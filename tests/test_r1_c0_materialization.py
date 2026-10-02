"""Static, fail-closed acceptance tests for the R1-to-C0 evidence binding."""

import base64
import copy
import hashlib
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, validators


ROOT = Path(__file__).parents[1]
MAPPING_SCHEMA_PATH = ROOT / "schemas" / "r1-c0-materialization-v1.schema.json"
MAPPING_GOLDEN_PATH = ROOT / "schemas" / "r1-c0-materialization-v1.golden.json"
C0_SCHEMA_PATH = ROOT / "schemas" / "strategy-contract-v1.schema.json"
C0_GOLDEN_PATH = ROOT / "schemas" / "strategy-contract-v1.golden.json"
C0_TEST_PATH = ROOT / "tests" / "test_strategy_contract.py"

MIN_I64 = -(2 ** 63)
MAX_I64 = 2 ** 63 - 1
MAPPING_VERSION = 1
_C0_FIXED_PROFILE = {
    "idealized_cost_bps": 0,
    "idealized_latency_events": 0,
    "realistic_cost_bps": 7,
    "realistic_latency_events": 1,
    "stressed_cost_bps": 21,
    "stressed_latency_events": 3,
}
_R1_CANDIDATE_KEYS = {
    "candidate_id",
    "code_sha256",
    "config_sha256",
    "feature_sha256",
    "score_units",
    "selected_event_count",
    "snapshot_id",
    "strategy_family_id",
    "threshold_units",
    "version",
}
_R1_MANIFEST_KEYS = {
    "candidate_ids",
    "candidate_metrics",
    "code_sha256",
    "config_sha256",
    "feature_sha256",
    "row_count",
    "screening_manifest_id",
    "selected_candidate_id",
    "snapshot_id",
    "strategy_family_id",
    "trace_id",
    "version",
}
_R1_TRACE_KEYS = {"candidate_id", "frames", "snapshot_id", "trace_id", "version"}


class MaterializationError(ValueError):
    """The static R1-to-C0 materialization evidence is invalid."""


def _canonical_bytes(value):
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def _sha256(value):
    return _sha256_bytes(_canonical_bytes(value))


def _component_id(component, id_key):
    material = dict(component)
    material.pop(id_key, None)
    return _sha256(material)


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise MaterializationError("duplicate JSON object key: %s" % key)
        result[key] = value
    return result


def _reject_json_constant(value):
    raise MaterializationError("non-finite JSON constant: %s" % value)


def _parse_strict(raw):
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MaterializationError("malformed UTF-8 JSON") from error


def _is_strict_integer(_checker, instance):
    return type(instance) is int


STRICT_TYPE_CHECKER = Draft202012Validator.TYPE_CHECKER.redefine(
    "integer", _is_strict_integer
)
StrictDraft202012Validator = validators.extend(
    Draft202012Validator, type_checker=STRICT_TYPE_CHECKER
)
FORMAT_CHECKER = FormatChecker()


@FORMAT_CHECKER.checks("trading-os-strict-integer")
def _strict_integer_format(value):
    return type(value) is int


def _assert_strict_numbers(value):
    if isinstance(value, dict):
        for nested in value.values():
            _assert_strict_numbers(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_strict_numbers(nested)
    elif isinstance(value, (bool, float)):
        raise MaterializationError("booleans and floats are not canonical integers")


def _require_exact_keys(value, keys, label):
    if not isinstance(value, dict) or set(value) != keys:
        raise MaterializationError("%s field set is invalid" % label)


def _require_i64(value, label):
    if type(value) is not int or value < MIN_I64 or value > MAX_I64:
        raise MaterializationError("%s is outside signed integer range" % label)


def _require_nonnegative_i64(value, label):
    _require_i64(value, label)
    if value < 0:
        raise MaterializationError("%s must be non-negative" % label)


def _decode_canonical(encoded, declared_sha256, label):
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (TypeError, ValueError) as error:
        raise MaterializationError("%s is not base64" % label) from error
    if _sha256_bytes(raw) != declared_sha256:
        raise MaterializationError("%s raw SHA-256 mismatch" % label)
    document = _parse_strict(raw)
    _assert_strict_numbers(document)
    if _canonical_bytes(document) != raw:
        raise MaterializationError("%s is not canonical UTF-8 JSON" % label)
    return document, raw


def _rebuild_source_binding(vector):
    source = vector["r1_source"]
    vector["r1_source_bundle_sha256"] = _sha256(
        {
            "candidate_raw_sha256": source["candidate_raw_sha256"],
            "manifest_raw_sha256": source["manifest_raw_sha256"],
            "trace_raw_sha256": source["trace_raw_sha256"],
        }
    )
    vector["materialization_id"] = _sha256(
        {
            "mapping_version": vector["mapping_version"],
            "r1_source_bundle_sha256": vector["r1_source_bundle_sha256"],
            "c0_contract_wire_sha256": vector["c0_contract_wire_sha256"],
        }
    )


def _replace_source_document(vector, kind, document, raw=None):
    fields = {
        "candidate": (
            "candidate_canonical_utf8_base64",
            "candidate_raw_sha256",
            "candidate_id",
            "candidate_id",
        ),
        "manifest": (
            "manifest_canonical_utf8_base64",
            "manifest_raw_sha256",
            "screening_manifest_id",
            "screening_manifest_id",
        ),
        "trace": (
            "trace_canonical_utf8_base64",
            "trace_raw_sha256",
            "trace_id",
            "trace_id",
        ),
    }
    encoded_key, raw_sha_key, wrapper_id_key, document_id_key = fields[kind]
    raw = _canonical_bytes(document) if raw is None else raw
    source = vector["r1_source"]
    source[encoded_key] = base64.b64encode(raw).decode("ascii")
    source[raw_sha_key] = _sha256_bytes(raw)
    if document_id_key in document:
        source[wrapper_id_key] = document[document_id_key]
    _rebuild_source_binding(vector)


def _replace_c0_document(vector, document, raw=None):
    raw = _canonical_bytes(document) if raw is None else raw
    vector["c0_contract_wire_utf8_base64"] = base64.b64encode(raw).decode("ascii")
    vector["c0_contract_wire_sha256"] = _sha256_bytes(raw)
    _rebuild_source_binding(vector)


def _rebuild_c0_component_ids(document):
    candidate = document["strategy_candidate"]
    package = document["strategy_package"]
    trace = document["frozen_trace"]
    candidate["candidate_id"] = _component_id(candidate, "candidate_id")
    package["candidate_id"] = candidate["candidate_id"]
    package["package_id"] = _component_id(package, "package_id")
    trace["package_id"] = package["package_id"]
    trace["trace_id"] = _component_id(trace, "trace_id")


class MaterializationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mapping_schema = json.loads(MAPPING_SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.c0_schema = json.loads(C0_SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.mapping_schema)
        Draft202012Validator.check_schema(cls.c0_schema)
        cls.mapping_validator = StrictDraft202012Validator(
            cls.mapping_schema, format_checker=FORMAT_CHECKER
        )
        cls.c0_validator = StrictDraft202012Validator(
            cls.c0_schema, format_checker=FORMAT_CHECKER
        )
        cls.golden = json.loads(MAPPING_GOLDEN_PATH.read_text(encoding="utf-8"))

    def assert_valid(self, vector):
        errors = sorted(
            self.mapping_validator.iter_errors(vector), key=lambda error: error.json_path
        )
        if errors:
            raise MaterializationError(errors[0].message)
        _assert_strict_numbers(vector)

        source = vector["r1_source"]
        candidate, candidate_raw = _decode_canonical(
            source["candidate_canonical_utf8_base64"],
            source["candidate_raw_sha256"],
            "R1 candidate",
        )
        manifest, manifest_raw = _decode_canonical(
            source["manifest_canonical_utf8_base64"],
            source["manifest_raw_sha256"],
            "R1 manifest",
        )
        trace, trace_raw = _decode_canonical(
            source["trace_canonical_utf8_base64"],
            source["trace_raw_sha256"],
            "R1 trace",
        )
        self._assert_r1_source(candidate, manifest, trace, source)
        self.assertEqual(
            vector["r1_source_bundle_sha256"],
            _sha256(
                {
                    "candidate_raw_sha256": _sha256_bytes(candidate_raw),
                    "manifest_raw_sha256": _sha256_bytes(manifest_raw),
                    "trace_raw_sha256": _sha256_bytes(trace_raw),
                }
            ),
        )

        c0_document, c0_raw = _decode_canonical(
            vector["c0_contract_wire_utf8_base64"],
            vector["c0_contract_wire_sha256"],
            "C0 contract wire",
        )
        c0_errors = sorted(
            self.c0_validator.iter_errors(c0_document), key=lambda error: error.json_path
        )
        if c0_errors:
            raise MaterializationError(c0_errors[0].message)
        self._assert_c0_semantics(c0_document)
        self._assert_materialization(candidate, manifest, trace, c0_document)
        self.assertEqual(
            vector["materialization_id"],
            _sha256(
                {
                    "mapping_version": vector["mapping_version"],
                    "r1_source_bundle_sha256": vector["r1_source_bundle_sha256"],
                    "c0_contract_wire_sha256": _sha256_bytes(c0_raw),
                }
            ),
        )
        return candidate, manifest, trace, c0_document

    def assert_rejected(self, vector):
        with self.assertRaises((MaterializationError, AssertionError)):
            self.assert_valid(vector)

    def _assert_r1_source(self, candidate, manifest, trace, wrapper):
        _require_exact_keys(candidate, _R1_CANDIDATE_KEYS, "R1 candidate")
        _require_exact_keys(manifest, _R1_MANIFEST_KEYS, "R1 manifest")
        _require_exact_keys(trace, _R1_TRACE_KEYS, "R1 trace")
        self.assertEqual(candidate["version"], "r1-screening-candidate-v1")
        self.assertEqual(manifest["version"], "r1-vectorized-screening-v1")
        self.assertEqual(trace["version"], "r1-frozen-simulation-trace-v1")
        self.assertEqual(candidate["candidate_id"], _component_id(candidate, "candidate_id"))
        self.assertEqual(
            manifest["screening_manifest_id"],
            _component_id(manifest, "screening_manifest_id"),
        )
        self.assertEqual(trace["trace_id"], _component_id(trace, "trace_id"))
        self.assertEqual(wrapper["candidate_id"], candidate["candidate_id"])
        self.assertEqual(
            wrapper["screening_manifest_id"], manifest["screening_manifest_id"]
        )
        self.assertEqual(wrapper["trace_id"], trace["trace_id"])
        _require_nonnegative_i64(candidate["threshold_units"], "R1 threshold")
        _require_nonnegative_i64(candidate["selected_event_count"], "R1 event count")
        _require_nonnegative_i64(candidate["score_units"], "R1 score")
        _require_nonnegative_i64(manifest["row_count"], "R1 row count")
        self.assertLessEqual(candidate["selected_event_count"], manifest["row_count"])
        self.assertIsInstance(trace["frames"], list)
        self.assertTrue(trace["frames"])
        self.assertEqual(candidate["selected_event_count"], len(trace["frames"]))
        state = 0
        absolute_score = 0
        previous_source_sequence = None
        for sequence, frame in enumerate(trace["frames"]):
            _require_exact_keys(
                frame,
                {"expected_state_units", "operand_units", "sequence", "source_sequence"},
                "R1 trace frame",
            )
            self.assertEqual(frame["sequence"], sequence)
            _require_nonnegative_i64(frame["source_sequence"], "R1 source sequence")
            self.assertLess(frame["source_sequence"], manifest["row_count"])
            if previous_source_sequence is not None:
                self.assertGreater(frame["source_sequence"], previous_source_sequence)
            previous_source_sequence = frame["source_sequence"]
            _require_i64(frame["operand_units"], "R1 trace operand")
            if frame["operand_units"] == MIN_I64:
                raise MaterializationError("R1 trace operand cannot be negated safely")
            state += frame["operand_units"]
            _require_i64(state, "R1 trace state")
            self.assertEqual(frame["expected_state_units"], state)
            absolute_score += abs(frame["operand_units"])
            _require_nonnegative_i64(absolute_score, "R1 trace score")
        self.assertEqual(candidate["score_units"], absolute_score)
        self.assertEqual(manifest["selected_candidate_id"], candidate["candidate_id"])
        self.assertIn(candidate["candidate_id"], manifest["candidate_ids"])
        self.assertEqual(len(manifest["candidate_ids"]), len(set(manifest["candidate_ids"])))
        metrics = [
            item
            for item in manifest["candidate_metrics"]
            if item.get("candidate_id") == candidate["candidate_id"]
        ]
        self.assertEqual(len(metrics), 1)
        metric = metrics[0]
        _require_exact_keys(
            metric,
            {"candidate_id", "rank", "score_units", "selected_event_count", "threshold_units"},
            "R1 candidate metric",
        )
        self.assertEqual(metric["rank"], 0)
        for key in ("score_units", "selected_event_count", "threshold_units"):
            self.assertEqual(metric[key], candidate[key])
        for key in (
            "code_sha256",
            "config_sha256",
            "feature_sha256",
            "snapshot_id",
            "strategy_family_id",
        ):
            self.assertEqual(manifest[key], candidate[key])
        self.assertEqual(manifest["trace_id"], trace["trace_id"])
        self.assertEqual(trace["candidate_id"], candidate["candidate_id"])
        self.assertEqual(trace["snapshot_id"], candidate["snapshot_id"])

    def _rewrite_r1_chain(
        self,
        vector,
        *,
        score_units,
        selected_event_count,
        final_source_sequence=None,
    ):
        source = vector["r1_source"]
        candidate, _ = _decode_canonical(
            source["candidate_canonical_utf8_base64"],
            source["candidate_raw_sha256"],
            "R1 candidate",
        )
        trace, _ = _decode_canonical(
            source["trace_canonical_utf8_base64"],
            source["trace_raw_sha256"],
            "R1 trace",
        )
        manifest, _ = _decode_canonical(
            source["manifest_canonical_utf8_base64"],
            source["manifest_raw_sha256"],
            "R1 manifest",
        )
        candidate["score_units"] = score_units
        candidate["selected_event_count"] = selected_event_count
        candidate["candidate_id"] = _component_id(candidate, "candidate_id")
        if final_source_sequence is not None:
            trace["frames"][-1]["source_sequence"] = final_source_sequence
        trace["candidate_id"] = candidate["candidate_id"]
        trace["trace_id"] = _component_id(trace, "trace_id")
        manifest["candidate_ids"] = [candidate["candidate_id"]]
        manifest["selected_candidate_id"] = candidate["candidate_id"]
        manifest["candidate_metrics"] = [{
            "candidate_id": candidate["candidate_id"],
            "rank": 0,
            "score_units": score_units,
            "selected_event_count": selected_event_count,
            "threshold_units": candidate["threshold_units"],
        }]
        manifest["trace_id"] = trace["trace_id"]
        manifest["screening_manifest_id"] = _component_id(
            manifest, "screening_manifest_id"
        )
        _replace_source_document(vector, "candidate", candidate)
        _replace_source_document(vector, "trace", trace)
        _replace_source_document(vector, "manifest", manifest)

    def _assert_c0_semantics(self, document):
        candidate = document["strategy_candidate"]
        package = document["strategy_package"]
        trace = document["frozen_trace"]
        self.assertEqual(candidate["candidate_id"], _component_id(candidate, "candidate_id"))
        self.assertEqual(package["package_id"], _component_id(package, "package_id"))
        self.assertEqual(trace["trace_id"], _component_id(trace, "trace_id"))
        self.assertEqual(package["candidate_id"], candidate["candidate_id"])
        self.assertEqual(trace["package_id"], package["package_id"])
        self.assertEqual(trace["data_snapshot_id"], candidate["data_snapshot_id"])
        names = [item["name"] for item in candidate["parameter_vector"]]
        self.assertEqual(names, sorted(names))
        self.assertEqual(len(names), len(set(names)))
        profile = package["cost_latency_profile"]
        self.assertLessEqual(profile["idealized_cost_bps"], profile["realistic_cost_bps"])
        self.assertLessEqual(profile["realistic_cost_bps"], profile["stressed_cost_bps"])
        self.assertLessEqual(
            profile["idealized_latency_events"], profile["realistic_latency_events"]
        )
        self.assertLessEqual(
            profile["realistic_latency_events"], profile["stressed_latency_events"]
        )
        state = package["initial_state_units"]
        limit = package["max_abs_state_units"]
        self.assertLessEqual(abs(state), limit)
        for sequence, frame in enumerate(trace["frames"]):
            self.assertEqual(frame["sequence"], sequence)
            self.assertEqual(frame["operation"], "ACCUMULATE")
            state += frame["operand_units"]
            _require_i64(state, "C0 trace state")
            self.assertLessEqual(abs(state), limit)
            self.assertEqual(frame["expected_state_units"], state)

    def _assert_materialization(self, candidate, manifest, r1_trace, c0_document):
        c0_candidate = c0_document["strategy_candidate"]
        c0_package = c0_document["strategy_package"]
        c0_trace = c0_document["frozen_trace"]
        self.assertNotEqual(c0_candidate["candidate_id"], candidate["candidate_id"])
        self.assertNotEqual(c0_trace["trace_id"], r1_trace["trace_id"])
        self.assertEqual(c0_candidate["strategy_family_id"], candidate["strategy_family_id"])
        self.assertEqual(c0_candidate["data_snapshot_id"], candidate["snapshot_id"])
        self.assertEqual(c0_candidate["code_sha256"], candidate["code_sha256"])
        self.assertEqual(c0_candidate["config_sha256"], candidate["config_sha256"])
        self.assertEqual(
            c0_candidate["experiment_run_id"],
            _sha256(
                {
                    "mapping_version": MAPPING_VERSION,
                    "r1_screening_manifest_id": manifest["screening_manifest_id"],
                    "r1_candidate_id": candidate["candidate_id"],
                    "r1_snapshot_id": candidate["snapshot_id"],
                    "r1_code_sha256": candidate["code_sha256"],
                    "r1_config_sha256": candidate["config_sha256"],
                }
            ),
        )
        self.assertEqual(
            c0_candidate["parameter_vector"],
            [{"name": "decision_threshold_units", "value": candidate["threshold_units"]}],
        )
        self.assertEqual(c0_package["kernel_id"], "generic-accumulator-v1")
        self.assertEqual(c0_package["execution_capability"], "RESEARCH_SIMULATION_ONLY")
        self.assertEqual(c0_package["initial_state_units"], 0)
        self.assertEqual(c0_package["max_abs_state_units"], 1000000)
        self.assertEqual(c0_package["cost_latency_profile"], _C0_FIXED_PROFILE)
        expected_frames = [
            {
                "sequence": index,
                "operation": "ACCUMULATE",
                "operand_units": frame["operand_units"],
                "expected_state_units": frame["expected_state_units"],
            }
            for index, frame in enumerate(r1_trace["frames"])
        ]
        self.assertEqual(c0_trace["frames"], expected_frames)
        self.assertTrue(
            all("source_sequence" not in frame for frame in c0_trace["frames"])
        )

    def test_golden_vector_is_static_canonical_and_preserves_c0_inputs(self):
        self.assertEqual(
            _sha256_bytes(C0_SCHEMA_PATH.read_bytes()),
            "3ca7d20a848e8ad2f48a355354594ea54305f47910d4f5f8450b78fc050cd16f",
        )
        self.assertEqual(
            _sha256_bytes(C0_GOLDEN_PATH.read_bytes()),
            "a63884526bccc368d6fdc3e7dcf76f82fd69ad8fd82c7f201a58702d74f1b46c",
        )
        self.assertEqual(
            _sha256_bytes(C0_TEST_PATH.read_bytes()),
            "d34786c66ab2502197c1cd249dfdf9b7c016f6bc7845fc9f776be2866a87d669",
        )
        candidate, manifest, trace, document = self.assert_valid(self.golden)
        self.assertEqual(document["strategy_candidate"]["strategy_family_id"], candidate["strategy_family_id"])
        self.assertEqual(manifest["trace_id"], trace["trace_id"])

    def test_hash_id_and_source_linkage_tampering_fail_closed(self):
        raw_hash = copy.deepcopy(self.golden)
        raw_hash["r1_source"]["candidate_raw_sha256"] = "0" * 64
        self.assert_rejected(raw_hash)

        wrapper_id = copy.deepcopy(self.golden)
        wrapper_id["r1_source"]["candidate_id"] = "f" * 64
        self.assert_rejected(wrapper_id)

        cross_link = copy.deepcopy(self.golden)
        manifest, _ = _decode_canonical(
            cross_link["r1_source"]["manifest_canonical_utf8_base64"],
            cross_link["r1_source"]["manifest_raw_sha256"],
            "R1 manifest",
        )
        manifest["selected_candidate_id"] = "f" * 64
        manifest["screening_manifest_id"] = _component_id(
            manifest, "screening_manifest_id"
        )
        _replace_source_document(cross_link, "manifest", manifest)
        self.assert_rejected(cross_link)

        source_sequence = copy.deepcopy(self.golden)
        trace, _ = _decode_canonical(
            source_sequence["r1_source"]["trace_canonical_utf8_base64"],
            source_sequence["r1_source"]["trace_raw_sha256"],
            "R1 trace",
        )
        trace["frames"][1]["source_sequence"] = trace["frames"][0]["source_sequence"]
        trace["trace_id"] = _component_id(trace, "trace_id")
        _replace_source_document(source_sequence, "trace", trace)
        self.assert_rejected(source_sequence)

    def test_c0_mapping_profile_frame_and_identity_tampering_fail_closed(self):
        parameter = copy.deepcopy(self.golden)
        document, _ = _decode_canonical(
            parameter["c0_contract_wire_utf8_base64"],
            parameter["c0_contract_wire_sha256"],
            "C0 contract wire",
        )
        document["strategy_candidate"]["parameter_vector"][0]["value"] = 6
        _rebuild_c0_component_ids(document)
        _replace_c0_document(parameter, document)
        self.assert_rejected(parameter)

        profile = copy.deepcopy(self.golden)
        document, _ = _decode_canonical(
            profile["c0_contract_wire_utf8_base64"],
            profile["c0_contract_wire_sha256"],
            "C0 contract wire",
        )
        document["strategy_package"]["cost_latency_profile"]["stressed_cost_bps"] = 22
        _rebuild_c0_component_ids(document)
        _replace_c0_document(profile, document)
        self.assert_rejected(profile)

        source_sequence_leak = copy.deepcopy(self.golden)
        document, _ = _decode_canonical(
            source_sequence_leak["c0_contract_wire_utf8_base64"],
            source_sequence_leak["c0_contract_wire_sha256"],
            "C0 contract wire",
        )
        document["frozen_trace"]["frames"][0]["source_sequence"] = 10
        _rebuild_c0_component_ids(document)
        _replace_c0_document(source_sequence_leak, document)
        self.assert_rejected(source_sequence_leak)

        id_substitution = copy.deepcopy(self.golden)
        document, _ = _decode_canonical(
            id_substitution["c0_contract_wire_utf8_base64"],
            id_substitution["c0_contract_wire_sha256"],
            "C0 contract wire",
        )
        document["strategy_candidate"]["candidate_id"] = "0" * 64
        _replace_c0_document(id_substitution, document)
        self.assert_rejected(id_substitution)

    def test_r1_trace_score_and_count_invariants_fail_closed(self):
        wrong_score = copy.deepcopy(self.golden)
        self._rewrite_r1_chain(
            wrong_score,
            score_units=14,
            selected_event_count=3,
        )
        self.assert_rejected(wrong_score)

        wrong_count = copy.deepcopy(self.golden)
        self._rewrite_r1_chain(
            wrong_count,
            score_units=15,
            selected_event_count=2,
        )
        self.assert_rejected(wrong_count)

        out_of_range_source_sequence = copy.deepcopy(self.golden)
        self._rewrite_r1_chain(
            out_of_range_source_sequence,
            score_units=15,
            selected_event_count=3,
            final_source_sequence=23,
        )
        self.assert_rejected(out_of_range_source_sequence)

    def test_noncanonical_duplicate_numeric_and_unknown_values_fail_closed(self):
        raw = base64.b64decode(
            self.golden["c0_contract_wire_utf8_base64"], validate=True
        )
        for replacement in (b"5.0", b"true", b"5e0"):
            vector = copy.deepcopy(self.golden)
            self.assertIn(b'"value":5', raw)
            _replace_c0_document(
                vector,
                {},
                raw=raw.replace(b'"value":5', b'"value":' + replacement, 1),
            )
            self.assert_rejected(vector)

        leading_space = copy.deepcopy(self.golden)
        _replace_c0_document(leading_space, {}, raw=b" " + raw)
        self.assert_rejected(leading_space)

        duplicate = copy.deepcopy(self.golden)
        _replace_c0_document(
            duplicate, {}, raw=raw[:-1] + b',"schema_version":1}'
        )
        self.assert_rejected(duplicate)

        unknown = copy.deepcopy(self.golden)
        unknown["unexpected"] = "field"
        self.assert_rejected(unknown)

        with self.assertRaises(MaterializationError):
            _parse_strict(b'{"mapping_version":1,"mapping_version":1}')


if __name__ == "__main__":
    unittest.main()
