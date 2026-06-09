"""One-off compaction of the news-alert latency trace file.

Collapses duplicate blocked rows (one per ticker+publish-time+reason, keeping the
real first-block latency) and drops events older than the retention window.
Delivered-alert rows are always kept. Safe to run on the live file — the rewrite
is atomic and uses the same lock as the appender.

Usage:
    python -m scripts.compact_latency_trace            # 30-day retention
    python -m scripts.compact_latency_trace --retention-days 14
"""

import argparse

from src.core.agentic.news_alert_latency_trace import TRACE_FILE, compact_latency_trace


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retention-days", type=int, default=30,
                        help="Drop events older than this many days (0 = keep all).")
    args = parser.parse_args()

    stats = compact_latency_trace(retention_days=args.retention_days)
    print(f"Compacted {TRACE_FILE}")
    print(f"  before : {stats['before']:,}")
    print(f"  after  : {stats['after']:,}")
    print(f"  removed: {stats['removed']:,}")


if __name__ == "__main__":
    main()
