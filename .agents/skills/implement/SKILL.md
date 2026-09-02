---
name: implement
description: Implement exactly one assigned, ready GitHub Issue in the current branch and return a verified handoff for the parent manager. Use only when an issue number is supplied; backlog ordering, pull requests, merges, and issue closure belong to the program manager.
---

# Implement One Issue

Implement exactly the assigned issue. The parent manager owns sequencing and landing.

## Establish the contract

1. Require one issue number. Read it and all comments with `gh`, then read `AGENTS.md`, `CONTEXT.md`, the relevant ADRs, and the product or prototype documents named by the issue.
2. Confirm the issue is labeled `ready-for-agent`, its declared blockers are closed, and the current branch is dedicated to it. Return a blocker if any check fails.
3. Translate every acceptance criterion into observable evidence before editing.

## Change

1. Use GitNexus query and context to find the relevant execution flows.
2. Run upstream impact analysis before editing each existing function, class, method, API handler, or other named symbol. Surface `HIGH`, `CRITICAL`, and `UNKNOWN` risk according to `AGENTS.md` before proceeding.
3. Implement the smallest complete change that satisfies the issue. Add or update external-behavior tests required by the acceptance criteria.
4. Keep `chatbot/` read-only. Do not incorporate unrelated working-tree changes.

Do not select another issue, push, create or merge a pull request, close an issue, or spawn another implementation agent.

## Verify

Run the narrow tests first, then the broader repository checks required by the changed surface. Inspect the final diff and run GitNexus `detect_changes` with scope `all`; `partial: true` or `truncated: true` is unresolved.

## Handoff

Return exactly these sections to the parent manager:

- `Status`: `ready_for_pr` or `blocked`.
- `Issue`: number and title.
- `Acceptance`: one row per criterion with evidence or a blocker.
- `Changes`: scoped files and behavior.
- `Verification`: commands and outcomes.
- `GitNexus`: impact risks and final affected processes.
- `Landing notes`: migrations, generated artifacts, approvals, or follow-up the manager must handle.

Use `ready_for_pr` only when every criterion has evidence and all required verification passes.
