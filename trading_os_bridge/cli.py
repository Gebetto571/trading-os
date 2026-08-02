from __future__ import annotations

import argparse
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .store import Store


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / os.getenv("TRADING_OS_DB", "var/trading_os.db")
MIGRATIONS = ROOT / "migrations"
OUTBOX = ROOT / "var/outbox"
ARCHIVE = ROOT / "var/archive"
VALID_TYPES = ("task", "response", "decision", "status", "error")
VALID_STATUSES = ("queued", "received", "processing", "completed", "failed")


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def store() -> Store:
    instance = Store(DEFAULT_DB, MIGRATIONS)
    instance.migrate()
    return instance


def validate_message(message: dict) -> None:
    required = {
        "schema_version", "id", "created_at", "sender", "recipient", "type",
        "subject", "body", "correlation_id", "artifacts", "metadata",
    }
    missing = required - message.keys()
    if missing:
        raise ValueError(f"Eksik alanlar: {', '.join(sorted(missing))}")
    if message["schema_version"] != 1 or message["type"] not in VALID_TYPES:
        raise ValueError("Desteklenmeyen mesaj sürümü veya türü")
    uuid.UUID(message["id"])


def command_init(_: argparse.Namespace) -> int:
    for path in (ROOT / "var/inbox", OUTBOX, ARCHIVE):
        path.mkdir(parents=True, exist_ok=True)
    count = store().migrate()
    print(f"Hazır. Uygulanan yeni migration: {count}")
    return 0


def command_send(args: argparse.Namespace) -> int:
    message_id = str(uuid.uuid4())
    created_at = now_utc()
    message = {
        "schema_version": 1,
        "id": message_id,
        "created_at": created_at,
        "sender": os.getenv("TRADING_OS_ACTOR", "codex-local"),
        "recipient": args.to,
        "type": args.type,
        "subject": args.subject,
        "body": args.body,
        "correlation_id": args.correlation_id,
        "artifacts": [],
        "metadata": {},
    }
    validate_message(message)
    OUTBOX.mkdir(parents=True, exist_ok=True)
    stamp = created_at.replace("-", "").replace(":", "")
    destination = OUTBOX / f"{stamp}__{message_id[:8]}__{args.type}.json"
    destination.write_text(json.dumps(message, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    store().put_message(message, "outbound", "queued", destination.as_uri())
    print(destination)
    return 0


def command_ingest(args: argparse.Namespace) -> int:
    source = Path(args.path)
    paths = [source] if source.is_file() else sorted(source.glob("*.json"))
    accepted = duplicate = failed = 0
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    database = store()
    for path in paths:
        try:
            message = json.loads(path.read_text(encoding="utf-8"))
            validate_message(message)
            if database.put_message(message, "inbound", "received", path.as_uri()):
                accepted += 1
                shutil.move(str(path), ARCHIVE / path.name)
            else:
                duplicate += 1
        except (OSError, ValueError, json.JSONDecodeError) as error:
            failed += 1
            print(f"Hata: {path}: {error}")
    print(f"Alındı: {accepted}, tekrar: {duplicate}, hatalı: {failed}")
    return 1 if failed else 0


def command_list(args: argparse.Namespace) -> int:
    rows = store().list_messages(args.limit)
    for row in rows:
        print(f"{row['created_at']}  {row['status']:<10} {row['message_type']:<8} {row['sender']} -> {row['recipient']}  {row['subject']}  [{row['id'][:8]}]")
    return 0


def command_status(args: argparse.Namespace) -> int:
    if not store().update_status(args.id, args.status):
        print("Mesaj bulunamadı")
        return 1
    print(f"{args.id}: {args.status}")
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Trading OS ChatGPT-Codex iletişim köprüsü")
    commands = result.add_subparsers(dest="command", required=True)
    init_cmd = commands.add_parser("init", help="Yerel veritabanını ve çalışma klasörlerini hazırla")
    init_cmd.set_defaults(func=command_init)

    send_cmd = commands.add_parser("send", help="Yeni mesaj zarfı üret")
    send_cmd.add_argument("--to", required=True)
    send_cmd.add_argument("--type", choices=VALID_TYPES, default="task")
    send_cmd.add_argument("--subject", required=True)
    send_cmd.add_argument("--body", required=True)
    send_cmd.add_argument("--correlation-id")
    send_cmd.set_defaults(func=command_send)

    ingest_cmd = commands.add_parser("ingest", help="JSON mesajlarını yerel kayda al")
    ingest_cmd.add_argument("path")
    ingest_cmd.set_defaults(func=command_ingest)

    list_cmd = commands.add_parser("list", help="Son mesajları göster")
    list_cmd.add_argument("--limit", type=int, default=25)
    list_cmd.set_defaults(func=command_list)

    status_cmd = commands.add_parser("status", help="Mesaj durumunu güncelle")
    status_cmd.add_argument("id")
    status_cmd.add_argument("status", choices=VALID_STATUSES)
    status_cmd.set_defaults(func=command_status)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.func(args)

