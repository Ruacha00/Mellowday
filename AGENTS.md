## Project boundary

Treat `chatbot/` as a read-only reference clone. Create all new project work at the repository root; never modify, move, delete, import from, or commit the reference tree.

Before extraction or refactoring work, read `docs/product-direction.md` and the relevant ADRs. Extract or adapt the proven Agent Core and generic backend-management behavior, while excluding QQ/OneBot adapters and the reference project's bundled tool and Skill implementations.

## Agent skills

### Issue tracker

Issues and specs are tracked in GitHub Issues using the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the five canonical triage labels without overrides. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repository. Read the root `CONTEXT.md` and relevant ADRs under `docs/adr/`. See `docs/agents/domain.md`.
