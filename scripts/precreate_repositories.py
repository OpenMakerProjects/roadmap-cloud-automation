#!/usr/bin/env python3
"""Pre-create unfinished roadmap repositories for cloud automation.

This is intentionally resumable: existing organization repositories are skipped,
and each successful creation is appended to a local JSONL audit log.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "roadmap-projects.json"
STATE_DIR = ROOT / "state"
LOG = STATE_DIR / "repository-precreation-results.jsonl"
ORG = "OpenMakerProjects"
COMPLETED_STATES = {"published", "complete", "completed", "merged", "verified"}
LOG_LOCK = threading.Lock()


def run_gh(*args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gh", *args],
        input=input_text,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def latest_statuses() -> dict[int, str]:
    latest: dict[int, str] = {}
    for path in sorted(STATE_DIR.glob("*.csv"), key=lambda item: item.stat().st_mtime):
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


def existing_repositories() -> set[str]:
    result = run_gh("repo", "list", ORG, "--limit", "5000", "--json", "name")
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Unable to list organization repositories")
    return {item["name"].lower() for item in json.loads(result.stdout)}


def append_log(project: dict, status: str, detail: str = "") -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "id": project["id"],
        "slug": project["slug"],
        "status": status,
        "detail": detail,
        "url": f"https://github.com/{ORG}/{project['slug']}",
    }
    with LOG_LOCK:
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def create_repository(project: dict, max_attempts: int = 30) -> tuple[bool, str]:
    description = f"OpenMakerProjects #{project['id']}: {project['title']}"
    payload = json.dumps(
        {
            "name": project["slug"],
            "description": description[:350],
            "private": False,
            "auto_init": True,
            "has_issues": True,
            "has_projects": False,
            "has_wiki": False,
        }
    )
    for attempt in range(1, max_attempts + 1):
        result = run_gh("api", "--method", "POST", f"orgs/{ORG}/repos", "--input", "-", input_text=payload)
        if result.returncode == 0:
            response = json.loads(result.stdout)
            return True, response.get("html_url", f"https://github.com/{ORG}/{project['slug']}")

        error = (result.stderr or result.stdout).strip()
        if "already exists" in error.lower() or "name already exists" in error.lower():
            return True, "already-exists"
        if "rate limit" in error.lower() or "secondary" in error.lower() or "http 403" in error.lower() or "http 429" in error.lower():
            delay = min(900, max(90, 30 * attempt))
            print(f"rate-limit pause={delay}s attempt={attempt} slug={project['slug']}", flush=True)
            time.sleep(delay)
            continue
        if attempt < 4:
            delay = 5 * attempt
            print(f"retry pause={delay}s attempt={attempt} slug={project['slug']} error={error[:240]}", flush=True)
            time.sleep(delay)
            continue
        return False, error[:1000]
    return False, "retry limit exhausted"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Create repositories; otherwise only report the plan")
    parser.add_argument("--limit", type=int, default=0, help="Maximum repositories to process; 0 means all")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay after successful creations")
    parser.add_argument("--workers", type=int, default=3, choices=range(1, 5), help="Parallel creation workers")
    args = parser.parse_args()

    projects = json.loads(MANIFEST.read_text(encoding="utf-8"))
    statuses = latest_statuses()
    unfinished = [item for item in projects if statuses.get(int(item["id"])) not in COMPLETED_STATES]
    existing = existing_repositories()
    missing = [item for item in unfinished if item["slug"].lower() not in existing]
    if args.limit > 0:
        missing = missing[: args.limit]

    print(
        f"roadmap={len(projects)} unfinished={len(unfinished)} existing_org_repos={len(existing)} "
        f"missing_to_create={len(missing)} execute={args.execute}",
        flush=True,
    )
    if not args.execute:
        for item in missing[:20]:
            print(f"plan id={item['id']} slug={item['slug']}")
        return 0

    def process(project: dict) -> tuple[dict, bool, str]:
        ok, detail = create_repository(project)
        if ok:
            append_log(project, "created", detail)
            time.sleep(max(0, args.delay))
        else:
            append_log(project, "failed", detail)
        return project, ok, detail

    created = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(process, project) for project in missing]
        for index, future in enumerate(as_completed(futures), start=1):
            project, ok, detail = future.result()
            if ok:
                created += 1
                print(f"progress={index}/{len(missing)} created={created} failed={failed} id={project['id']} slug={project['slug']}", flush=True)
            else:
                failed += 1
                print(f"progress={index}/{len(missing)} created={created} failed={failed} id={project['id']} error={detail}", flush=True)

    print(f"complete attempted={len(missing)} created={created} failed={failed}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
