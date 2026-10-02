use base64::{engine::general_purpose::STANDARD, Engine as _};
use serde_json::Value;
use sha2::{Digest, Sha256};
use trading_os_strategy_runtime::{export_c1_b0_evidence, C2MaterializationBinding, LedgerKind};

const C2_GOLDEN: &str = include_str!("../../../schemas/r1-c0-materialization-v1.golden.json");
const C2_RAW_WIRE_SHA256: &str = "2ae93b68cc46be4824d2f97c2ef7e159bfb8a19ed768f71a4ba9a67b99a25c3d";
const C2_MATERIALIZATION_ID: &str =
    "9513176db3ac26eac59407ced49e507e2ef09d30cff52692decb921957ae461d";
const R1_SOURCE_BUNDLE_SHA256: &str =
    "ace6e9bd88853e1c3d0409fec331466d02ee844389b01258903f665fd27672f1";
const C2_CANDIDATE_ID: &str = "bbd7da0000c6d4174c9a0ce4a58480321b116b191702c6f440b2568733490222";
const C2_PACKAGE_ID: &str = "26f2add2d7145a7bff4d3095c4f0131427656f0a2935eed0b85b666f32e11993";
const C2_TRACE_ID: &str = "36958098fa84512d96b309e2ef8b6bf0ca4602c8219c065faa852ade717e473f";
const C3_EXPORT_SHA256: &str = "3c33cbebeaeba52582e0eb90a19744fc85a77f1f27e4445a12d8b70c3c56408b";
const IDEALIZED_EVENT_HASH: &str =
    "cc0d355d428e6f8104ab94a8517f5da19d958894f13f0c7c5c600b4c072e8e86";
const IDEALIZED_STATE_HASH: &str =
    "ce07bb0697bdc12a5aea713e0f03a916103c1fd4bb866a613d2ed2d7cf089615";
const REALISTIC_EVENT_HASH: &str =
    "e17bc3e9be164cae88a22f61e3f3fb70702ed1624093406b8539ec7454171eae";
const REALISTIC_STATE_HASH: &str =
    "ca11fa42ec14e6f5d86344db55feb8bd6bb47ddd29fc42d85a6870507ccac602";
const STRESSED_EVENT_HASH: &str =
    "5c3ea1b415a66a5dd2ed543a19e599247c835a0ac51e8c3a9af23996deb6e94d";
const STRESSED_STATE_HASH: &str =
    "f4741674c1035e4bbe0c550c68564e8852a0bc53bef755ef4a39143b9db2ef4c";
const RECONCILIATION_HASH: &str =
    "ac7c1e6de307037c19df5ab93066cb69532b9f369bc868274fc1f45f9a8ef79f";

fn golden() -> Value {
    serde_json::from_str(C2_GOLDEN).expect("C2 materialization golden JSON")
}

fn c2_wire() -> Vec<u8> {
    STANDARD
        .decode(
            golden()["c0_contract_wire_utf8_base64"]
                .as_str()
                .expect("C2 raw wire base64"),
        )
        .expect("C2 raw wire bytes")
}

fn binding() -> C2MaterializationBinding<'static> {
    C2MaterializationBinding {
        mapping_version: 1,
        materialization_id: C2_MATERIALIZATION_ID,
        r1_source_bundle_sha256: R1_SOURCE_BUNDLE_SHA256,
        expected_c0_contract_wire_sha256: C2_RAW_WIRE_SHA256,
    }
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

fn assert_ledger(
    document: &Value,
    key: &str,
    kind: LedgerKind,
    event_hash: &str,
    state_hash: &str,
    cost_bps: u64,
    latency_events: u64,
) {
    let ledger = &document["b0"][key];
    assert_eq!(ledger["ledger"], serde_json::to_value(kind).unwrap());
    assert_eq!(ledger["source_trace_id"], C2_TRACE_ID);
    assert_eq!(ledger["event_hash"], event_hash);
    assert_eq!(ledger["state_hash"], state_hash);
    assert_eq!(ledger["cost_bps"], cost_bps);
    assert_eq!(ledger["latency_events"], latency_events);
    assert_eq!(ledger["final_state_units"], 9);
    assert_eq!(ledger["input_frame_count"], 3);
    assert_eq!(ledger["applied_event_count"], 3);
    assert_eq!(ledger["cumulative_cost_units"], 0);
}

#[test]
fn c2_wire_exports_deterministic_c1_b0_evidence_with_independent_ledgers() {
    let raw = c2_wire();
    assert_eq!(sha256_hex(&raw), C2_RAW_WIRE_SHA256);

    let first = export_c1_b0_evidence(&raw, binding()).expect("C2 export must verify");
    let second = export_c1_b0_evidence(&raw, binding()).expect("repeat C2 export must verify");
    assert_eq!(first, second);
    assert_eq!(first.sha256(), sha256_hex(first.canonical_bytes()));
    assert_eq!(first.sha256(), C3_EXPORT_SHA256);
    assert_eq!(first.canonical_bytes(), second.canonical_bytes());

    let document: Value =
        serde_json::from_slice(first.canonical_bytes()).expect("C3 export canonical JSON");
    let source: Value = serde_json::from_slice(&raw).expect("C2 C0 contract JSON");
    assert_eq!(document["export_version"], 1);
    assert_eq!(document["c2"]["mapping_version"], 1);
    assert_eq!(document["c2"]["materialization_id"], C2_MATERIALIZATION_ID);
    assert_eq!(
        document["c2"]["r1_source_bundle_sha256"],
        R1_SOURCE_BUNDLE_SHA256
    );
    assert_eq!(document["c0"]["raw_c0_wire_sha256"], C2_RAW_WIRE_SHA256);
    assert_eq!(document["c0"]["candidate_id"], C2_CANDIDATE_ID);
    assert_eq!(document["c0"]["package_id"], C2_PACKAGE_ID);
    assert_eq!(document["c0"]["trace_id"], C2_TRACE_ID);
    assert_eq!(
        document["c0"]["data_snapshot_id"],
        source["strategy_candidate"]["data_snapshot_id"]
    );
    assert_eq!(
        document["c0"]["experiment_run_id"],
        source["strategy_candidate"]["experiment_run_id"]
    );
    assert_eq!(
        document["c0"]["code_sha256"],
        source["strategy_candidate"]["code_sha256"]
    );
    assert_eq!(
        document["c0"]["config_sha256"],
        source["strategy_candidate"]["config_sha256"]
    );
    assert_eq!(
        document["c0"]["strategy_family_id"],
        source["strategy_candidate"]["strategy_family_id"]
    );
    assert_eq!(document["c1"]["final_state_units"], 9);
    assert_eq!(document["c1"]["frame_count"], 3);

    assert_eq!(document["b0"]["source_trace_id"], C2_TRACE_ID);
    assert_eq!(document["b0"]["reconciliation_hash"], RECONCILIATION_HASH);
    assert_ledger(
        &document,
        "idealized",
        LedgerKind::Idealized,
        IDEALIZED_EVENT_HASH,
        IDEALIZED_STATE_HASH,
        0,
        0,
    );
    assert_ledger(
        &document,
        "realistic_paper",
        LedgerKind::RealisticPaper,
        REALISTIC_EVENT_HASH,
        REALISTIC_STATE_HASH,
        7,
        1,
    );
    assert_ledger(
        &document,
        "stressed",
        LedgerKind::Stressed,
        STRESSED_EVENT_HASH,
        STRESSED_STATE_HASH,
        21,
        3,
    );
}

#[test]
fn c2_binding_and_raw_contract_mismatches_fail_closed() {
    let raw = c2_wire();

    let wrong_raw_sha256 = "0".repeat(64);
    let wrong_raw_sha = C2MaterializationBinding {
        expected_c0_contract_wire_sha256: &wrong_raw_sha256,
        ..binding()
    };
    assert!(export_c1_b0_evidence(&raw, wrong_raw_sha).is_err());

    let wrong_materialization_id = "0".repeat(64);
    let wrong_materialization = C2MaterializationBinding {
        materialization_id: &wrong_materialization_id,
        ..binding()
    };
    assert!(export_c1_b0_evidence(&raw, wrong_materialization).is_err());

    let unsupported_mapping = C2MaterializationBinding {
        mapping_version: 2,
        ..binding()
    };
    assert!(export_c1_b0_evidence(&raw, unsupported_mapping).is_err());

    let noncanonical = [b" ".as_slice(), raw.as_slice()].concat();
    assert!(export_c1_b0_evidence(&noncanonical, binding()).is_err());

    let historical: Value = serde_json::from_str(include_str!(
        "../../../schemas/strategy-contract-v1.golden.json"
    ))
    .expect("historical C0 golden JSON");
    let historical_raw = STANDARD
        .decode(
            historical["wire_utf8_base64"]
                .as_str()
                .expect("historical C0 raw wire base64"),
        )
        .expect("historical C0 raw wire bytes");
    assert!(export_c1_b0_evidence(&historical_raw, binding()).is_err());
}
