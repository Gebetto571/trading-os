"""Static boundary tests: A0 has no execution, trading, or network dependency."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


ENGINE_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ENGINE_ROOT / "research_engine"

_ALLOWED_IMPORT_ROOTS = {
    "__future__",
    "argparse",
    "dataclasses",
    "hashlib",
    "json",
    "os",
    "pathlib",
    "platform",
    "polars",
    "re",
    "resource",
    "sqlite3",
    "stat",
    "tempfile",
    "time",
    "typing",
}
_FORBIDDEN_IMPORT_ROOTS = {
    "aiohttp",
    "alpaca",
    "boto3",
    "ccxt",
    "google",
    "http",
    "ib_insync",
    "requests",
    "socket",
    "subprocess",
    "trading_os_bridge",
    "urllib",
    "websocket",
}
_FORBIDDEN_SOURCE_TERMS = (
    "execution_core",
    "execution-core",
    "credential",
    "paper_trading",
    "live_trading",
)


class IsolationBoundaryTests(unittest.TestCase):
    def test_package_imports_are_local_stdlib_or_polars_only(self) -> None:
        import_roots: set[str] = set()
        for source_path in PACKAGE_ROOT.rglob("*.py"):
            tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    import_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    import_roots.add(node.module.split(".", 1)[0])
        self.assertFalse(import_roots.intersection(_FORBIDDEN_IMPORT_ROOTS))
        self.assertTrue(import_roots.issubset(_ALLOWED_IMPORT_ROOTS), sorted(import_roots))

    def test_package_has_no_prohibited_runtime_capability_terms(self) -> None:
        combined_source = "\n".join(
            path.read_text(encoding="utf-8").lower() for path in PACKAGE_ROOT.rglob("*.py")
        )
        for forbidden in _FORBIDDEN_SOURCE_TERMS:
            self.assertNotIn(forbidden, combined_source)

    def test_canonical_input_column_name_does_not_grant_a_venue_capability(self) -> None:
        snapshot_source = (PACKAGE_ROOT / "snapshot.py").read_text(encoding="utf-8").lower()
        self.assertIn('"venue"', snapshot_source)
        for forbidden_capability in (
            "venue_client",
            "venueclient",
            "connect_venue",
            "broker_client",
            "paper_trading",
            "live_trading",
        ):
            self.assertNotIn(forbidden_capability, snapshot_source)

    def test_runtime_outputs_are_ignored_and_fixture_is_tracked_input(self) -> None:
        ignore_file = (ENGINE_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("runtime/", ignore_file)
        self.assertIn("*.sqlite3", ignore_file)
        self.assertTrue((ENGINE_ROOT / "fixtures" / "candles_v1.parquet").is_file())
