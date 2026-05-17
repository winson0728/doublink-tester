#!/usr/bin/env python3
"""Prune Allure history JSON files to bound long-term disk growth.

Allure's TREND graph keeps an append-only history across runs.  Each entry in
the trend files corresponds to one historical run; once enabled, these files
grow without bound — the chart only renders the last ~20 anyway, but the JSON
backing it still accumulates indefinitely.

This script truncates the trend arrays (and per-test history arrays) to the
most recent ``keep_n`` entries.  Allure stores entries newest-first, so taking
the first slice preserves the latest runs.

Files affected (all under ``<allure-report>/history/``):
  - categories-trend.json   (top-level array)
  - duration-trend.json     (top-level array)
  - history-trend.json      (top-level array)
  - retry-trend.json        (top-level array)
  - history.json            (dict {test_id: {statistic, items: [...]}})
                             — each test's ``items`` list is truncated

Usage:
    python3 prune_allure_history.py <history_dir> [keep_n=90]

Exit codes:
    0  success (always — missing files / parse errors are warnings only,
       so this never breaks the daily cron run)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


TREND_FILES = (
    "categories-trend.json",
    "duration-trend.json",
    "history-trend.json",
    "retry-trend.json",
)


def _prune_trend_file(path: Path, keep_n: int) -> tuple[int, int] | None:
    """Truncate a top-level-array trend file. Returns (before, after) or None."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"  ! {path.name}: read failed — {exc}")
        return None
    if not isinstance(data, list):
        print(f"  ! {path.name}: expected list, got {type(data).__name__}")
        return None
    before = len(data)
    if before <= keep_n:
        return (before, before)  # no change needed
    pruned = data[:keep_n]
    path.write_text(json.dumps(pruned), encoding="utf-8")
    return (before, keep_n)


def _prune_history_json(path: Path, keep_n: int) -> int:
    """Truncate per-test items[] in history.json. Returns # of tests pruned."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"  ! {path.name}: read failed — {exc}")
        return 0
    if not isinstance(data, dict):
        print(f"  ! {path.name}: expected dict, got {type(data).__name__}")
        return 0
    n_pruned = 0
    for _test_id, entry in data.items():
        if not isinstance(entry, dict):
            continue
        items = entry.get("items")
        if isinstance(items, list) and len(items) > keep_n:
            entry["items"] = items[:keep_n]
            n_pruned += 1
    if n_pruned:
        path.write_text(json.dumps(data), encoding="utf-8")
    return n_pruned


def prune(history_dir: Path, keep_n: int) -> None:
    if not history_dir.is_dir():
        print(f"  → history dir not found: {history_dir} (nothing to prune)")
        return

    print(f"  → pruning {history_dir} to keep last {keep_n} runs ...")

    for name in TREND_FILES:
        f = history_dir / name
        if not f.is_file():
            continue
        result = _prune_trend_file(f, keep_n)
        if result is None:
            continue
        before, after = result
        if before == after:
            print(f"      {name:28s}  {before:4d} entries  (within limit)")
        else:
            print(f"      {name:28s}  {before:4d} → {after:4d} entries  (pruned)")

    hjson = history_dir / "history.json"
    if hjson.is_file():
        n = _prune_history_json(hjson, keep_n)
        if n:
            print(f"      history.json                  {n} test case(s) truncated")
        else:
            print(f"      history.json                  no truncation needed")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(f"Usage: {argv[0]} <history_dir> [keep_n=90]", file=sys.stderr)
        return 2
    history_dir = Path(argv[1])
    keep_n = int(argv[2]) if len(argv) > 2 else 90
    if keep_n < 1:
        print(f"keep_n must be >= 1, got {keep_n}", file=sys.stderr)
        return 2
    prune(history_dir, keep_n)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
