# Issue tracker: GitHub

Issues and specs for this repository live in GitHub Issues. Use the `gh` CLI for all operations.

The repository is inferred from `git remote -v`. A GitHub remote must be configured before issue operations are run.

## Conventions

- Create: `gh issue create --title "..." --body "..."`
- Read: `gh issue view <number> --comments`
- List: `gh issue list --state open --json number,title,body,labels,comments`
- Comment: `gh issue comment <number> --body "..."`
- Add/remove labels: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- Close: `gh issue close <number> --comment "..."`

## Pull requests as a triage surface

PRs as a request surface: no.

## Skill conventions

- “Publish to the issue tracker” means creating a GitHub issue.
- “Fetch the relevant ticket” means reading the issue and its comments.
- Wayfinder maps use a parent issue with linked child issues.
- Blocking relationships use GitHub issue dependencies where available.
- Claim work by assigning the issue to the current GitHub user.
- Resolve work by commenting with the result and closing the issue.
