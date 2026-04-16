#!/usr/bin/env python3
"""Extract measurement data from allure-results JSON attachments."""
import json
import os
import glob
import sys

results_dir = sys.argv[1] if len(sys.argv) > 1 else "allure-results"

# Find all test result files
result_files = sorted(glob.glob(f"{results_dir}/*-result.json"))

passed = 0
failed = 0
total = 0

for rf in result_files:
    try:
        data = json.load(open(rf))
    except Exception:
        continue

    test_name = data.get("name", "unknown")
    status = data.get("status", "unknown")
    full_name = data.get("fullName", "")
    duration_ms = data.get("time", {}).get("duration", 0)

    total += 1
    if status == "passed":
        passed += 1
    elif status in ("failed", "broken"):
        failed += 1

    # Find attachments with measurement data
    attachments = data.get("attachments", [])
    # Also check test body steps
    for step in data.get("steps", []):
        attachments.extend(step.get("attachments", []))

    status_icon = {"passed": "PASS", "failed": "FAIL", "broken": "BROKE", "skipped": "SKIP"}.get(status, status.upper())
    print(f"\n{'='*80}")
    print(f"[{status_icon}] {test_name}  ({duration_ms/1000:.1f}s)")

    for att in attachments:
        att_name = att.get("name", "")
        att_source = att.get("source", "")
        att_path = os.path.join(results_dir, att_source)
        if os.path.exists(att_path):
            try:
                content = open(att_path).read()
                try:
                    jdata = json.loads(content)
                    print(f"\n  [{att_name}]")
                    for k, v in jdata.items():
                        if isinstance(v, float):
                            print(f"    {k}: {v:.4f}")
                        else:
                            print(f"    {k}: {v}")
                except json.JSONDecodeError:
                    print(f"\n  [{att_name}]: {content[:200]}")
            except Exception:
                pass

    # Show failure message if failed
    if status in ("failed", "broken"):
        status_details = data.get("statusDetails", {})
        msg = status_details.get("message", "")
        if msg:
            print(f"\n  FAILURE: {msg[:200]}")

print(f"\n{'='*80}")
print(f"SUMMARY: {passed} passed, {failed} failed, {total} total")
print(f"{'='*80}")
