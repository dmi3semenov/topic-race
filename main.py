"""CLI entrypoint: sync Telegram data into local cache."""
from __future__ import annotations

import argparse
import logging

from topic_race.pipeline import run_sync


def main() -> None:
    parser = argparse.ArgumentParser(description="Topic Race — sync Telegram group data")
    parser.add_argument("--days", type=int, default=14, help="History window in days (default: 14)")
    parser.add_argument("--all", action="store_true", help="Fetch full history instead of --days window")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    since_days = None if args.all else args.days
    group, n_topics, n_new = run_sync(since_days=since_days, progress=print)
    print(f"\nOK: {group.title} — {n_topics} topics, {n_new} new messages")


if __name__ == "__main__":
    main()
