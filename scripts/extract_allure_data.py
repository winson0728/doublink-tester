#!/usr/bin/env python3
"""Extract measurement data from allure-results JSON attachments."""
import json
import os
import glob
import sys

results_dir = sys.argv[1] if len(sys.argv) > 1 else "allure-results"

# Find all test result files
result_files = sorted(glob.glob(f"{results_dir}/*-result.json"))

for rf in result_files:
    try:
        data = json.load(open(rf))
    except Exception:
        continue

    test_name = data.get("name", "unknown")
    status = data.get("status", "unknown")
    full_name = data.get("fullName", "")

    # Only show mode_switching and link_weight tests
    if "mode_switching" not in full_name and "link_weight" not in full_name:
        continue

    # Find attachments with measurement data
    attachments = data.get("attachments", [])
    # Also check test body steps
    for step in data.get("steps", []):
        attachments.extend(step.get("attachments", []))

    print(f"\n{'='*80}")
    print(f"TEST: {test_name}")
    print(f"STATUS: {status}")
    print(f"FULL: {full_name}")

    for att in attachments:
        att_name = att.get("name", "")
        att_source = att.get("source", "")
        att_path = os.path.join(results_dir, att_source)
        if os.path.exists(att_path):
            try:
                content = open(att_path).read()
                # Try to parse as JSON and pretty print
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

print()
