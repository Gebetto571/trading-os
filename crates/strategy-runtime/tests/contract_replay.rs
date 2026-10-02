use base64::{engine::general_purpose::STANDARD, Engine as _};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use trading_os_strategy_runtime::{replay_contract, verify_and_replay, verify_contract};

const GOLDEN_VECTOR: &str = include_str!("../../../schemas/strategy-contract-v1.golden.json");
const GOLDEN_WIRE_SHA256: &str = "484e0b3b58d889ad4d579a51220f55fdfc3338d9747cdb5b0460e383c124731b";
const CANDIDATE_ID: &str = "3806c8a4df7712b78918f87d5ae1a37da1910d31ffaee25f7ae63fb7b9ee95d3";
const PACKAGE_ID: &str = "20e2aad37ce83d935f1b0ea237182bb68b2ad9786f0487438b08c2a5d8609402";
const TRACE_ID: &str = "381966131194b9fd672fa6246726a5bc4f93cdb823c30e599f8b050eae4e4bef";

fn golden_wire() -> Vec<u8> {
    let wrapper: Value = serde_json::from_str(GOLDEN_VECTOR).expect("golden wrapper JSON");
    STANDARD
        .decode(
            wrapper["wire_utf8_base64"]
                .as_str()
                .expect("golden base64 string"),
        )
        .expect("golden base64 bytes")
}

fn golden_document() -> Value {
    serde_json::from_slice(&golden_wire()).expect("golden contract JSON")
}

fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    let mut output = String::with_capacity(digest.len() * 2);
    for byte in digest {
        use std::fmt::Write as _;
        let _ = write!(output, "{byte:02x}");
    }
    output
}

fn canonical(value: &Value) -> Vec<u8> {
    serde_json::to_vec(value).expect("canonical test JSON")
}

fn component_id(component: &Map<String, Value>, id_key: &str) -> String {
    let mut material = component.clone();
    material.remove(id_key);
    sha256_hex(&canonical(&Value::Object(material)))
}

fn refresh_candidate(document: &mut Value) {
    let candidate = document["strategy_candidate"]
        .as_object_mut()
        .expect("candidate object");
    let candidate_id = component_id(candidate, "candidate_id");
    candidate.insert("candidate_id".to_owned(), Value::String(candidate_id));
}

fn refresh_package(document: &mut Value) {
    let package = document["strategy_package"]
        .as_object_mut()
        .expect("package object");
    let package_id = component_id(package, "package_id");
    package.insert("package_id".to_owned(), Value::String(package_id));
}

fn refresh_trace(document: &mut Value) {
    let trace = document["frozen_trace"]
        .as_object_mut()
        .expect("trace object");
    let trace_id = component_id(trace, "trace_id");
    trace.insert("trace_id".to_owned(), Value::String(trace_id));
}

fn refresh_all(document: &mut Value) {
    refresh_candidate(document);
    let candidate_id = document["strategy_candidate"]["candidate_id"]
        .as_str()
        .expect("candidate ID")
        .to_owned();
    let snapshot_id = document["strategy_candidate"]["data_snapshot_id"]
        .as_str()
        .expect("snapshot ID")
        .to_owned();
    document["strategy_package"]["candidate_id"] = Value::String(candidate_id);
    refresh_package(document);
    let package_id = document["strategy_package"]["package_id"]
        .as_str()
        .expect("package ID")
        .to_owned();
    document["frozen_trace"]["package_id"] = Value::String(package_id);
    document["frozen_trace"]["data_snapshot_id"] = Value::String(snapshot_id);
    refresh_trace(document);
}

fn assert_rejected(raw: &[u8]) {
    assert!(
        verify_contract(raw).is_err(),
        "contract was accepted: {raw:?}"
    );
}

#[test]
fn c0_golden_wire_verifies_and_replays_deterministically() {
    let raw = golden_wire();
    assert_eq!(sha256_hex(&raw), GOLDEN_WIRE_SHA256);

    let verified = verify_contract(&raw).expect("C0 golden contract must verify");
    assert_eq!(verified.raw_sha256(), GOLDEN_WIRE_SHA256);
    assert_eq!(verified.candidate_id(), CANDIDATE_ID);
    assert_eq!(verified.package_id(), PACKAGE_ID);
    assert_eq!(verified.trace_id(), TRACE_ID);

    let first = replay_contract(&verified).expect("verified replay must succeed");
    let second = verify_and_replay(&raw).expect("combined replay must succeed");
    assert_eq!(first, second);
    assert_eq!(first.final_state_units, 9);
    assert_eq!(first.frame_count, 3);
}

#[test]
fn noncanonical_and_noninteger_wire_representations_fail_closed() {
    let raw = golden_wire();
    assert_rejected(&[b" ".as_slice(), raw.as_slice()].concat());
    assert_rejected(&serde_json::to_vec_pretty(&golden_document()).expect("pretty JSON"));

    let escaped_ascii = String::from_utf8(raw.clone())
        .expect("ASCII golden")
        .replace("generic-accumulator-v1", "generic-\\u0061ccumulator-v1")
        .into_bytes();
    assert_rejected(&escaped_ascii);

    let float_value = String::from_utf8(raw.clone())
        .expect("ASCII golden")
        .replace("\"value\":125", "\"value\":125.0")
        .into_bytes();
    assert_rejected(&float_value);

    let exponent_value = String::from_utf8(raw.clone())
        .expect("ASCII golden")
        .replace("\"value\":125", "\"value\":1.25e2")
        .into_bytes();
    assert_rejected(&exponent_value);

    let boolean_value = String::from_utf8(raw)
        .expect("ASCII golden")
        .replace("\"value\":125", "\"value\":true")
        .into_bytes();
    assert_rejected(&boolean_value);
}

#[test]
fn duplicate_unknown_version_hash_and_linkage_inputs_fail_closed() {
    let raw = golden_wire();
    let duplicate = String::from_utf8(raw.clone())
        .expect("ASCII golden")
        .replace("\"value\":125", "\"value\":125,\"value\":125")
        .into_bytes();
    assert_rejected(&duplicate);

    let mut unknown_field = golden_document();
    unknown_field["strategy_package"]["order"] = Value::String("forbidden".to_owned());
    refresh_all(&mut unknown_field);
    assert_rejected(&canonical(&unknown_field));

    let mut wrong_version = golden_document();
    wrong_version["schema_version"] = Value::from(2_u64);
    assert_rejected(&canonical(&wrong_version));

    let mut wrong_hash = golden_document();
    wrong_hash["strategy_candidate"]["candidate_id"] = Value::String("0".repeat(64));
    assert_rejected(&canonical(&wrong_hash));

    let mut linkage = golden_document();
    linkage["frozen_trace"]["package_id"] = Value::String("f".repeat(64));
    refresh_trace(&mut linkage);
    assert_rejected(&canonical(&linkage));

    let mut package_candidate_linkage = golden_document();
    package_candidate_linkage["strategy_package"]["candidate_id"] = Value::String("a".repeat(64));
    refresh_package(&mut package_candidate_linkage);
    let package_id = package_candidate_linkage["strategy_package"]["package_id"]
        .as_str()
        .expect("package ID")
        .to_owned();
    package_candidate_linkage["frozen_trace"]["package_id"] = Value::String(package_id);
    refresh_trace(&mut package_candidate_linkage);
    assert_rejected(&canonical(&package_candidate_linkage));
}

#[test]
fn semantic_rejections_reach_checked_replay_after_rehashing() {
    let mut unordered_parameters = golden_document();
    unordered_parameters["strategy_candidate"]["parameter_vector"]
        .as_array_mut()
        .expect("parameter vector")
        .reverse();
    refresh_all(&mut unordered_parameters);
    assert_rejected(&canonical(&unordered_parameters));

    let mut nonmonotonic_profile = golden_document();
    nonmonotonic_profile["strategy_package"]["cost_latency_profile"]["stressed_cost_bps"] =
        Value::from(6_u64);
    refresh_all(&mut nonmonotonic_profile);
    assert_rejected(&canonical(&nonmonotonic_profile));

    let mut duplicate_sequence = golden_document();
    duplicate_sequence["frozen_trace"]["frames"][1]["sequence"] = Value::from(0_u64);
    refresh_trace(&mut duplicate_sequence);
    assert_rejected(&canonical(&duplicate_sequence));

    let mut out_of_bounds = golden_document();
    out_of_bounds["strategy_package"]["max_abs_state_units"] = Value::from(6_u64);
    refresh_all(&mut out_of_bounds);
    assert_rejected(&canonical(&out_of_bounds));

    let mut overflow = golden_document();
    overflow["strategy_package"]["initial_state_units"] = Value::from(i64::MAX);
    overflow["strategy_package"]["max_abs_state_units"] = Value::from(i64::MAX as u64);
    overflow["frozen_trace"]["frames"][0]["operand_units"] = Value::from(1_i64);
    overflow["frozen_trace"]["frames"][0]["expected_state_units"] = Value::from(i64::MAX);
    refresh_all(&mut overflow);
    assert_rejected(&canonical(&overflow));

    let mut minimum = golden_document();
    minimum["strategy_package"]["max_abs_state_units"] = Value::from(i64::MAX as u64);
    minimum["frozen_trace"]["frames"][0]["operand_units"] = Value::from(i64::MIN);
    minimum["frozen_trace"]["frames"][0]["expected_state_units"] = Value::from(i64::MIN);
    refresh_all(&mut minimum);
    assert_rejected(&canonical(&minimum));
}

#[test]
fn trace_length_cap_is_enforced_after_component_rehashing() {
    let mut document = golden_document();
    let frames = document["frozen_trace"]["frames"]
        .as_array_mut()
        .expect("trace frames");
    frames.clear();
    for sequence in 0_u64..=10_000 {
        frames.push(serde_json::json!({
            "expected_state_units": 0,
            "operand_units": 0,
            "operation": "ACCUMULATE",
            "sequence": sequence,
        }));
    }
    refresh_trace(&mut document);
    assert_rejected(&canonical(&document));
}

#[test]
fn crate_has_no_execution_core_dependency() {
    let manifest = include_str!("../Cargo.toml");
    assert!(!manifest.contains("execution-core"));
    assert!(!manifest.contains("tokio"));
    assert!(!manifest.contains("reqwest"));
}
