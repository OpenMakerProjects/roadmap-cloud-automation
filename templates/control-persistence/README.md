# Control-state compare-and-swap persistence

This helper is restricted to OpenMakerProjects/roadmap-cloud-automation, main. It does not build projects, acquire a lease, send Gmail, contain credentials, or perform network calls. The CLI prints a validated operation plan by default. `--apply` deliberately refuses: there is no built-in authenticated connector. Python `execute(..., apply=True, protected_runtime=True)` is an adapter boundary tested only with offline mocks. Never treat those mock results as live GitHub persistence evidence.

## API choice and atomicity

GitHub REST update-reference accepts sha and force, but no expected-old SHA. An immediate read followed by PATCH is not a server-side compare-and-swap. Do not translate this plan into an unconditional REST update or claim If-Match support.

The emitted connector-equivalent GraphQL `createCommitOnBranch` uses `expectedHeadOid`. It atomically creates one commit containing every addition/replacement and appends it to the expected main head. No deletions, force, author or committer overrides are allowed. GitHub attributes the commit to the credential owner; the adapter must verify authenticated login shrutikbalwan. Required source documentation:
- https://docs.github.com/en/rest/git/refs#update-a-reference
- https://docs.github.com/en/graphql/reference/commits#createcommitonbranch

The included Git-data operation plan describes fresh ref/base commit/tree, UTF-8 blobs, base-tree preservation, one expected-head parent, conditional ref update and readback. A Git-data connector may implement it only if its ref primitive supplies a genuine server-side expected-old-SHA condition. Ordinary connected REST update_ref is insufficient. The GraphQL operation is the supported equivalent; it avoids orphan Git object creation before a rejected conditional update.

## Explicit inputs

`python tools/control_persistence.py --input /path/to/request.json` reads an envelope with operation and snapshot. No hidden clock, randomness, Git checkout, environment credentials or network access.

Operation exact fields:
- schemaVersion: 1; owner: OpenMakerProjects; repo: roadmap-cloud-automation; branch: main.
- expectedMainSHA: observed 40-character main commit; message: bounded safe single line.
- transition: state/context/request inputs for tools/batch_lifecycle.py.
- changes: every changed path, expectedBlobSHA (null means explicit absence), expectedDigest (canonical digest of old parsed JSON, including null for absence), expectedRevision (old revision, otherwise 0), content (UTF-8 JSON text).

Snapshot: owner/repo/branch/refSHA/treeSHA plus files mapping each needed path to sha/mode/content. The adapter must fetch main ref, base commit/tree, and every required input/target blob at that immutable commit, reject truncated trees and directory symlinks, and verify treeSHA belongs to that commit. A snapshot is an explicit observation, not proof obtained by the offline planner. Every file byte stream is checked against its Git blob SHA; only regular mode 100644 is allowed. Snapshot file paths include the complete historical roadmap/completion state, current planning/QA/preflight, historical run/report ledger, scheduler/setup and correctly parsed CSV. Required paths are listed in READ_PATHS. Authoritative v1 evidence must additionally be present in the observed tree.

The fixed legacy baseline is validated with validate_control_state; planning with validate_execution_manifest; each proposed transition with batch_lifecycle and its evidence/report tools. Complete evidence is validated again on evidence/recovery writes. Ledger and report-intent files must exactly match the validated transition. This version supports the current IDs1–20 baseline and corrected IDs21–40 planning bundle; updating that bundle requires updating the snapshot validator deliberately. It refuses an absent historical lease rather than invent historical completion evidence. Explicit absent target evidence/report files are supported.

Approved writes only:
- state/active-lease.json
- state/run-YYYYMMDD-batchNNN-NNN.json
- state/recovery-YYYYMMDD-idNNN.json (v1 records only; existing legacy history is immutable)
- state/report-intent-<reportReference>.json
- state/completion-evidence/idNNN.json

Every transition includes the lease and all related changed state files in ONE commit. Canonical state digest/revision must match the observed target and lifecycle request. Existing evidence/ledger records are immutable. Report intent may advance only from prepared to the exact reconciled sent receipt. Historical completion-verifications.json/CSV are read-only to this helper; no migration or history rewrite is implied. Non-authoritative proposal markers remain intact.

## Protected adapter and readback

No production adapter is installed or exercised here. A future adapter must:
1. Receive credentials only from a protected cloud runtime, outside operation/snapshot/source/commit JSON. Never print tokens, headers, signed URLs or raw transport exceptions. No credentials in GitHub files.
2. Bind the allowlisted repo/main and authenticated login; expose atomic_expected_head_supported only for the documented atomic mutation.
3. Read snapshots at immutable observed commit; re-read/revalidate immediately before the single mutation.
4. Execute precisely the emitted mutation. Ref changes cause rejection; never retry a mutation automatically or force-update. Do not accept caller-supplied author, deletion, endpoint or ref fields.
5. Return commitSHA/refSHA and actual parent list. Read main and every written blob again. Verify the sole parent is expectedMainSHA, main equals the resulting commit, regular file modes and exact bytes/hashes match.
6. On timeout, rejection or readback mismatch, STOP mutation. A write may have succeeded: reconcile read-only using ref/commit/transition requestId, state digest, blobs and report reference before proposing anything new. Never resend Gmail from this helper.

The protected_runtime argument is an orchestration assertion, not authentication by itself. The adapter owns real authentication and repository protection enforcement. Default CI has contents: read and no adapter or credentials, so cannot apply.

## Offline checks

`python -m unittest discover -s tests -v` includes actual planning/control files and temporary fixtures, mocked competing writers/stale refs/blob/digest/revision, invalid scope/path/content/credentials/symlinks, multi-file single mutation, permission/update failure without retry, readback failure, successful mocked CAS, dry-run and CLI apply refusal. These tests prove local invariants; they do not replace live main/tree verification.
