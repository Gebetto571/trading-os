"""Fail-closed validation for remediation evidence records.

This module validates evidence *about* an audit boundary.  It neither starts an
execution service nor gives a research domain a repository-writing capability.
"""

from __future__ import annotations

import re
from collections.abc import Mapping


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_CONTROL_KEYS = frozenset({"three_ledger", "holdout", "trial_registry"})
REQUIRED_GATES = frozenset({"D1-02", "D1-03", "D1-04", "D1-05", "D1-06"})


class EvidenceValidationError(ValueError):
    """Raised when a remediation evidence record is incomplete or unsafe."""


def validate_remediation_evidence(record: Mapping[str, object]) -> None:
    """Validate a source-bound audit record without interpreting it as approval.

    The evidence is intentionally data-only: all privileged capabilities must be
    false, research remains a non-repository cloud domain, and every named gate
    must be tied to a SHA-256 identified source.
    """

    _require_exact_keys(
        record,
        {
            "target_commit",
            "source_hashes",
            "research_boundary",
            "controls",
            "gate_observations",
            "maintenance",
            "authority_state",
        },
    )
    target_commit = _require_string(record["target_commit"], "target_commit")
    if not COMMIT_RE.fullmatch(target_commit):
        raise EvidenceValidationError("target_commit tam 40 karakterlik SHA olmalı")

    source_hashes = record["source_hashes"]
    if not isinstance(source_hashes, Mapping) or not source_hashes:
        raise EvidenceValidationError("source_hashes boş olmayan bir nesne olmalı")
    for name, value in source_hashes.items():
        if not isinstance(name, str) or not name or not isinstance(value, str) or not SHA256_RE.fullmatch(value):
            raise EvidenceValidationError("her kaynak adı ve SHA-256 değeri geçerli olmalı")

    research = record["research_boundary"]
    _require_exact_keys(research, {"domain", "repository_owned_path", "execution_imports_research"})
    if research["domain"] != "strategy_research_cloud_domain":
        raise EvidenceValidationError("araştırma alanı strategy_research_cloud_domain olmalı")
    if research["repository_owned_path"] is not False or research["execution_imports_research"] is not False:
        raise EvidenceValidationError("araştırma alanı repo-yazarı veya execution bağımlılığı olamaz")

    controls = record["controls"]
    if not isinstance(controls, Mapping) or set(controls) != REQUIRED_CONTROL_KEYS:
        raise EvidenceValidationError("three_ledger, holdout ve trial_registry kontrolleri zorunlu")
    if any(value is not True for value in controls.values()):
        raise EvidenceValidationError("tüm araştırma kontrolleri açıkça true olmalı")

    observations = record["gate_observations"]
    if not isinstance(observations, Mapping) or set(observations) != REQUIRED_GATES:
        raise EvidenceValidationError("D1-02 ile D1-06 gözlemlerinin tamamı zorunlu")
    for gate, observation in observations.items():
        _require_exact_keys(observation, {"source", "source_sha256", "status", "scope"})
        source = _require_string(observation["source"], f"{gate}.source")
        if source not in source_hashes:
            raise EvidenceValidationError(f"{gate} bilinmeyen bir kaynağa bağlı")
        if observation["source_sha256"] != source_hashes[source]:
            raise EvidenceValidationError(f"{gate} kaynak hash'i eşleşmiyor")
        if observation["status"] not in {"OBSERVED", "NOT_EVIDENCED"}:
            raise EvidenceValidationError(f"{gate} geçersiz gözlem durumu")
        _require_string(observation["scope"], f"{gate}.scope")

    maintenance = record["maintenance"]
    _require_exact_keys(maintenance, {"criteria", "scope", "observation"})
    for key in maintenance:
        _require_string(maintenance[key], f"maintenance.{key}")

    authority = record["authority_state"]
    _require_exact_keys(
        authority,
        {
            "implementation_authority",
            "activation_authority",
            "bridge_write_authority",
            "freeze_authority",
            "claim_authority",
            "live_trading_authority",
        },
    )
    if any(value is not False for value in authority.values()):
        raise EvidenceValidationError("kanıt kaydı uygulama veya aktivasyon yetkisi üretemez")


def _require_exact_keys(value: object, expected: set[str]) -> None:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise EvidenceValidationError("kanıt nesnesi beklenen alanları tam taşımalı")


def _require_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceValidationError(f"{field} boş olmayan metin olmalı")
    return value
