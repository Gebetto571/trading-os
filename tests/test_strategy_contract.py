"""Static acceptance tests for the non-executable Strategy Contract V1."""

import base64
import copy
import hashlib
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, validators


ROOT = Path(__file__).parents[1]
SCHEMA_PATH = ROOT / "schemas/strategy-contract-v1.schema.json"
GOLDEN_PATH = ROOT / "schemas/strategy-contract-v1.golden.json"
MIN_I64 = -(2 ** 63)
MAX_I64 = 2 ** 63 - 1


class ContractError(ValueError):
    """The static contract or its canonical wire representation is invalid."""


def _canonical_bytes(value):
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value):
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _component_id(component, id_key):
    material = dict(component)
    material.pop(id_key, None)
    return _sha256(material)


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("duplicate JSON object key: %s" % key)
        result[key] = value
    return result


def _reject_json_constant(value):
    raise ContractError("non-finite JSON constant: %s" % value)


def _parse_strict(raw):
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("malformed UTF-8 JSON") from exc


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


def _all_strict_integers(value):
    if isinstance(value, dict):
        return all(_all_strict_integers(item) for item in value.values())
    if isinstance(value, list):
        return all(_all_strict_integers(item) for item in value)
    return not isinstance(value, (bool, float))


def _assert_semantics(document):
    if not _all_strict_integers(document):
        raise ContractError("booleans and floats are not contract integers")

    candidate = document["strategy_candidate"]
    package = document["strategy_package"]
    trace = document["frozen_trace"]
    if candidate["candidate_id"] != _component_id(candidate, "candidate_id"):
        raise ContractError("candidate identity mismatch")
    if package["package_id"] != _component_id(package, "package_id"):
        raise ContractError("package identity mismatch")
    if trace["trace_id"] != _component_id(trace, "trace_id"):
        raise ContractError("trace identity mismatch")
    if package["candidate_id"] != candidate["candidate_id"]:
        raise ContractError("package candidate linkage mismatch")
    if trace["package_id"] != package["package_id"]:
        raise ContractError("trace package linkage mismatch")
    if trace["data_snapshot_id"] != candidate["data_snapshot_id"]:
        raise ContractError("trace snapshot linkage mismatch")

    parameter_names = [item["name"] for item in candidate["parameter_vector"]]
    if parameter_names != sorted(parameter_names) or len(set(parameter_names)) != len(parameter_names):
        raise ContractError("parameter vector must be strictly sorted and unique")

    profile = package["cost_latency_profile"]
    if not (
        profile["idealized_cost_bps"]
        <= profile["realistic_cost_bps"]
        <= profile["stressed_cost_bps"]
    ):
        raise ContractError("cost profile must be monotonic")
    if not (
        profile["idealized_latency_events"]
        <= profile["realistic_latency_events"]
        <= profile["stressed_latency_events"]
    ):
        raise ContractError("latency profile must be monotonic")

    state = package["initial_state_units"]
    limit = package["max_abs_state_units"]
    if abs(state) > limit:
        raise ContractError("initial state exceeds package bound")
    frames = trace["frames"]
    if [frame["sequence"] for frame in frames] != list(range(len(frames))):
        raise ContractError("trace sequence must be contiguous and monotonic")
    for frame in frames:
        next_state = state + frame["operand_units"]
        if next_state < MIN_I64 or next_state > MAX_I64:
            raise ContractError("accumulator transition overflows i64")
        if abs(next_state) > limit:
            raise ContractError("accumulator transition exceeds package bound")
        if frame["expected_state_units"] != next_state:
            raise ContractError("trace frame state mismatch")
        state = next_state


class StrategyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = StrictDraft202012Validator(
            cls.schema, format_checker=FORMAT_CHECKER
        )
        cls.vector = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        cls.golden_wire = base64.b64decode(
            cls.vector["wire_utf8_base64"], validate=True
        )
        cls.golden_document = _parse_strict(cls.golden_wire)

    def assert_contract_valid(self, document):
        errors = sorted(self.validator.iter_errors(document), key=lambda error: error.json_path)
        if errors:
            raise ContractError(errors[0].message)
        _assert_semantics(document)

    def assert_contract_rejected(self, document):
        with self.assertRaises(ContractError):
            self.assert_contract_valid(document)

    def assert_wire_valid(self, raw):
        document = _parse_strict(raw)
        if _canonical_bytes(document) != raw:
            raise ContractError("wire is not canonical UTF-8 JSON")
        self.assert_contract_valid(document)
        return document

    def test_schema_is_draft_2020_12_and_golden_wire_is_immutable(self):
        self.assertEqual(
            self.schema["$schema"],
            "https://json-schema.org/draft/2020-12/schema",
        )
        self.assertEqual(self.vector["vector_version"], 1)
        self.assertEqual(self.vector["wire_encoding"], "utf-8-canonical-json-v1")
        self.assertEqual(
            hashlib.sha256(self.golden_wire).hexdigest(),
            self.vector["wire_sha256"],
        )
        self.assertEqual(self.assert_wire_valid(self.golden_wire), self.golden_document)
        self.assertEqual(
            self.golden_document["strategy_candidate"]["candidate_id"],
            self.vector["candidate_id"],
        )
        self.assertEqual(
            self.golden_document["strategy_package"]["package_id"],
            self.vector["package_id"],
        )
        self.assertEqual(
            self.golden_document["frozen_trace"]["trace_id"],
            self.vector["trace_id"],
        )

    def test_invalid_versions_unknown_fields_and_capabilities_fail_closed(self):
        invalid_version = copy.deepcopy(self.golden_document)
        invalid_version["schema_version"] = 2
        self.assert_contract_rejected(invalid_version)

        extra = copy.deepcopy(self.golden_document)
        extra["strategy_package"]["broker_endpoint"] = "https://example.invalid"
        self.assert_contract_rejected(extra)

        executable = copy.deepcopy(self.golden_document)
        executable["strategy_package"]["execution_capability"] = "PAPER_TRADING"
        self.assert_contract_rejected(executable)

    def test_all_numeric_contract_values_are_strict_json_integers(self):
        float_value = copy.deepcopy(self.golden_document)
        float_value["strategy_candidate"]["parameter_vector"][0]["value"] = 1.0
        self.assertFalse(list(Draft202012Validator(self.schema).iter_errors(float_value)))
        self.assert_contract_rejected(float_value)

        boolean_value = copy.deepcopy(self.golden_document)
        boolean_value["strategy_package"]["max_abs_state_units"] = True
        self.assert_contract_rejected(boolean_value)

        exponent_wire = self.golden_wire.replace(
            b'"max_abs_state_units":1000000',
            b'"max_abs_state_units":1e6',
            1,
        )
        with self.assertRaises(ContractError):
            self.assert_wire_valid(exponent_wire)

    def test_identity_linkage_and_parameter_order_fail_closed(self):
        wrong_candidate_hash = copy.deepcopy(self.golden_document)
        wrong_candidate_hash["strategy_candidate"]["code_sha256"] = "a" * 64
        self.assert_contract_rejected(wrong_candidate_hash)

        linkage = copy.deepcopy(self.golden_document)
        linkage["frozen_trace"]["package_id"] = "b" * 64
        self.assert_contract_rejected(linkage)

        unordered = copy.deepcopy(self.golden_document)
        unordered["strategy_candidate"]["parameter_vector"].reverse()
        self.assert_contract_rejected(unordered)

    def test_trace_and_stress_constraints_fail_closed(self):
        duplicate_sequence = copy.deepcopy(self.golden_document)
        duplicate_sequence["frozen_trace"]["frames"][1]["sequence"] = 0
        self.assert_contract_rejected(duplicate_sequence)

        non_monotonic_profile = copy.deepcopy(self.golden_document)
        non_monotonic_profile["strategy_package"]["cost_latency_profile"]["stressed_cost_bps"] = 6
        self.assert_contract_rejected(non_monotonic_profile)

        bad_transition = copy.deepcopy(self.golden_document)
        bad_transition["frozen_trace"]["frames"][2]["expected_state_units"] = 8
        self.assert_contract_rejected(bad_transition)

    def test_malformed_duplicate_and_noncanonical_wire_fail_closed(self):
        with self.assertRaises(ContractError):
            _parse_strict(b'{"schema_version":1,"schema_version":1}')

        with self.assertRaises(ContractError):
            _parse_strict(b'{"schema_version":NaN}')

        with self.assertRaises(ContractError):
            self.assert_wire_valid(b" " + self.golden_wire)


if __name__ == "__main__":
    unittest.main()
