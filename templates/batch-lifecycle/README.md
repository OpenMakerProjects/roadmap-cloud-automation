# Batch lifecycle proposals

tools/batch_lifecycle.py is a pure explicit JSON state/context/request → proposal function. It uses no network, Git writes, randomness, environment credentials or wall clock. Every output is marked nonAuthoritativePlanningOutput=true. A proposed status=active is data, never a lease acquisition.

The caller supplies a current snapshot, authoritative roadmap, preserved historical completion records1–20, plans/manifest/preflight, schema-v1 authoritative evidence, durable report reconciliation records, and explicit IST times. Historical baseline records must carry their actual verified main-tree/result evidence; no count-only override is accepted. New IDs count only through the completion-evidence validator and aggregator.

Each request carries unique requestId, owner, expectedStateDigest, expectedContextDigest and expectedRevision. Digests are SHA256 of canonical JSON. Exact replay of an applied request returns the current state unchanged; reusing its ID with another payload/context fails. Stale writers fail. **A caller that persists a proposal must separately use GitHub blob/ref compare-and-swap against the same observed snapshot.** The utility does not persist or provide a distributed lock by itself.

Transitions:
- begin: only absent, completed or expired leases; reject a live unexpired owner. New selection equals the selector's first20 unfinished IDs and matches preflight/manifest. Expired interrupted takeovers retain the original selected batch and completed progress rather than adding replacement IDs.
- activate: only the first pending remaining project; exactly one activeProject.
- checkpoint: only that project; validated schema-v1 evidence moves it from remaining to completed. Failed/blocked IDs remain unfinished but terminal for this batch, with diagnostics.
- report-intent: only after every selected ID is terminal. The safe renderer computes a single stable reference, HTML hash, subject and me/profile/empty cc,bcc. Duplicate, sent or unresolved intent is rejected.
- reconcile-sent: explicit receipt must match intent/hash/recipient and carry SENT/message ID/time. Repeated matching reconciliation never creates a send.
- release: all IDs terminal, aggregation and report still coherent, and a reconciled sent receipt. Full success yields completed with empty remaining; failures yield an expired released snapshot retaining failed remaining IDs. No counts regress.
- Explicit zero_success_failure_report release may finalize project work with a validated zero-success failure report intent and deliveryPending=true. It does not claim email delivery, and a new begin remains blocked until that intent is reconciled. This exception never bypasses the failure-report obligation.

CLI: python tools/batch_lifecycle.py --input /path/to/input.json
Input has state, context, request. Output is a proposal only.

Dry-run generator (read-only file inputs, no writes):
python tools/propose_batch.py --root . --now-ist 2026-10-11T04:00:00+05:30 --owner dry-run-20261011-ids021-040

The saved state/batch-proposal-20261011-ids021-040.json is explicitly non-authoritative planning data. Never copy it directly over active-lease.json or execute it without fresh source reads and atomic state reconciliation. Existing completed lease and report evidence remain untouched.

Offline unit fixtures are synthetic. This utility does not replace live GitHub verification, real builds, Gmail delivery reconciliation or actual optimistic-concurrency persistence.
