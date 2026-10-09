#!/usr/bin/env python3
"""Return candidates; published ledger history is not verified completion."""
import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / 'state'
PUBLICATION_STATES = {'published', 'complete', 'completed', 'merged', 'verified'}

def latest_statuses(state_dir=STATE_DIR):
    latest = {}
    seed = state_dir / 'publish-results-seed.csv'
    # Seed chronology is its append-only row order. Execution failures/audits in
    # daily ledgers do not revoke an existing publication.
    candidates = ([seed] if seed.exists() else []) + sorted(
        p for p in state_dir.glob('*.csv') if p != seed)
    for path in candidates:
        with path.open(newline='', encoding='utf-8-sig') as handle:
            for row in csv.DictReader(handle):
                try: project_id = int(row.get('Id', ''))
                except (TypeError, ValueError): continue
                status = (row.get('Status') or '').strip().lower()
                if path == seed or status in PUBLICATION_STATES:
                    latest[project_id] = status
    return latest

def select(projects, verifications, limit=20):
    # Agents must still reconfirm public main trees. Audit blocked is not a
    # publication status change and verified records are never inferred from it.
    return [p for p in projects if verifications.get(str(p['id']), {}).get('status')
            not in {'verified_complete', 'merged_verified'}][:limit]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=20)
    args = parser.parse_args()
    if not 1 <= args.limit <= 20: raise SystemExit('--limit must be between 1 and 20')
    projects = json.loads((ROOT/'roadmap-projects.json').read_text())
    if len(projects) != 2200: raise SystemExit('Expected 2200 projects')
    publication = latest_statuses()
    verified_path = STATE_DIR/'completion-verifications.json'
    verified = json.loads(verified_path.read_text()) if verified_path.exists() else {}
    batch = select(projects, verified, args.limit)
    print(json.dumps({'roadmap_total':len(projects),
        'ledger_published_not_a_completion_count':sum(v in PUBLICATION_STATES for v in publication.values()),
        'requires_current_github_verification':True,
        'batch_count':len(batch), 'batch':batch}, indent=2))

if __name__ == '__main__': main()
