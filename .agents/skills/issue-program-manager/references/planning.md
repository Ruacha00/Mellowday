# Planning gate

Build the plan from live repository and GitHub state on every run.

## Preconditions

1. Read `AGENTS.md`, `CONTEXT.md`, `docs/agents/issue-tracker.md`, `docs/agents/triage-labels.md`, `docs/product-direction.md`, and ADRs relevant to the open work.
2. Verify the Git remote, default branch, GitHub authentication, current branch, and working-tree state.
3. Fetch every open issue, not just the first page or one label:

   `gh issue list --state open --limit 200 --json number,title,body,labels,assignees,comments,milestone,updatedAt`

4. Fetch open pull requests and their linked issues so work already in flight is not duplicated.

If authentication, pagination, or repository identity is unresolved, the gate fails. Report the exact failed check.

## Dependency model

For every open issue, record:

- canonical triage label;
- explicit blockers from GitHub dependencies and the issue body's `Blocked by` section;
- parent and child relationships;
- an open pull request or active branch already claiming it;
- acceptance criteria and the likely code or artifact ownership area.

An issue is actionable only when it is labeled `ready-for-agent`, every blocker is closed, no pull request already owns it, and it is not a coordination parent with open children. Treat missing or contradictory dependency data as unresolved.

## Selection

Choose from the actionable set using this order of judgment:

1. architectural or build foundations that unlock the largest remaining dependency chain;
2. work on the longest path to the final acceptance gate;
3. work that establishes reusable contracts before pages that consume them;
4. an order that minimizes overlapping edits and merge churn;
5. the newest issue comments and acceptance clarifications.

Do not assign numerical scores or select by issue number alone. Record why the chosen issue comes before the other actionable candidates.

## Planning completion criterion

The gate is complete when the manager can show:

- total open issues and their canonical status;
- the dependency graph, including coordination parents;
- the ordered implementation path and any currently interchangeable candidates;
- the next issue with a written selection rationale;
- preflight status for GitHub authentication, default branch, open pull requests, and working-tree cleanliness.

For a run request, working-tree cleanliness is mandatory. Do not stash, discard, move, or absorb user changes to manufacture a clean tree.
