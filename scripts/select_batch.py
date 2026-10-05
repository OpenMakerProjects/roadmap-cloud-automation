#!/usr/bin/env python3
"""Select the next unfinished OpenMakerProjects roadmap batch."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "roadmap-projects.json"
STATE_DIR = ROOT / "state"


def latest_statuses() -> dict[int, str]:
    latest: dict[int, str] = {}
    candidates = sorted(STATE_DIR.glob("*.csv"), key=lambda path: path.stat().st_mtime)
    for path in candidates:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or "Id" not in reader.fieldnames or "Status" not in reader.fieldnames:
                continue
            for row in reader:
                try:
                    project_id = int(row.get("Id", ""))
                except ValueError:
                    continue
                latest[project_id] = (row.get("Status") or "").strip().lower()
    return latest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 20:
        raise SystemExit("--limit must be between 1 and 20")

    projects = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if len(projects) != 2200:
        raise SystemExit(f"Expected 2200 roadmap projects, found {len(projects)}")

    statuses = latest_statuses()
    completed_states = {"published", "complete", "completed", "merged", "verified"}
    remaining = [project for project in projects if statuses.get(int(project["id"])) not in completed_states]
    batch = remaining[: args.limit]
    result = {
        "roadmap_total": len(projects),
        "ledger_completed": len(projects) - len(remaining),
        "ledger_remaining": len(remaining),
        "batch_count": len(batch),
        "batch": batch,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
