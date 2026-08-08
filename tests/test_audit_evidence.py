import copy
import unittest

from trading_os_bridge.audit_evidence import EvidenceValidationError, validate_remediation_evidence
from trading_os_bridge.retention import RetentionPlanError, plan_quarantine_dry_run


BASE_COMMIT = "218414d8dcf967862dc66bbaaa3b2dc23c89106e"
SOURCE_HASH = "a" * 64


def evidence_record():
    source_hashes = {"o1-controlled-remediation": SOURCE_HASH}
    return {
        "target_commit": BASE_COMMIT,
        "source_hashes": source_hashes,
        "research_boundary": {
            "domain": "strategy_research_cloud_domain",
            "repository_owned_path": False,
            "execution_imports_research": False,
        },
        "controls": {"three_ledger": True, "holdout": True, "trial_registry": True},
        "gate_observations": {
            gate: {
                "source": "o1-controlled-remediation",
                "source_sha256": SOURCE_HASH,
                "status": "OBSERVED",
                "scope": "target-commit bounded fixture",
            }
            for gate in ("D1-02", "D1-03", "D1-04", "D1-05", "D1-06")
        },
        "maintenance": {
            "criteria": "single-purpose modules and explicit boundaries",
            "scope": "audit remediation surface only",
            "observation": "all named gates are source-bound",
        },
        "authority_state": {
            "implementation_authority": False,
            "activation_authority": False,
            "bridge_write_authority": False,
            "freeze_authority": False,
            "claim_authority": False,
            "live_trading_authority": False,
        },
    }


class AuditEvidenceTests(unittest.TestCase):
    def test_complete_record_requires_every_gate_to_be_source_bound(self):
        validate_remediation_evidence(evidence_record())

    def test_research_cannot_be_made_a_repository_writer_or_execution_dependency(self):
        for key in ("repository_owned_path", "execution_imports_research"):
            record = evidence_record()
            record["research_boundary"][key] = True
            with self.subTest(key=key), self.assertRaises(EvidenceValidationError):
                validate_remediation_evidence(record)

    def test_missing_or_mismatched_semantic_source_fails_closed(self):
        missing_gate = evidence_record()
        del missing_gate["gate_observations"]["D1-05"]
        with self.assertRaises(EvidenceValidationError):
            validate_remediation_evidence(missing_gate)

        mismatched_hash = evidence_record()
        mismatched_hash["gate_observations"]["D1-04"]["source_sha256"] = "b" * 64
        with self.assertRaises(EvidenceValidationError):
            validate_remediation_evidence(mismatched_hash)

    def test_authority_escalation_fails_closed(self):
        record = evidence_record()
        record["authority_state"]["activation_authority"] = True
        with self.assertRaises(EvidenceValidationError):
            validate_remediation_evidence(record)


class RetentionDryRunTests(unittest.TestCase):
    def test_dry_run_is_deterministic_and_state_preserving(self):
        candidates = ["var/archive/old.json", "var/outbox/old.json"]
        before = copy.deepcopy(candidates)
        first = plan_quarantine_dry_run(candidates, ["var/inbox/live.json"])
        second = plan_quarantine_dry_run(reversed(candidates), ["var/inbox/live.json"])
        self.assertEqual(candidates, before)
        self.assertEqual(first, second)
        self.assertEqual(first.candidates, ("var/archive/old.json", "var/outbox/old.json"))
        self.assertEqual(len(first.rollback_manifest_sha256), 64)

    def test_dry_run_rejects_protected_or_ambiguous_paths(self):
        with self.assertRaises(RetentionPlanError):
            plan_quarantine_dry_run(["var/archive/live.json"], ["var/archive/live.json"])
        with self.assertRaises(RetentionPlanError):
            plan_quarantine_dry_run(["../outside.json"])


if __name__ == "__main__":
    unittest.main()
