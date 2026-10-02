use base64::{engine::general_purpose::STANDARD, Engine as _};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use trading_os_strategy_runtime::{
    replay_three_ledgers, verify_and_replay_three_ledgers, verify_contract, LedgerKind,
};

const GOLDEN_VECTOR: &str = include_str!("../../../schemas/strategy-contract-v1.golden.json");
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

#[test]
fn golden_trace_produces_three_deterministic_reconciled_ledgers() {
    let raw = golden_wire();
    let first = verify_and_replay_three_ledgers(&raw).expect("golden B0 replay");
    let second = verify_and_replay_three_ledgers(&raw).expect("repeat golden B0 replay");

    assert_eq!(first, second);
    assert_eq!(first.source_trace_id, TRACE_ID);
    assert_eq!(first.idealized.ledger, LedgerKind::Idealized);
    assert_eq!(first.realistic_paper.ledger, LedgerKind::RealisticPaper);
    assert_eq!(first.stressed.ledger, LedgerKind::Stressed);
    assert_eq!(first.idealized.cost_bps, 0);
    assert_eq!(first.idealized.latency_events, 0);
    assert_eq!(first.realistic_paper.cost_bps, 7);
    assert_eq!(first.realistic_paper.latency_events, 1);
    assert_eq!(first.stressed.cost_bps, 21);
    assert_eq!(first.stressed.latency_events, 3);
    assert_eq!(first.idealized.final_state_units, 9);
    assert_eq!(first.realistic_paper.final_state_units, 9);
    assert_eq!(first.stressed.final_state_units, 9);
    assert_eq!(first.idealized.cumulative_cost_units, 0);
    assert_eq!(first.realistic_paper.cumulative_cost_units, 0);
    assert_eq!(first.stressed.cumulative_cost_units, 0);
    assert_eq!(first.idealized.applied_event_count, 3);
    assert_eq!(first.realistic_paper.applied_event_count, 3);
    assert_eq!(first.stressed.applied_event_count, 3);
    assert_ne!(first.idealized.event_hash, first.realistic_paper.event_hash);
    assert_ne!(first.realistic_paper.event_hash, first.stressed.event_hash);
    assert_ne!(first.idealized.state_hash, first.realistic_paper.state_hash);
}

#[test]
fn integer_costs_and_latency_are_monotonic_and_reconciled() {
    let mut document = golden_document();
    document["strategy_package"]["max_abs_state_units"] = Value::from(1_000_000_u64);
    document["strategy_package"]["cost_latency_profile"]["realistic_cost_bps"] =
        Value::from(1_000_u64);
    document["strategy_package"]["cost_latency_profile"]["realistic_latency_events"] =
        Value::from(1_u64);
    document["strategy_package"]["cost_latency_profile"]["stressed_cost_bps"] =
        Value::from(2_000_u64);
    document["strategy_package"]["cost_latency_profile"]["stressed_latency_events"] =
        Value::from(2_u64);
    document["frozen_trace"]["frames"] = serde_json::json!([
        {
            "expected_state_units": 100000,
            "operand_units": 100000,
            "operation": "ACCUMULATE",
            "sequence": 0
        },
        {
            "expected_state_units": 200000,
            "operand_units": 100000,
            "operation": "ACCUMULATE",
            "sequence": 1
        }
    ]);
    refresh_all(&mut document);

    let outcome = verify_and_replay_three_ledgers(&canonical(&document))
        .expect("large integer profile must replay");
    assert_eq!(outcome.idealized.final_state_units, 200_000);
    assert_eq!(outcome.realistic_paper.final_state_units, 180_000);
    assert_eq!(outcome.stressed.final_state_units, 160_000);
    assert_eq!(outcome.realistic_paper.cumulative_cost_units, 20_000);
    assert_eq!(outcome.stressed.cumulative_cost_units, 40_000);
    assert_ne!(
        outcome.idealized.event_hash,
        outcome.realistic_paper.event_hash
    );
    assert_ne!(
        outcome.realistic_paper.event_hash,
        outcome.stressed.event_hash
    );
    assert_ne!(outcome.idealized.state_hash, outcome.stressed.state_hash);
    assert_ne!(outcome.reconciliation_hash, "0".repeat(64));
}

#[test]
fn projection_bound_and_canonical_input_fail_closed() {
    let mut document = golden_document();
    document["strategy_package"]["max_abs_state_units"] = Value::from(100_u64);
    document["strategy_package"]["cost_latency_profile"]["realistic_cost_bps"] =
        Value::from(100_u64);
    document["strategy_package"]["cost_latency_profile"]["stressed_cost_bps"] =
        Value::from(100_u64);
    document["frozen_trace"]["frames"] = serde_json::json!([
        {
            "expected_state_units": -100,
            "operand_units": -100,
            "operation": "ACCUMULATE",
            "sequence": 0
        }
    ]);
    refresh_all(&mut document);
    let raw = canonical(&document);
    assert!(
        verify_contract(&raw).is_ok(),
        "baseline C1 contract remains valid"
    );
    assert!(
        verify_and_replay_three_ledgers(&raw).is_err(),
        "cost-adjusted bound breach must fail closed"
    );

    let golden = golden_wire();
    let noncanonical = [b" ".as_slice(), golden.as_slice()].concat();
    assert!(verify_and_replay_three_ledgers(&noncanonical).is_err());

    let mut oversized_cost = golden_document();
    oversized_cost["strategy_package"]["max_abs_state_units"] = Value::from(i64::MAX as u64);
    oversized_cost["strategy_package"]["cost_latency_profile"]["realistic_cost_bps"] =
        Value::from(i64::MAX as u64);
    oversized_cost["strategy_package"]["cost_latency_profile"]["stressed_cost_bps"] =
        Value::from(i64::MAX as u64);
    oversized_cost["frozen_trace"]["frames"] = serde_json::json!([
        {
            "expected_state_units": i64::MAX,
            "operand_units": i64::MAX,
            "operation": "ACCUMULATE",
            "sequence": 0
        }
    ]);
    refresh_all(&mut oversized_cost);
    let oversized_raw = canonical(&oversized_cost);
    assert!(verify_contract(&oversized_raw).is_ok());
    assert!(
        verify_and_replay_three_ledgers(&oversized_raw).is_err(),
        "unrepresentable basis-point cost must fail closed"
    );
}

#[test]
fn verified_contract_replay_is_identical_to_combined_operation() {
    let raw = golden_wire();
    let contract = verify_contract(&raw).expect("verified contract");
    assert_eq!(
        replay_three_ledgers(&contract).expect("verified three ledger replay"),
        verify_and_replay_three_ledgers(&raw).expect("combined three ledger replay")
    );
}
