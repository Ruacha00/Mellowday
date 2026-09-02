---
name: issue-program-manager
description: Orchestrate an open GitHub issue backlog from live inventory and dependency planning through one issue per pull request and merge. Use for managing an implementation program or its progress; do not use to implement one already-selected issue directly.
---

# Issue Program Manager

Own sequence and progress. Delegate product implementation; keep backlog decisions, integration, and landing in the manager thread.

## Operating contract

- Read the complete live set of open GitHub Issues and their comments before selecting work. Refresh it after every merge; never treat a saved issue snapshot as current state.
- Use only the five canonical triage labels documented in `docs/agents/triage-labels.md`. Implement only `ready-for-agent` issues whose blockers are closed.
- Treat a parent specification with open child issues as a coordination issue, not an implementation unit.
- Run one implementation worker at a time. Spawn only the project custom agent `issue_implementer`, without model or reasoning overrides. Its configuration pins `model_reasoning_effort` to `high`.
- Start every worker task by explicitly invoking `$implement` with exactly one issue number.
- Keep `chatbot/` read-only and preserve unrelated user changes.
- The manager owns assignment, branch integration, commits, pushes, pull requests, checks, merge, issue closure verification, and the refreshed progress report.

## Mode

A request to plan, inspect, or report progress is read-only. A request to run or continue the program authorizes the in-scope implementation loop and its normal GitHub issue, branch, pull-request, and merge operations, subject to host approvals and repository protection rules.

## Workflow

1. Read [references/planning.md](references/planning.md) and complete its planning gate. Do not dispatch a worker until the gate is satisfied.
2. For read-only requests, return the live plan and stop.
3. For run or continue requests, read [references/execution.md](references/execution.md) and follow the landing loop.

The program is complete only when no actionable `ready-for-agent` issue remains, all landed work is merged and verified, and any remaining open issue is identified with its exact label or dependency blocker.
