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

/// The deterministic cost-and-latency projection applied to one verified trace.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum LedgerKind {
    #[serde(rename = "IDEALIZED")]
    Idealized,
    #[serde(rename = "REALISTIC_PAPER")]
    RealisticPaper,
    #[serde(rename = "STRESSED")]
    Stressed,
}

/// Immutable, hash-bound result of one pure in-memory ledger projection.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct LedgerOutcome {
    pub ledger: LedgerKind,
    pub source_trace_id: String,
    pub cost_bps: u64,
    pub latency_events: u64,
    pub event_hash: String,
    pub state_hash: String,
    pub final_state_units: i64,
    pub input_frame_count: usize,
    pub applied_event_count: usize,
    pub cumulative_cost_units: u64,
}

/// Reconciled projections for one already verified canonical frozen trace.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ThreeLedgerOutcome {
    pub source_trace_id: String,
    pub idealized: LedgerOutcome,
    pub realistic_paper: LedgerOutcome,
    pub stressed: LedgerOutcome,
    pub reconciliation_hash: String,
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

/// Replay the same verified trace as deterministic idealized, realistic, and
/// stressed in-memory projections. This is a generic simulation utility only.
pub fn replay_three_ledgers(
    contract: &VerifiedContract,
) -> Result<ThreeLedgerOutcome, ContractError> {
    replay_document(&contract.document)?;
    let profile = &contract.document.strategy_package.cost_latency_profile;
    let idealized = replay_projection(
        contract,
        LedgerKind::Idealized,
        profile.idealized_cost_bps,
        profile.idealized_latency_events,
    )?;
    let realistic_paper = replay_projection(
        contract,
        LedgerKind::RealisticPaper,
        profile.realistic_cost_bps,
        profile.realistic_latency_events,
    )?;
    let stressed = replay_projection(
        contract,
        LedgerKind::Stressed,
        profile.stressed_cost_bps,
        profile.stressed_latency_events,
    )?;
    validate_reconciliation(&idealized, &realistic_paper, &stressed)?;

    let reconciliation = ReconciliationMaterial {
        source_trace_id: &idealized.source_trace_id,
        idealized: &idealized,
        realistic_paper: &realistic_paper,
        stressed: &stressed,
    };
    let reconciliation_hash = sha256_hex(&canonical_json(&reconciliation)?);
    Ok(ThreeLedgerOutcome {
        source_trace_id: idealized.source_trace_id.clone(),
        idealized,
        realistic_paper,
        stressed,
        reconciliation_hash,
    })
}

/// Verify canonical C0 wire bytes, then produce all three deterministic replay
/// projections in one pure in-memory operation.
pub fn verify_and_replay_three_ledgers(raw: &[u8]) -> Result<ThreeLedgerOutcome, ContractError> {
    let contract = verify_contract(raw)?;
    replay_three_ledgers(&contract)
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

#[derive(Serialize)]
struct LedgerEvent {
    applied_sequence: u64,
    cost_units: u64,
    input_sequence: u64,
    net_operand_units: i64,
    operand_units: i64,
    state_after_units: i64,
}

#[derive(Serialize)]
struct LedgerStateMaterial<'a> {
    applied_event_count: usize,
    cost_bps: u64,
    cumulative_cost_units: u64,
    event_hash: &'a str,
    final_state_units: i64,
    input_frame_count: usize,
    latency_events: u64,
    ledger: LedgerKind,
    source_trace_id: &'a str,
}

#[derive(Serialize)]
struct ReconciliationMaterial<'a> {
    idealized: &'a LedgerOutcome,
    realistic_paper: &'a LedgerOutcome,
    source_trace_id: &'a str,
    stressed: &'a LedgerOutcome,
}

struct PendingFrame<'a> {
    apply_sequence: u64,
    frame: &'a TraceFrame,
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

fn replay_projection(
    contract: &VerifiedContract,
    ledger: LedgerKind,
    cost_bps: u64,
    latency_events: u64,
) -> Result<LedgerOutcome, ContractError> {
    let document = &contract.document;
    let package = &document.strategy_package;
    let frames = &document.frozen_trace.frames;
    let mut pending = Vec::with_capacity(frames.len());
    let mut next_pending = 0_usize;
    let mut events = Vec::with_capacity(frames.len());
    let mut state = package.initial_state_units;
    let mut cumulative_cost_units = 0_u64;

    for frame in frames {
        let apply_sequence = frame
            .sequence
            .checked_add(latency_events)
            .ok_or_else(|| ContractError::new("ledger latency sequence overflows u64"))?;
        pending.push(PendingFrame {
            apply_sequence,
            frame,
        });
        while next_pending < pending.len() && pending[next_pending].apply_sequence <= frame.sequence
        {
            apply_pending_frame(
                &pending[next_pending],
                cost_bps,
                &mut state,
                &mut cumulative_cost_units,
                package.max_abs_state_units,
                &mut events,
            )?;
            next_pending += 1;
        }
    }
    while next_pending < pending.len() {
        apply_pending_frame(
            &pending[next_pending],
            cost_bps,
            &mut state,
            &mut cumulative_cost_units,
            package.max_abs_state_units,
            &mut events,
        )?;
        next_pending += 1;
    }

    if events.len() != frames.len() {
        return Err(ContractError::new(
            "ledger did not apply every source frame",
        ));
    }
    let event_hash = sha256_hex(&canonical_json(&events)?);
    let source_trace_id = contract.trace_id().to_owned();
    let state_material = LedgerStateMaterial {
        applied_event_count: events.len(),
        cost_bps,
        cumulative_cost_units,
        event_hash: &event_hash,
        final_state_units: state,
        input_frame_count: frames.len(),
        latency_events,
        ledger,
        source_trace_id: &source_trace_id,
    };
    let state_hash = sha256_hex(&canonical_json(&state_material)?);
    Ok(LedgerOutcome {
        ledger,
        source_trace_id,
        cost_bps,
        latency_events,
        event_hash,
        state_hash,
        final_state_units: state,
        input_frame_count: frames.len(),
        applied_event_count: events.len(),
        cumulative_cost_units,
    })
}

fn apply_pending_frame(
    pending: &PendingFrame<'_>,
    cost_bps: u64,
    state: &mut i64,
    cumulative_cost_units: &mut u64,
    max_abs_state_units: u64,
    events: &mut Vec<LedgerEvent>,
) -> Result<(), ContractError> {
    if let Some(previous) = events.last() {
        if previous.input_sequence >= pending.frame.sequence
            || previous.applied_sequence >= pending.apply_sequence
        {
            return Err(ContractError::new(
                "ledger event ordering is not strictly increasing",
            ));
        }
    }
    let cost_units = cost_units(pending.frame.operand_units, cost_bps)?;
    let cost_as_i64 = i64::try_from(cost_units)
        .map_err(|_| ContractError::new("ledger cost exceeds i64 range"))?;
    let net_operand_units = pending
        .frame
        .operand_units
        .checked_sub(cost_as_i64)
        .ok_or_else(|| ContractError::new("ledger net operand overflows i64"))?;
    let next_state = state
        .checked_add(net_operand_units)
        .ok_or_else(|| ContractError::new("ledger transition overflows i64"))?;
    if next_state.unsigned_abs() > max_abs_state_units {
        return Err(ContractError::new(
            "ledger transition exceeds package bound",
        ));
    }
    *cumulative_cost_units = cumulative_cost_units
        .checked_add(cost_units)
        .ok_or_else(|| ContractError::new("ledger cumulative cost overflows u64"))?;
    *state = next_state;
    events.push(LedgerEvent {
        applied_sequence: pending.apply_sequence,
        cost_units,
        input_sequence: pending.frame.sequence,
        net_operand_units,
        operand_units: pending.frame.operand_units,
        state_after_units: next_state,
    });
    Ok(())
}

fn cost_units(operand_units: i64, cost_bps: u64) -> Result<u64, ContractError> {
    let scaled = (operand_units.unsigned_abs() as u128)
        .checked_mul(cost_bps as u128)
        .ok_or_else(|| ContractError::new("ledger cost multiplication overflows u128"))?;
    u64::try_from(scaled / 10_000_u128)
        .map_err(|_| ContractError::new("ledger cost exceeds u64 range"))
}

fn validate_reconciliation(
    idealized: &LedgerOutcome,
    realistic_paper: &LedgerOutcome,
    stressed: &LedgerOutcome,
) -> Result<(), ContractError> {
    if idealized.source_trace_id != realistic_paper.source_trace_id
        || idealized.source_trace_id != stressed.source_trace_id
    {
        return Err(ContractError::new("ledger source trace mismatch"));
    }
    if idealized.input_frame_count != realistic_paper.input_frame_count
        || idealized.input_frame_count != stressed.input_frame_count
        || idealized.applied_event_count != idealized.input_frame_count
        || realistic_paper.applied_event_count != realistic_paper.input_frame_count
        || stressed.applied_event_count != stressed.input_frame_count
    {
        return Err(ContractError::new("ledger event count mismatch"));
    }
    if idealized.cost_bps != 0
        || idealized.latency_events != 0
        || idealized.cumulative_cost_units != 0
    {
        return Err(ContractError::new("idealized ledger profile is not zero"));
    }
    if realistic_paper.cost_bps > stressed.cost_bps
        || realistic_paper.latency_events > stressed.latency_events
        || realistic_paper.cumulative_cost_units > stressed.cumulative_cost_units
    {
        return Err(ContractError::new("stressed ledger cost is not monotonic"));
    }
    if idealized.final_state_units < realistic_paper.final_state_units
        || realistic_paper.final_state_units < stressed.final_state_units
    {
        return Err(ContractError::new(
            "ledger final state is not cost monotonic",
        ));
    }
    Ok(())
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
