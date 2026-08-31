# Product Direction

## Purpose

Build a self-hosted personal daily assistant for one user. The product has two equally important responsibilities: provide sustained conversational companionship and emotional value, and help the user manage everyday commitments without turning every conversation into a workflow.

The assistant should feel like a consistent person during conversation. That personality must not obscure the truth of system state, permissions, stored data, or failures.

## Product principles

1. **Companionship is a first-class responsibility.** The assistant listens and responds naturally before trying to turn casual conversation into tasks or plans.
2. **Persona is behaviour, not decorative wording.** It shapes chat content, conversational clarification, acknowledgement, failure, and refusal.
3. **Persona is chat-only.** Settings, logs, permissions, stored data, diagnostics, and operation history stay neutral and precise.
4. **Natural intent replaces blanket confirmation.** Clear requests for reversible internal actions execute directly. Ambiguous intent receives a natural clarification. Only high-risk or irreversible actions require explicit confirmation.
5. **Tools stay behind the conversation.** Chat reports outcomes naturally; technical execution details remain available through unobtrusive UI details, audit history, or undo controls.
6. **Local data belongs to the user.** Model providers are replaceable inference adapters rather than owners of personal data.

## User and deployment

- Each installation serves one user.
- The user deploys the application themselves.
- Persona, memories, conversations, life records, settings, and audit data are stored locally.
- Model providers are replaceable. The product must not make one provider part of its domain model.
- Multi-user, team, tenant, and social permission models are out of scope.

## Interaction surface

The primary interaction surface is the browser. Chat and management belong to one application: settings are reached from the conversation experience rather than through a separate administration product.

The conversation surface may be installable as a PWA. While open, it receives live messages from the backend; optional browser notification delivery can extend proactive chat beyond an active tab.

QQ, OneBot, and other platform-specific chat adapters are not part of the new product direction.

## Persona

The system has one persona, managed by the user. It includes the assistant's name, identity, character, speaking style, relationship framing, conversational boundaries, and proactive-chat style.

The model cannot silently rewrite the persona. Learning about the user changes Memory, not the assistant's identity. Multiple personas, character slots, autonomous persona evolution, relationship levels, and gamified affection state are out of scope.

## Memory

Memory is intentionally similar to a simple personal-assistant memory feature:

- Explicit requests such as “remember that I do not eat cilantro” are saved directly.
- Clear, stable preferences or facts may be remembered automatically.
- Temporary emotions, jokes, and unsupported model guesses are not saved as facts.
- Relevant memories are recalled in later conversations.
- The user can list, search, edit, and delete memories from Settings or ask naturally for a memory to be forgotten.
- Conversation history is separate. The first version uses current conversation context and saved memories, not long-term semantic search over every old chat.

Memory may hold context such as “the user has a report due Friday”, but it does not replace the structured Task or Reminder that manages the commitment.

## Daily-life management

The first version manages:

- Tasks
- Reminders
- Calendar events
- Notes
- A daily review derived from those records

Each kind of record remains structurally distinct. A Task tracks work and completion; a Reminder schedules a notification; a Calendar Event occupies time; a Note preserves free-form content. Daily Review aggregates current records rather than copying them.

When the user states a fact such as “I need to submit a report on Friday”, the assistant may remember the context but does not silently create a Reminder. When the user says “remind me Friday to submit the report”, that clear Action Intent creates the Reminder directly without a second mechanical confirmation.

## Proactive chat

The assistant may initiate short conversational messages for companionship and emotional value. A bounded backend scheduler decides when a proactive-chat evaluation is allowed, considering quiet hours, cooldown, daily limits, recent interaction, relevant memory, upcoming life records, and the configured Persona.

The model only decides whether to send a message and what to say. Proactive-chat evaluation has no write-tool permission and cannot create, modify, or delete Memories or Life Records. It must not become an unrestricted autonomous loop.

## Product structure

The new project is divided into three modules:

- **Agent Core** owns the model loop, conversation sessions, tool and Skill interfaces, permission and confirmation mechanics, and runtime events. It contains no personal-assistant or web-specific behaviour.
- **Personal Assistant** owns the single Persona, Memory, Tasks, Reminders, Calendar Events, Notes, Daily Review, and Proactive Chat. Its concrete capabilities use the interfaces exposed by Agent Core.
- **Web App** owns the browser conversation surface, integrated Settings, backend transport, notification delivery, and neutral management views.

The existing concrete tools and SKILL.md content from the reference project are not migrated. Tool and Skill interfaces remain available so the new application and future projects can supply their own capabilities.

## Extraction mandate

The new project is an extraction and refactoring of proven behavior from the reference project, not an unrelated rewrite. Use `chatbot/` as the primary implementation reference for:

- the Agent loop, execution budgets, tool calls, sessions, permissions, approvals, and event flow;
- generic tool and Skill extension interfaces;
- replaceable model-provider integration;
- generic backend management such as health and status, sessions, tools, Skills, approvals, events, logs, and diagnostics.

Extract or adapt those capabilities into clean modules at the repository root, with behavior-preserving tests where practical. The resulting runtime must be independently buildable and must not import from or package `chatbot/`.

Do not carry forward:

- QQ, OneBot, channel, gateway, group-chat, or group-learning behavior;
- QQ-specific proactive behavior, configuration, backend fields, endpoints, or UI;
- the reference project's bundled tools, plugins, or SKILL.md implementations;
- persona content or product behavior that belongs specifically to the QQ bot.

The backend remains part of the product. Refactor it into generic management capabilities presented through the browser application's Settings area rather than a separate administration frontend.

## Reference project

The `chatbot/` directory is a read-only reference clone. New work is created at the repository root. The reference directory is ignored by Git and must not be modified, moved, or uploaded with the new project.
