# Cloud Agent Contract

## Scope

Continue the OpenMakerProjects roadmap until all 2,200 entries are verified complete. Work as GitHub user `shrutikbalwan` in the `OpenMakerProjects` organization. This repository is the durable source of roadmap and run state.

## Selection and state

1. Read `roadmap-projects.json` and all files under `state/`.
2. Treat a roadmap ID whose latest seed/result status is `published` as complete only after confirming the public repository and `main` branch still exist.
3. Select the first 20 unfinished IDs in ascending order. Use fewer only when fewer remain or a systemic safety/rate-limit failure requires stopping.
4. Append a run ledger with IST timestamps, attempted IDs, repository URLs, PR URLs, tests, merge state, errors, Gmail delivery result, verified total, and remaining total.
5. Never mark an item complete from intent, an open PR, or a repository shell. Verify the required tree on `main`.

## Per-project deliverables

Build a real, internally consistent educational prototype from its roadmap entry. Include source code or firmware, configuration, tests or validation, sample data where relevant, CI, documentation, `.gitignore`, and an MIT `LICENSE`. Never claim physical hardware testing unless it actually occurred.

Write a project-specific `README.md` covering: overview, objectives, features, architecture, platform, bill of materials with quantities, prerequisites, exact pin map, circuit/wiring, assembly, setup, flashing, configuration, usage, telemetry/data formats, expected output, test results from the run, troubleshooting, limitations, domain-specific safety, future work, contributing, and license.

Generate one original, technically plausible project illustration with the image-generation tool and save it as `docs/images/project-overview.png`. Embed it using a relative path and meaningful alt text. Keep it reasonably sized for Git.

Create the circuit separately as a precise, self-contained code-native SVG at `docs/circuit-diagram.svg`. Label controller pins, component pins, rails, voltage levels, grounds, and connections. It must agree exactly with firmware and README. Preserve its editable source. If no physical circuit applies, create a precise architecture/interconnection SVG and explain why.

## GitHub workflow

- Never overwrite, delete, rename, or force-push unrelated existing content.
- If a project repository is missing, create it PUBLIC under `OpenMakerProjects`, set `main` as default, and add a minimal safe initial commit.
- Work on a unique automation branch and open exactly one PR per selected project into `main`.
- If an existing repository is incomplete, branch from current `main` and add only missing roadmap work.
- Run appropriate syntax checks, validators, tests, representative builds, link checks, SVG checks, and secret scans.
- Merge only after validation succeeds. If admin merge or temporary protection adjustment is necessary, restore the original protection in a guaranteed cleanup path.
- Record the PR and resulting `main` commit. Leave blocked PRs open only with a clear diagnostic.
- Respect GitHub rate limits with bounded backoff. Never submit rapid repeated failures.

## Daily email

After each run, send one HTML Gmail message to `me` with no cc or bcc. Subject: `OpenMakerProjects daily build report - <YYYY-MM-DD IST>`. Include the 20-item table, repository and PR links, validation and merge status, blockers, totals complete/remaining, and the next starting ID. Send a failure report if no project could be processed. Record delivery so retries do not send duplicates.

## Finish condition

After all 2,200 projects are verified, perform a manifest-to-GitHub audit, send one final completion email, commit final state, and disable the recurring schedule if possible. Future invocations must exit without changes or duplicate email.

## Scheduled execution safeguards

Follow [docs/cloud-scheduled-execution.md](docs/cloud-scheduled-execution.md) for the existing cloud schedule and the exact selector, control/manifest validators, batch_lifecycle, control_persistence expectedHeadOid CAS, completion_evidence and daily_report contracts. Planning proposals and mocked transports are not live leases or completion evidence. If protected atomic CAS is unavailable, fail closed before project execution; never bypass it with sequential writes. Keep the existing schedule enabled unless all 2,200 projects are verified and final audit/report/state are complete.
