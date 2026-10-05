# OpenMakerProjects Cloud Automation

This repository is the durable control plane for the remaining OpenMakerProjects roadmap publication.

It contains:

- `roadmap-projects.json`: the authoritative 2,200-project roadmap.
- `state/publish-results-seed.csv`: the publication ledger captured when the local continuous publisher was stopped.
- `state/`: durable cloud-run ledgers and completion records.
- `AGENTS.md`: the cloud agent's execution contract.

## Daily target

At 04:00 Asia/Kolkata, process exactly 20 unfinished roadmap entries unless fewer remain or a systemic failure makes continuing unsafe. Every selected project receives a public repository, a validated implementation, one pull request, a generated project image, an accurate circuit or architecture diagram, a comprehensive README, CI, tests, and an MIT license.

## Existing progress

The seed ledger is append-only history. Determine each roadmap ID's state from its latest row and verify published rows against GitHub before counting them complete. Do not recreate or overwrite repositories that are already complete.

## Credentials

No credentials belong in this repository. GitHub, image-generation, and Gmail access must come from the cloud environment's connected apps or protected secrets.

## Completion

The workflow is complete only when every roadmap ID from 1 through 2200 has a verified public OpenMakerProjects repository on `main`. Each daily run must update durable state and send a self-addressed HTML Gmail report.
