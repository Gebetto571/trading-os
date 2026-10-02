import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from trading_os_bridge.audit_evidence import EvidenceValidationError, validate_remediation_evidence
import trading_os_bridge.retention as retention
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
    def setUp(self):
        self._repository = tempfile.TemporaryDirectory()
        self.addCleanup(self._repository.cleanup)
        self.root = Path(self._repository.name)
        subprocess.run(
            ["git", "init", "--quiet", str(self.root)],
            check=True,
            capture_output=True,
        )
        self._outside = tempfile.TemporaryDirectory()
        self.addCleanup(self._outside.cleanup)
        self.outside_root = Path(self._outside.name)

    def _write(self, relative_path, content):
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def _digest(self, relative_path):
        return hashlib.sha256((self.root / relative_path).read_bytes()).hexdigest()

    def _hashes(self, candidates):
        hashes = {}
        for candidate in candidates:
            path = self.root / candidate
            hashes[candidate] = (
                hashlib.sha256(path.read_bytes()).hexdigest()
                if path.is_file() and not path.is_symlink()
                else "0" * 64
            )
        return hashes

    def _plan(self, candidates, protected_paths=(), expected_sha256=None):
        return plan_quarantine_dry_run(
            candidates,
            protected_paths,
            repository_root=self.root,
            expected_sha256=(
                self._hashes(candidates) if expected_sha256 is None else expected_sha256
            ),
        )

    def test_dry_run_is_deterministic_and_state_preserving(self):
        self._write("var/archive/old.json", b"archive-old")
        self._write("var/outbox/old.json", b"outbox-old")
        protected_path = self._write("var/inbox/live.json", b"must-stay")
        candidates = ["var/archive/old.json", "var/outbox/old.json"]
        before = {
            path: ((self.root / path).read_bytes(), (self.root / path).stat().st_mtime_ns)
            for path in (*candidates, "var/inbox/live.json")
        }
        first = self._plan(candidates, ["var/inbox/live.json"])
        second = self._plan(list(reversed(candidates)), ["var/inbox/live.json"])
        self.assertEqual(first, second)
        self.assertEqual(first.candidates, ("var/archive/old.json", "var/outbox/old.json"))
        self.assertEqual(first.candidate_sha256, tuple(sorted(self._hashes(candidates).items())))
        self.assertEqual(len(first.rollback_manifest_sha256), 64)
        self.assertTrue(protected_path.exists())
        after = {
            path: ((self.root / path).read_bytes(), (self.root / path).stat().st_mtime_ns)
            for path in (*candidates, "var/inbox/live.json")
        }
        self.assertEqual(before, after)

    def test_dry_run_rejects_repository_root_outside_and_noncanonical_paths(self):
        outside_file = self.outside_root / "outside.json"
        outside_file.write_bytes(b"outside")
        for candidate in (
            "",
            ".",
            str(self.root),
            str(outside_file),
            "../outside.json",
            "var/../outside.json",
            "./var/archive/old.json",
            "var//archive/old.json",
            "var/archive/",
            "var\\archive\\old.json",
            "C:/outside.json",
        ):
            with self.subTest(candidate=candidate), self.assertRaises(RetentionPlanError):
                self._plan([candidate], expected_sha256={candidate: "0" * 64})

    def test_dry_run_rejects_direct_ancestor_and_descendant_protected_paths(self):
        self._write("var/protected/live.json", b"protected")
        self._write("var/protected/child.json", b"child")
        with self.assertRaises(RetentionPlanError):
            self._plan(["var/protected/live.json"], ["var/protected/live.json"])
        with self.assertRaises(RetentionPlanError):
            self._plan(
                ["var/protected"],
                ["var/protected/live.json"],
                expected_sha256={"var/protected": "0" * 64},
            )
        with self.assertRaises(RetentionPlanError):
            self._plan(["var/protected/child.json"], ["var/protected"])

    def test_dry_run_rejects_symlink_escape(self):
        outside_file = self.outside_root / "outside.json"
        outside_file.write_bytes(b"outside")
        escape = self.root / "var" / "escape"
        escape.parent.mkdir(parents=True, exist_ok=True)
        escape.symlink_to(self.outside_root, target_is_directory=True)
        with self.assertRaises(RetentionPlanError):
            self._plan(
                ["var/escape/outside.json"],
                expected_sha256={
                    "var/escape/outside.json": hashlib.sha256(outside_file.read_bytes()).hexdigest()
                },
            )
        final_link = self.root / "var" / "final-link.json"
        final_link.symlink_to(outside_file)
        with self.assertRaises(RetentionPlanError):
            self._plan(
                ["var/final-link.json"],
                expected_sha256={
                    "var/final-link.json": hashlib.sha256(outside_file.read_bytes()).hexdigest()
                },
            )

    def test_dry_run_rejects_git_metadata_and_nested_git_worktree(self):
        git_config = self.root / ".git" / "config"
        with self.assertRaises(RetentionPlanError):
            self._plan(
                [".git/config"],
                expected_sha256={
                    ".git/config": hashlib.sha256(git_config.read_bytes()).hexdigest()
                },
            )

        nested_root = self.root / "nested"
        subprocess.run(
            ["git", "init", "--quiet", str(nested_root)],
            check=True,
            capture_output=True,
        )
        nested_file = nested_root / "candidate.json"
        nested_file.write_bytes(b"nested")
        with self.assertRaises(RetentionPlanError):
            self._plan(
                ["nested/candidate.json"],
                expected_sha256={
                    "nested/candidate.json": hashlib.sha256(nested_file.read_bytes()).hexdigest()
                },
            )

    def test_dry_run_rejects_tracked_candidate_and_hash_mismatch(self):
        self._write("tracked.json", b"tracked")
        subprocess.run(
            ["git", "-C", str(self.root), "add", "--", "tracked.json"],
            check=True,
            capture_output=True,
        )
        with self.assertRaises(RetentionPlanError):
            self._plan(["tracked.json"])

        self._write("var/archive/mutable.json", b"bound-content")
        mutable_path = self.root / "var/archive/mutable.json"
        before = (mutable_path.read_bytes(), mutable_path.stat().st_mtime_ns)
        with self.assertRaises(RetentionPlanError):
            self._plan(
                ["var/archive/mutable.json"],
                expected_sha256={"var/archive/mutable.json": "f" * 64},
            )
        after = (mutable_path.read_bytes(), mutable_path.stat().st_mtime_ns)
        self.assertEqual(before, after)

    def test_dry_run_rejects_candidate_changed_during_hash_verification(self):
        self._write("var/archive/racing.json", b"original")
        candidate_path = self.root / "var/archive/racing.json"
        original_stat = candidate_path.stat()
        original_read = retention.os.read
        changed = False

        def replace_after_first_read(descriptor, size):
            nonlocal changed
            block = original_read(descriptor, size)
            if block and not changed:
                changed = True
                candidate_path.write_bytes(b"replaced")
                retention.os.utime(
                    candidate_path,
                    ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
                )
            return block

        with mock.patch.object(retention.os, "read", side_effect=replace_after_first_read):
            with self.assertRaises(RetentionPlanError):
                self._plan(
                    ["var/archive/racing.json"],
                    expected_sha256={
                        "var/archive/racing.json": hashlib.sha256(b"original").hexdigest()
                    },
                )
        self.assertTrue(changed)
        self.assertEqual(candidate_path.read_bytes(), b"replaced")

    def test_dry_run_requires_exact_hash_evidence(self):
        self._write("var/archive/old.json", b"archive-old")
        with self.assertRaises(RetentionPlanError):
            self._plan(["var/archive/old.json"], expected_sha256={})
        with self.assertRaises(RetentionPlanError):
            self._plan(
                ["var/archive/old.json"],
                expected_sha256={
                    "var/archive/old.json": self._digest("var/archive/old.json"),
                    "var/archive/extra.json": "0" * 64,
                },
            )


if __name__ == "__main__":
    unittest.main()
