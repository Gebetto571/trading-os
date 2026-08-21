#![forbid(unsafe_code)]

//! Pure, in-memory verification and replay for the C0 Strategy Contract V1.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fmt;

const MAX_I64_AS_U64: u64 = i64::MAX as u64;
const MAX_PARAMETERS: usize = 128;
const MAX_TRACE_FRAMES: usize = 10_000;

/// A fail-closed C0 wire-contract validation or replay error.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ContractError {
    message: String,
}

impl ContractError {
    fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl fmt::Display for ContractError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl std::error::Error for ContractError {}

/// A verified immutable C0 contract held entirely in memory.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VerifiedContract {
    document: WireContract,
    raw_sha256: String,
}

impl VerifiedContract {
    /// SHA-256 of the verified raw canonical wire bytes.
    pub fn raw_sha256(&self) -> &str {
        &self.raw_sha256
    }

    /// C0 StrategyCandidate identity bound into this contract.
    pub fn candidate_id(&self) -> &str {
        &self.document.strategy_candidate.candidate_id
    }

    /// C0 StrategyPackage identity bound into this contract.
    pub fn package_id(&self) -> &str {
        &self.document.strategy_package.package_id
    }

    /// C0 FrozenTrace identity bound into this contract.
    pub fn trace_id(&self) -> &str {
        &self.document.frozen_trace.trace_id
    }
}

/// Deterministic result of replaying a verified generic accumulator trace.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ReplayOutcome {
    pub final_state_units: i64,
    pub frame_count: usize,
}

/// Decode, canonical-byte verify, and validate a C0 Strategy Contract V1.
pub fn verify_contract(raw: &[u8]) -> Result<VerifiedContract, ContractError> {
    let document: WireContract = serde_json::from_slice(raw)
        .map_err(|error| ContractError::new(format!("invalid contract JSON: {error}")))?;
    let canonical = canonical_json(&document)?;
    if raw != canonical.as_slice() {
        return Err(ContractError::new("contract wire bytes are not canonical"));
    }
    validate_document(&document)?;
    Ok(VerifiedContract {
        document,
        raw_sha256: sha256_hex(raw),
    })
}

/// Replay a verified C0 contract with checked, bounded integer arithmetic only.
pub fn replay_contract(contract: &VerifiedContract) -> Result<ReplayOutcome, ContractError> {
    replay_document(&contract.document)
}

/// Verify and replay the exact C0 wire bytes in one pure in-memory operation.
pub fn verify_and_replay(raw: &[u8]) -> Result<ReplayOutcome, ContractError> {
    let contract = verify_contract(raw)?;
    replay_contract(&contract)
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct WireContract {
    frozen_trace: FrozenTrace,
    schema_version: u64,
    strategy_candidate: StrategyCandidate,
    strategy_package: StrategyPackage,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct StrategyCandidate {
    candidate_id: String,
    code_sha256: String,
    config_sha256: String,
    data_snapshot_id: String,
    experiment_run_id: String,
    parameter_vector: Vec<Parameter>,
    strategy_family_id: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Parameter {
    name: String,
    value: i64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct StrategyPackage {
    candidate_id: String,
    cost_latency_profile: CostLatencyProfile,
    execution_capability: ExecutionCapability,
    initial_state_units: i64,
    kernel_id: KernelId,
    max_abs_state_units: u64,
    package_id: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct CostLatencyProfile {
    idealized_cost_bps: u64,
    idealized_latency_events: u64,
    realistic_cost_bps: u64,
    realistic_latency_events: u64,
    stressed_cost_bps: u64,
    stressed_latency_events: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
enum ExecutionCapability {
    #[serde(rename = "RESEARCH_SIMULATION_ONLY")]
    ResearchSimulationOnly,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
enum KernelId {
    #[serde(rename = "generic-accumulator-v1")]
    GenericAccumulatorV1,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct FrozenTrace {
    data_snapshot_id: String,
    frames: Vec<TraceFrame>,
    package_id: String,
    trace_id: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct TraceFrame {
    expected_state_units: i64,
    operand_units: i64,
    operation: TraceOperation,
    sequence: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
enum TraceOperation {
    #[serde(rename = "ACCUMULATE")]
    Accumulate,
}

#[derive(Serialize)]
struct CandidateMaterial<'a> {
    code_sha256: &'a str,
    config_sha256: &'a str,
    data_snapshot_id: &'a str,
    experiment_run_id: &'a str,
    parameter_vector: &'a [Parameter],
    strategy_family_id: &'a str,
}

#[derive(Serialize)]
struct PackageMaterial<'a> {
    candidate_id: &'a str,
    cost_latency_profile: &'a CostLatencyProfile,
    execution_capability: &'a ExecutionCapability,
    initial_state_units: i64,
    kernel_id: &'a KernelId,
    max_abs_state_units: u64,
}

#[derive(Serialize)]
struct TraceMaterial<'a> {
    data_snapshot_id: &'a str,
    frames: &'a [TraceFrame],
    package_id: &'a str,
}

fn validate_document(document: &WireContract) -> Result<(), ContractError> {
    if document.schema_version != 1 {
        return Err(ContractError::new("unsupported contract schema version"));
    }
    validate_candidate(&document.strategy_candidate)?;
    validate_package(&document.strategy_package)?;
    if document.strategy_package.candidate_id != document.strategy_candidate.candidate_id {
        return Err(ContractError::new("package candidate linkage mismatch"));
    }
    validate_trace(
        &document.frozen_trace,
        &document.strategy_candidate,
        &document.strategy_package,
    )?;
    replay_document(document).map(|_| ())
}

fn validate_candidate(candidate: &StrategyCandidate) -> Result<(), ContractError> {
    for (label, value) in [
        ("candidate_id", candidate.candidate_id.as_str()),
        ("code_sha256", candidate.code_sha256.as_str()),
        ("config_sha256", candidate.config_sha256.as_str()),
        ("data_snapshot_id", candidate.data_snapshot_id.as_str()),
        ("experiment_run_id", candidate.experiment_run_id.as_str()),
    ] {
        validate_sha256(label, value)?;
    }
    if !is_stable_name(&candidate.strategy_family_id) {
        return Err(ContractError::new("invalid strategy family identifier"));
    }
    if candidate.parameter_vector.is_empty() || candidate.parameter_vector.len() > MAX_PARAMETERS {
        return Err(ContractError::new("invalid parameter vector length"));
    }
    let mut previous_name: Option<&str> = None;
    for parameter in &candidate.parameter_vector {
        if !is_stable_name(&parameter.name) {
            return Err(ContractError::new("invalid parameter name"));
        }
        if previous_name.is_some_and(|previous| previous >= parameter.name.as_str()) {
            return Err(ContractError::new(
                "parameter names are not strictly sorted",
            ));
        }
        previous_name = Some(&parameter.name);
    }
    let material = CandidateMaterial {
        code_sha256: &candidate.code_sha256,
        config_sha256: &candidate.config_sha256,
        data_snapshot_id: &candidate.data_snapshot_id,
        experiment_run_id: &candidate.experiment_run_id,
        parameter_vector: &candidate.parameter_vector,
        strategy_family_id: &candidate.strategy_family_id,
    };
    if candidate.candidate_id != sha256_hex(&canonical_json(&material)?) {
        return Err(ContractError::new("candidate identity mismatch"));
    }
    Ok(())
}

fn validate_package(package: &StrategyPackage) -> Result<(), ContractError> {
    validate_sha256("package_id", &package.package_id)?;
    validate_sha256("package candidate_id", &package.candidate_id)?;
    if package.max_abs_state_units == 0 || package.max_abs_state_units > MAX_I64_AS_U64 {
        return Err(ContractError::new("invalid package state bound"));
    }
    if package.initial_state_units.unsigned_abs() > package.max_abs_state_units {
        return Err(ContractError::new("initial state exceeds package bound"));
    }
    validate_profile(&package.cost_latency_profile)?;
    let material = PackageMaterial {
        candidate_id: &package.candidate_id,
        cost_latency_profile: &package.cost_latency_profile,
        execution_capability: &package.execution_capability,
        initial_state_units: package.initial_state_units,
        kernel_id: &package.kernel_id,
        max_abs_state_units: package.max_abs_state_units,
    };
    if package.package_id != sha256_hex(&canonical_json(&material)?) {
        return Err(ContractError::new("package identity mismatch"));
    }
    Ok(())
}

fn validate_profile(profile: &CostLatencyProfile) -> Result<(), ContractError> {
    for value in [
        profile.idealized_cost_bps,
        profile.idealized_latency_events,
        profile.realistic_cost_bps,
        profile.realistic_latency_events,
        profile.stressed_cost_bps,
        profile.stressed_latency_events,
    ] {
        if value > MAX_I64_AS_U64 {
            return Err(ContractError::new("profile integer exceeds i64 range"));
        }
    }
    if profile.idealized_cost_bps != 0 || profile.idealized_latency_events != 0 {
        return Err(ContractError::new(
            "idealized profile must have zero cost and latency",
        ));
    }
    if profile.realistic_cost_bps > profile.stressed_cost_bps
        || profile.realistic_latency_events > profile.stressed_latency_events
    {
        return Err(ContractError::new(
            "cost and latency profile must be monotonic",
        ));
    }
    Ok(())
}

fn validate_trace(
    trace: &FrozenTrace,
    candidate: &StrategyCandidate,
    package: &StrategyPackage,
) -> Result<(), ContractError> {
    for (label, value) in [
        ("trace_id", trace.trace_id.as_str()),
        ("trace package_id", trace.package_id.as_str()),
        ("trace data_snapshot_id", trace.data_snapshot_id.as_str()),
    ] {
        validate_sha256(label, value)?;
    }
    if trace.frames.is_empty() || trace.frames.len() > MAX_TRACE_FRAMES {
        return Err(ContractError::new("invalid frozen trace length"));
    }
    if trace.package_id != package.package_id {
        return Err(ContractError::new("trace package linkage mismatch"));
    }
    if trace.data_snapshot_id != candidate.data_snapshot_id {
        return Err(ContractError::new("trace snapshot linkage mismatch"));
    }
    for (index, frame) in trace.frames.iter().enumerate() {
        if frame.sequence != index as u64 {
            return Err(ContractError::new("trace sequence is not contiguous"));
        }
    }
    let material = TraceMaterial {
        data_snapshot_id: &trace.data_snapshot_id,
        frames: &trace.frames,
        package_id: &trace.package_id,
    };
    if trace.trace_id != sha256_hex(&canonical_json(&material)?) {
        return Err(ContractError::new("trace identity mismatch"));
    }
    Ok(())
}

fn replay_document(document: &WireContract) -> Result<ReplayOutcome, ContractError> {
    let package = &document.strategy_package;
    let mut state = package.initial_state_units;
    for frame in &document.frozen_trace.frames {
        let next_state = state
            .checked_add(frame.operand_units)
            .ok_or_else(|| ContractError::new("accumulator transition overflows i64"))?;
        if next_state.unsigned_abs() > package.max_abs_state_units {
            return Err(ContractError::new(
                "accumulator transition exceeds package bound",
            ));
        }
        if frame.expected_state_units != next_state {
            return Err(ContractError::new("accumulator trace state mismatch"));
        }
        state = next_state;
    }
    Ok(ReplayOutcome {
        final_state_units: state,
        frame_count: document.frozen_trace.frames.len(),
    })
}

fn validate_sha256(label: &str, value: &str) -> Result<(), ContractError> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(ContractError::new(format!("invalid {label} SHA-256")));
    }
    Ok(())
}

fn is_stable_name(value: &str) -> bool {
    let bytes = value.as_bytes();
    (3..=64).contains(&bytes.len())
        && bytes[0].is_ascii_lowercase()
        && bytes[1..].iter().all(|byte| {
            byte.is_ascii_lowercase() || byte.is_ascii_digit() || *byte == b'_' || *byte == b'-'
        })
}

fn canonical_json<T: Serialize>(value: &T) -> Result<Vec<u8>, ContractError> {
    serde_json::to_vec(value)
        .map_err(|error| ContractError::new(format!("canonical serialization failed: {error}")))
}

fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    let mut output = String::with_capacity(digest.len() * 2);
    for byte in digest {
        use fmt::Write as _;
        let _ = write!(output, "{byte:02x}");
    }
    output
}
