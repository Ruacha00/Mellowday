# Agent Core extension interfaces

Mellowday intentionally preserves the product-neutral Tool, Skill, and Provider
interfaces from Agent Core. The release ships the interfaces and Mellowday's own
Personal Assistant Tools; it does not ship reference Tools, Skill instruction
files, plugins, or MCP configuration.

## Tool

`mellowday.agent_core.Tool` registers an async callable with JSON input metadata,
permissions, side-effect and risk classifications, and optional direct-User
evidence requirements. `ToolOutcome` and `UndoMetadata` let a reversible Tool
publish a bounded undo operation. Tools are supplied to
`mellowday.web_app.create_app(tools=...)`; Agent Core validates arguments and
applies its permission and confirmation rules before calling the executor.

## Skill

`mellowday.agent_core.Skill` supplies named instructions through a lazy
`instruction_loader`. Agent Core exposes metadata without loading the
instructions, persists enablement through the configured local state file, and
loads an enabled Skill only when selected for a turn. Skills are supplied to
`create_app(skills=...)`. No bundled `SKILL.md` content is part of this release.

## Provider

`mellowday.agent_core.ModelProvider` is the replaceable inference boundary. An
implementation exposes a `name` and an async `complete(ProviderRequest)` method
that returns `ProviderReply`. The Web App can receive an implementation through
`create_app(provider=...)` for another project or tests.

The shipped Settings path stores OpenAI-compatible Provider configurations
locally and resolves the selected configuration for every turn. Transport is a
separate injectable `ProviderTransport`, allowing deterministic boundary tests
without live model access. Provider failures are normalized into safe codes and
never return credentials through diagnostics.

These are Python composition interfaces rather than runtime plugin discovery.
Future projects can depend on the public `mellowday.agent_core` facade and inject
their own implementations without importing the Web App or the reference tree.
