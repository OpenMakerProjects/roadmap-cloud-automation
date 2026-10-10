# Cloud GitHub connector capability readback

Observed 2026-10-10 in the authorized cloud conversation. Exact operation declarations, account/access readback, and preservation evidence are in state/github-connector-capability-audit-20261010.json. No lease, project or Gmail operation was executed.

## Guarded multi-file Git-data path

The exposed connector includes:
- mcp__codex_apps__github_create_blob: UTF-8 content to immutable blob.
- mcp__codex_apps__github_create_tree: tree_elements plus base_tree_sha to preserve unrelated content.
- mcp__codex_apps__github_create_commit: tree_sha, parent_sha, optional additional_parent_shas.
- mcp__codex_apps__github_update_ref: repository_full_name, branch_name, sha, optional expected_sha and force. Its declared contract is: move a branch ref, rejecting a mismatched expected_sha.

A future protected connector adapter may implement the existing control_persistence Git-data plan with these operations. It MUST supply expected_sha equal to the fresh observed main head, force=false, and a commit having exactly that expected SHA as its sole parent (additional_parent_shas=[]). Before the update, read and verify the constructed commit/tree and all validated blobs; refresh the main ref, abort mismatches. Only the final ref movement publishes all files in one commit; intermediate blob/tree/commit objects do not alter main. A concurrent append creates a sibling or descendant of the prior head, which cannot fast-forward to this single-parent commit. Never omit the precondition or use force=true. Read the main ref, commit parents and every target blob back. Do not retry uncertain mutation; reconcile read-only.

This is the exposed connector's guarded Git-data path, not a claim that bare GitHub REST PATCH accepts expected_sha. Raw REST lacks that argument. No generic GraphQL mutation/createCommitOnBranch operation is exposed here; github_fetch is GET-only. Existing control_persistence also emits the GraphQL expectedHeadOid equivalent for a runtime that has that capability.

The audit verifies published operation contracts and harmless authenticated account/repository reads. Connector backend implementation/race timing is not inspectable, and no live concurrency/write probe was authorized. Actual execution must still enforce the helper's complete state/schema/digest/path/auth/readback contract and the single-parent non-force safety property. A tested production adapter has not been installed by this audit. Mere operation availability, offline mocks or planning markers do not acquire a lease or authorize counting completions.

## Single-file preconditions

mcp__codex_apps__github_create_file uses the Contents API with no replacement SHA: its declared path must not already exist on the requested existing branch. An existing file is a conflict, not permission to overwrite.

mcp__codex_apps__github_update_file requires the current blob SHA (sha), uses the Contents API and returns commit_sha/content_sha. Supply explicit main; stale blob SHA must fail. Neither operation exposes expected main head SHA. They are file-level guards, not a multi-file transaction or branch-head CAS.

These operations safely save this read-only audit/documentation under their per-file preconditions; they must not approximate the mandatory whole-transition atomic lease path. A staged operational fallback was not introduced because the guarded non-force Git-data publication path is exposed. Any future fallback would require separate schema/reconciliation/negative tests and explicit policy authorization.

## Schedule and state

Existing schedule 6ac3fd99bfc88191b9cefd5ea5c04359 is unchanged and keeps its fail-closed requirement. No duplicate schedule, run-now, staged project evidence, report intent, receipt, or active-lease write occurred. Runtime authentication remains connector-managed as shrutikbalwan; no credentials are saved. The audit does not replace live project/main/check/Gmail verification.
