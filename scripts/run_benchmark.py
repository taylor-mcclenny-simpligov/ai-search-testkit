"""Author: Taylor M
Run benchmark: query index using production-style pipeline outputs and score vs gold labels.
Stub: load labels, run queries, aggregate by parent_id, compute Top-1/Top-3/MRR.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run similarity benchmark")
    ap.add_argument("--config", required=True, help="Path to benchmark_config.json")
    ap.add_argument("--labels", required=True, help="Path to gold labels.json")
    ap.add_argument("--out", required=True, help="Path to write scores.json")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    # TODO: implement scoring against gold labels
    print(f"Stub: run benchmark using {args.config} vs labels {args.labels} -> {args.out}")


if __name__ == "__main__":
    main()
