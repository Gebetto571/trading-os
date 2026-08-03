from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONSTITUTION = ROOT / "docs/decisions/system/TOS-DEC-004__merkezi-dosya-yonetim-anayasasi__v1.0.md"
REGISTRY = ROOT / "docs/decisions/system/TOS-CHAT-REGISTRY__v1.0.md"


def index_rows() -> list[list[str]]:
    rows: list[list[str]] = []
    for line in CONSTITUTION.read_text(encoding="utf-8").splitlines():
        if re.match(r"^\| MD-\d{3} \|", line):
            rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows


class GovernanceTests(unittest.TestCase):
    def test_index_ids_documents_and_required_columns_are_unique(self) -> None:
        rows = index_rows()
        self.assertTrue(rows, "Merkezi Markdown fihristi boş")
        self.assertTrue(all(len(row) == 10 for row in rows), "Fihrist satırı 10 zorunlu sütunu taşımıyor")
        ids = [row[0] for row in rows]
        documents = [row[1] for row in rows]
        self.assertEqual(len(ids), len(set(ids)), "Tekrarlanan MD-NNN kimliği var")
        self.assertEqual(len(documents), len(set(documents)), "Tekrarlanan fihrist belge adı var")
        self.assertEqual(ids, sorted(ids), "Fihrist kimlikleri artan sırada değil")

    def test_index_lifecycle_availability_and_owner_are_valid(self) -> None:
        registry_text = REGISTRY.read_text(encoding="utf-8")
        roles = set(re.findall(r"^\| `([^`]+)` \|", registry_text, flags=re.MULTILINE))
        lifecycles = {"proposed", "active", "reference", "superseded", "archived", "generated"}
        availability = {"branch-only", "main", "external-sync", "external-legacy"}
        for row in index_rows():
            owner = row[3].split("/", 1)[0].strip()
            lifecycle, location = [part.strip() for part in row[6].split("/", 1)]
            self.assertIn(owner, roles, f"Bilinmeyen fihrist sahibi: {owner}")
            self.assertIn(lifecycle, lifecycles, f"Geçersiz yaşam döngüsü: {lifecycle}")
            self.assertIn(location, availability, f"Geçersiz erişim durumu: {location}")
            self.assertTrue(row[5], "creation_reason boş")
            self.assertTrue(row[7], "Git kanıtı boş")
            self.assertIn("/", row[8], "created_at / last_updated eksik")

    def test_every_tracked_managed_markdown_is_indexed(self) -> None:
        output = subprocess.check_output(
            ["git", "ls-files", "*.md"], cwd=ROOT, text=True, encoding="utf-8"
        )
        tracked = [Path(line) for line in output.splitlines() if line]
        indexed_names = {row[1].strip("`") for row in index_rows()}
        missing = sorted(
            str(path)
            for path in tracked
            if not str(path).startswith("sources/") and path.name not in indexed_names
        )
        self.assertEqual(missing, [], f"Fihristsiz yönetilen Markdown: {missing}")

    def test_single_writer_and_local_checkout_are_sealed(self) -> None:
        constitution = CONSTITUTION.read_text(encoding="utf-8")
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("/Users/scm/Projects/trading-os", constitution)
        self.assertIn("tek yazardır", constitution)
        self.assertIn("tek yazar", agents)
        self.assertNotIn("/Users/scm/Drive'ım/Trading OS/07_KOD/trading-os", constitution)
        self.assertNotIn("/Users/scm/Drive'ım/Trading OS/07_KOD/trading-os", agents)
        self.assertIn("Google Drive is not a project storage or synchronization layer", agents)

    def test_drive_sync_runtime_is_removed(self) -> None:
        self.assertFalse((ROOT / "config/drive-folders.json").exists())
        self.assertFalse((ROOT / "trading_os_bridge/drive.py").exists())
        self.assertFalse((ROOT / "bin/tos-git").exists())
        parser_source = (ROOT / "trading_os_bridge/cli.py").read_text(encoding="utf-8")
        self.assertNotIn("sync-pull", parser_source)
        self.assertNotIn("sync-push", parser_source)

    def test_historical_event_documents_are_not_active_policy(self) -> None:
        dec3 = (ROOT / "docs/decisions/system/TOS-DEC-003__sohbet-karar-ve-iletisim-kayit-sistemi__v1.0.md")
        xfer = (ROOT / "docs/communication-log/TOS-XFER-20260803-001__docs-manager__all-chats__policy.md")
        template = (ROOT / "docs/decisions/templates/TOS-TPL-002__sohbetler-arasi-aktarim-sablonu.md")
        self.assertIn("status: reference", dec3.read_text(encoding="utf-8"))
        self.assertIn("lifecycle: historical-reference", xfer.read_text(encoding="utf-8"))
        self.assertIn("template_status: deprecated", template.read_text(encoding="utf-8"))

    def test_secrets_and_runtime_files_are_not_tracked(self) -> None:
        tracked = subprocess.check_output(
            ["git", "ls-files"], cwd=ROOT, text=True, encoding="utf-8"
        ).splitlines()
        forbidden_paths = {
            ".env",
            "var/trading_os.db",
            "var/trading_os.db-wal",
            "var/trading_os.db-shm",
        }
        self.assertFalse(forbidden_paths.intersection(tracked))
        self.assertFalse(any(path.startswith(("target/", "data/")) for path in tracked))

        private_key_header = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
        assignment = re.compile(
            r"(?im)^(?:api[_-]?key|access[_-]?token|secret[_-]?key|private[_-]?key)\s*=\s*[^<\s][^\s]*$"
        )
        violations: list[str] = []
        for relative in tracked:
            path = ROOT / relative
            if not path.is_file() or path.stat().st_size > 1_000_000:
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if private_key_header.search(content) or assignment.search(content):
                violations.append(relative)
        self.assertEqual(violations, [], f"Takip edilen dosyada olası sır: {violations}")


if __name__ == "__main__":
    unittest.main()
