"""Generate A0's small, integer-only synthetic Parquet fixture deterministically."""

from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    fixture = pl.DataFrame(
        {
            "open_time": [1, 2, 3, 4, 5, 6, 7, 8],
            "open": [100, 102, 100, 110, 105, 100, 120, 120],
            "close": [102, 100, 100, 108, 110, 95, 120, 125],
        },
        schema={"open_time": pl.Int64, "open": pl.Int64, "close": pl.Int64},
    )
    fixture.write_parquet(arguments.output, compression="uncompressed", statistics=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
