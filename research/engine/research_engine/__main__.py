"""CLI entry point for the isolated A0 research process."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .errors import EngineError
from .runner import run_experiment


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local read-only A0 event study")
    parser.add_argument("--config", required=True, type=Path, help="strict local TOML configuration")
    arguments = parser.parse_args()
    try:
        outcome = run_experiment(arguments.config)
    except EngineError as error:
        print(json.dumps({"error": str(error), "status": "rejected"}, sort_keys=True))
        return 2
    print(json.dumps(outcome.to_public_dict(), separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
