"""Deterministic, offline-only research runtime with no execution integration."""
from __future__ import annotations
import hashlib, json
from pathlib import Path

class ResearchRuntimeError(ValueError): pass

def run_offline(fixture: Path, output: Path, requested_effect: str = "none") -> dict:
    if requested_effect != "none":
        raise ResearchRuntimeError("offline runtime side effects are forbidden")
    if not fixture.is_file() or output.parent != fixture.parent / "results":
        raise ResearchRuntimeError("fixture/output boundary is invalid")
    raw = fixture.read_bytes()
    data = json.loads(raw)
    values = data["values"]
    result = {"fixture_sha256": hashlib.sha256(raw).hexdigest(), "count": len(values), "sum": sum(values), "intent_count": 0, "order_count": 0, "risk_decision_count": 0, "network_access_count": 0, "credential_access_count": 0, "venue_access_count": 0}
    output.parent.mkdir(exist_ok=True)
    output.write_bytes(json.dumps(result, sort_keys=True, separators=(",", ":")).encode()+b"\n")
    return result
