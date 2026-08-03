import argparse
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from trading_os_bridge import cli


MIGRATIONS = Path(__file__).parents[1] / "migrations"


def message(message_id=None, body="body"):
    return {
        "schema_version": 1, "id": message_id or str(uuid.uuid4()),
        "created_at": "2026-08-03T12:00:00Z", "sender": "cloud-planner",
        "recipient": "codex-dev", "type": "task", "subject": "Test", "body": body,
        "correlation_id": None, "artifacts": [], "metadata": {},
    }


class CliIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.inbox = self.root / "inbox"
        self.archive = self.root / "archive"
        self.quarantine = self.root / "quarantine"
        self.outbox = self.root / "outbox"
        self.inbox.mkdir()
        self.patches = [
            patch.object(cli, "DEFAULT_DB", self.root / "bridge.db"),
            patch.object(cli, "MIGRATIONS", MIGRATIONS),
            patch.object(cli, "INBOX", self.inbox),
            patch.object(cli, "ARCHIVE", self.archive),
            patch.object(cli, "QUARANTINE", self.quarantine),
            patch.object(cli, "OUTBOX", self.outbox),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def _write(self, name, payload):
        path = self.inbox / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_relative_ingest_duplicate_conflict_and_quarantine(self):
        item = message()
        self._write("ok.json", item)
        old_cwd = Path.cwd()
        try:
            os.chdir(self.root)
            self.assertEqual(cli.command_ingest(argparse.Namespace(path="inbox")), 0)
        finally:
            os.chdir(old_cwd)
        self.assertTrue((self.archive / "ok.json").exists())
        self.assertTrue(cli.store().get_message(item["id"])["source_uri"].startswith("file://"))

        self._write("duplicate.json", item)
        self.assertEqual(cli.command_ingest(argparse.Namespace(path=str(self.inbox))), 0)
        self.assertTrue((self.archive / "duplicate.json").exists())

        self._write("conflict.json", dict(item, body="different"))
        self.assertEqual(cli.command_ingest(argparse.Namespace(path=str(self.inbox))), 1)
        self.assertTrue((self.quarantine / "conflict.json").exists())

        (self.inbox / "invalid.json").write_text("{broken", encoding="utf-8")
        self.assertEqual(cli.command_ingest(argparse.Namespace(path=str(self.inbox))), 1)
        self.assertTrue((self.quarantine / "invalid.json").exists())

    def test_ingest_rejects_outside_file_without_moving_it(self):
        outside = self.root / "outside.json"
        outside.write_text(json.dumps(message()), encoding="utf-8")
        self.assertEqual(cli.command_ingest(argparse.Namespace(path=str(outside))), 1)
        self.assertTrue(outside.exists())
        self.assertFalse(self.archive.exists())
        self.assertFalse(self.quarantine.exists())

    def test_ingest_rejects_parent_symlink_escape(self):
        outside = self.root / "outside"
        outside.mkdir()
        payload = outside / "message.json"
        payload.write_text(json.dumps(message()), encoding="utf-8")
        link = self.inbox / "escape"
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlink unavailable")
        self.assertEqual(cli.command_ingest(argparse.Namespace(path=str(link))), 1)
        self.assertTrue(payload.exists())
        self.assertTrue(link.is_symlink())


if __name__ == "__main__":
    unittest.main()
