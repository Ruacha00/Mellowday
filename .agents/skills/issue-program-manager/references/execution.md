# Execution and landing loop

Run the following loop for the one issue selected by the planning gate.

## Claim and prepare

1. Synchronize the local default branch with `origin` using a fast-forward-only update.
2. Re-read the selected issue with comments and confirm its label and blockers are unchanged.
3. Assign the issue to the current GitHub user according to `docs/agents/issue-tracker.md`.
4. Create a dedicated branch named `issue/<number>-<short-slug>` from the updated default branch.

Stop if the branch already exists with unclear ownership, the base cannot fast-forward, or the issue changed enough to invalidate the plan.

## Dispatch and supervise

Spawn the project custom agent `issue_implementer` in a fresh agent thread. Do not provide a model or reasoning override. Its task must begin:

`Use $implement to implement GitHub Issue #<number>.`

Include the issue title, full body, comments, branch name, acceptance criteria, and any planning facts that are not discoverable from the repository. Wait for its structured handoff. Use follow-up turns in the same worker thread for implementation corrections; do not open a replacement context merely to retry.

## Verify

The manager independently checks:

- the diff is limited to the issue and necessary consequences;
- no path under `chatbot/` changed;
- every acceptance criterion has evidence;
- targeted and repository-required tests pass;
- GitNexus impact warnings were handled before edits and `detect_changes` completed without `partial` or `truncated` uncertainty;
- no unrelated user changes were staged.

Return the same worker thread for corrections when evidence is missing. A worker's success statement is not sufficient evidence by itself.

## Land

1. Stage only the verified issue files and create one clear commit.
2. Push the issue branch and open one pull request whose body summarizes behavior and tests and includes `Closes #<number>`.
3. Inspect the final pull-request diff and wait for required checks. Failed checks return to the same worker thread for repair.
4. Merge only after required checks pass and repository rules allow it. Prefer the repository's established merge method; otherwise use squash merge and delete the remote branch.
5. Verify the pull request is merged and the issue is closed. Return to the default branch and update it with a fast-forward-only pull.

Never force-push, bypass branch protection, or merge a red or indeterminate pull request. If protection requires a human decision, report the exact pending action.

## Refresh progress

After every merge, fetch the complete open-issue and open-pull-request inventories again and rerun the planning gate. Continue only with the newly selected issue.

When all children of a coordination parent are closed, compare the parent's acceptance criteria with merged evidence. Comment with the child/PR summary and close it only when the parent is genuinely satisfied; do not create a dummy implementation pull request for it.

The loop ends when the refreshed actionable set is empty or an external blocker prevents safe progress.
