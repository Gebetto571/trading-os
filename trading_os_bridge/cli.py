from __future__ import annotations

import argparse
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

from .store import IntegrityConflict, InvalidTransition, Store
from .validation import VALID_TYPES, load_registry_roles, parse_json_strict, sha256_bytes, validate_message


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / os.getenv("TRADING_OS_DB", "var/trading_os.db")
MIGRATIONS = ROOT / "migrations"
INBOX = ROOT / "var/inbox"
OUTBOX = ROOT / "var/outbox"
ARCHIVE = ROOT / "var/archive"
QUARANTINE = ROOT / "var/quarantine"
REGISTRY = ROOT / "docs/decisions/system/TOS-CHAT-REGISTRY__v1.0.md"
TERMINAL_STATUSES = ("completed", "failed")


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def store() -> Store:
    for path in (INBOX, OUTBOX, ARCHIVE, QUARANTINE):
        _private_dir(path)
    instance = Store(DEFAULT_DB, MIGRATIONS)
    instance.migrate()
    return instance


def _validate(message: object) -> dict:
    return validate_message(message, load_registry_roles(REGISTRY))


def _private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)


def _unique_destination(source: Path, destination_dir: Path) -> Path:
    _private_dir(destination_dir)
    destination = destination_dir / source.name
    if destination.exists():
        destination = destination_dir / f"{source.stem}__{uuid.uuid4().hex[:8]}{source.suffix}"
    return destination


def _move_unique(source: Path, destination_dir: Path) -> Path:
    destination = _unique_destination(source, destination_dir)
    was_symlink = source.is_symlink()
    os.replace(source, destination)
    if not was_symlink:
        os.chmod(destination, 0o600)
    return destination


def command_init(_: argparse.Namespace) -> int:
    for path in (INBOX, OUTBOX, ARCHIVE, QUARANTINE):
        _private_dir(path)
    instance = Store(DEFAULT_DB, MIGRATIONS)
    count = instance.migrate()
    print(f"Hazır. Uygulanan yeni migration: {count}")
    return 0


def command_send(args: argparse.Namespace) -> int:
    message_id = str(uuid.uuid4())
    created_at = now_utc()
    message = {
        "schema_version": 1, "id": message_id, "created_at": created_at,
        "sender": os.getenv("TRADING_OS_ACTOR", "codex-dev"), "recipient": args.to,
        "type": args.type, "subject": args.subject, "body": args.body,
        "correlation_id": args.correlation_id, "artifacts": [], "metadata": {},
    }
    _validate(message)
    _private_dir(OUTBOX)
    stamp = created_at.replace("-", "").replace(":", "")
    destination = OUTBOX / f"{stamp}__{message_id[:8]}__{args.type}.json"
    raw = (json.dumps(message, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    staging = destination.with_name("." + destination.name + ".tmp")
    staging.write_bytes(raw)
    os.chmod(staging, 0o600)
    os.replace(staging, destination)
    store().put_message(message, "outbound", "queued", destination.resolve().as_uri(), raw)
    print(destination)
    return 0


def command_ingest(args: argparse.Namespace) -> int:
    configured_inbox = INBOX.expanduser().absolute()
    requested = Path(args.path).expanduser().absolute()
    try:
        if configured_inbox.is_symlink():
            raise ValueError("Yapılandırılmış gelen kutusu sembolik bağ olamaz")
        inbox_root = configured_inbox.resolve(strict=True)
        source = requested.resolve(strict=True)
        source.relative_to(inbox_root)
        current = requested
        while current.resolve(strict=True) != inbox_root:
            if current.is_symlink():
                raise ValueError(f"Gelen kutusunda sembolik bağ reddedildi: {current}")
            parent = current.parent
            if parent == current:
                raise ValueError("Gelen kutusu köküne ulaşılamadı")
            current = parent
    except (OSError, ValueError) as error:
        print(f"Hata: yalnız gerçek gelen kutusu altı kabul edilir: {requested}: {error}")
        return 1
    paths = [source] if source.is_file() else sorted(source.glob("*.json"))
    accepted = duplicate = failed = conflicts = 0
    database = store()
    database.reconcile_pending_ingests()
    for path in paths:
        raw = b""
        message = None
        inserted = False
        original_uri = path.resolve().as_uri()
        try:
            if path.is_symlink() or not path.is_file():
                raise ValueError("Sembolik bağ veya dosya olmayan girdi reddedildi")
            raw = path.read_bytes()
            message = _validate(parse_json_strict(raw))
            archive = _unique_destination(path, ARCHIVE)
            inserted = database.put_message(
                message, "inbound", "queued", archive.resolve().as_uri(), raw
            )
            existing = database.get_message(message["id"])
            if not inserted and existing["status"] != "queued":
                duplicate += 1
                _move_unique(path, ARCHIVE)
                continue
            parsed_target = urlparse(existing["source_uri"])
            if parsed_target.scheme != "file":
                raise ValueError("Bekleyen arşiv hedefi yerel file URI olmalı")
            target = Path(unquote(parsed_target.path))
            archive_root = ARCHIVE.resolve(strict=True)
            target.resolve(strict=False).relative_to(archive_root)
            try:
                _private_dir(target.parent)
                os.replace(path, target)
                os.chmod(target, 0o600)
            except OSError as error:
                if inserted:
                    database.cancel_inbound_reservation(message["id"])
                failed += 1
                print(f"Arşivleme hatası: {path}: {error}")
                continue
            if not database.activate_inbound(message["id"], target.resolve().as_uri()):
                failed += 1
                print(f"Etkinleştirme ertelendi: {message['id']}")
                continue
            accepted += 1
        except IntegrityConflict as error:
            conflicts += 1
            destination = _move_unique(path, QUARANTINE)
            database.record_quarantine(
                "integrity_conflict", original_uri, destination.resolve().as_uri(), str(error),
                message["id"] if isinstance(message, dict) else None,
                sha256_bytes(raw) if raw else None,
            )
            print(f"Bütünlük çatışması: {destination}: {error}")
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
            failed += 1
            if inserted and isinstance(message, dict):
                database.cancel_inbound_reservation(message["id"])
            try:
                destination = _move_unique(path, QUARANTINE)
            except OSError:
                destination = path
            database.record_quarantine(
                "invalid", original_uri,
                destination.absolute().as_uri() if destination != path or destination.exists() else None,
                str(error), message["id"] if isinstance(message, dict) else None,
                sha256_bytes(raw) if raw else None,
            )
            print(f"Karantina: {destination}: {error}")
        except sqlite3.Error as error:
            failed += 1
            print(f"Veritabanı hatası, kaynak korundu: {path}: {error}")
    print(f"Alındı: {accepted}, tekrar: {duplicate}, çatışma: {conflicts}, karantina: {failed}")
    return 1 if failed or conflicts else 0


def command_list(args: argparse.Namespace) -> int:
    for row in store().list_messages(args.limit):
        print(f"{row['created_at']}  {row['status']:<10} {row['message_type']:<8} {row['sender']} -> {row['recipient']}  {row['subject']}  [{row['id'][:8]}]")
    return 0


def command_status(args: argparse.Namespace) -> int:
    try:
        found = store().update_status(args.id, args.status, args.error, args.worker)
    except InvalidTransition as error:
        print(error)
        return 1
    if not found:
        print("Mesaj bulunamadı")
        return 1
    print(f"{args.id}: {args.status}")
    return 0


def command_check(args: argparse.Namespace) -> int:
    row = store().get_message(args.id)
    if row is None:
        print(json.dumps({"known": False, "id": args.id}))
        return 1
    print(json.dumps({"known": True, **dict(row)}, ensure_ascii=False))
    return 0


def command_claim(args: argparse.Namespace) -> int:
    row = store().claim_message(args.worker, args.lease_seconds)
    if row is None:
        print(json.dumps({"claimed": False}))
        return 1
    print(json.dumps({"claimed": True, **dict(row)}, ensure_ascii=False))
    return 0


def command_recover(args: argparse.Namespace) -> int:
    database = store()
    if args.id:
        try:
            found = database.recover_message(args.id, args.reason)
        except InvalidTransition as error:
            print(error)
            return 1
        if not found:
            print("Mesaj bulunamadı")
            return 1
        print(f"Kurtarılan mesaj: {args.id}")
        return 0
    count = database.recover_expired(args.reason)
    print(f"Kurtarılan: {count}")
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Trading OS ChatGPT-Codex iletişim köprüsü")
    commands = result.add_subparsers(dest="command", required=True)
    init_cmd = commands.add_parser("init")
    init_cmd.set_defaults(func=command_init)
    send_cmd = commands.add_parser("send")
    send_cmd.add_argument("--to", required=True)
    send_cmd.add_argument("--type", choices=sorted(VALID_TYPES), default="task")
    send_cmd.add_argument("--subject", required=True)
    send_cmd.add_argument("--body", required=True)
    send_cmd.add_argument("--correlation-id")
    send_cmd.set_defaults(func=command_send)
    ingest_cmd = commands.add_parser("ingest")
    ingest_cmd.add_argument("path")
    ingest_cmd.set_defaults(func=command_ingest)
    list_cmd = commands.add_parser("list")
    list_cmd.add_argument("--limit", type=int, default=25)
    list_cmd.set_defaults(func=command_list)
    status_cmd = commands.add_parser("status")
    status_cmd.add_argument("id")
    status_cmd.add_argument("status", choices=TERMINAL_STATUSES)
    status_cmd.add_argument("--error")
    status_cmd.add_argument("--worker")
    status_cmd.set_defaults(func=command_status)
    check_cmd = commands.add_parser("check")
    check_cmd.add_argument("id")
    check_cmd.set_defaults(func=command_check)
    claim_cmd = commands.add_parser("claim")
    claim_cmd.add_argument("--worker", required=True)
    claim_cmd.add_argument("--lease-seconds", type=int, default=300)
    claim_cmd.set_defaults(func=command_claim)
    recover_cmd = commands.add_parser("recover")
    recover_cmd.add_argument("--id")
    recover_cmd.add_argument("--reason", default="lease expired")
    recover_cmd.set_defaults(func=command_recover)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.func(args)
