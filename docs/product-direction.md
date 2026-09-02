# Mellowday Product Direction

## Purpose

Build Mellowday (悠日), a self-hosted personal daily assistant for one user. The product has two equally important responsibilities: provide sustained conversational companionship and emotional value, and help the user manage everyday commitments without turning every conversation into a workflow.

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

The current delivery target is a personally built and used Windows 11 x64 application, produced locally as both a per-user installer and a portable bundle. Public distribution, code signing, automatic updates, release channels, telemetry, and uploaded crash reporting are not current product goals.

Provider API keys are encrypted by the application before local persistence. The application uses no master password and does not bind encryption to a Windows user or device; the required key material travels with portable data and backups. This prevents direct plaintext inspection of the database or backup, but it is not intended to resist an attacker who has the complete application and its data or who reverse-engineers the application.

## Interaction surface

The primary Windows interaction surface is the Desktop Application. It presents the same Conversation Surface and integrated Settings owned by the Web App rather than introducing a second frontend or a separate administration product.

The Desktop Application owns Windows process lifecycle, single-instance behavior, system tray presence, startup registration, desktop notifications, and recovery when its local backend exits unexpectedly. Closing its window hides it to the system tray so Reminder and Proactive Chat schedulers can continue; an explicit exit stops those services.

Browser mode remains supported for development, diagnostics, and self-hosted use. It serves the same Web App and backend capabilities and is not a separate product. UI and UX layout decisions for the desktop presentation are intentionally deferred to an external design supplied by the User.

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

The project is divided into four modules:

- **Agent Core** owns the model loop, conversation sessions, tool and Skill interfaces, permission and confirmation mechanics, and runtime events. It contains no personal-assistant or web-specific behaviour.
- **Personal Assistant** owns the single Persona, Memory, Tasks, Reminders, Calendar Events, Notes, Daily Review, and Proactive Chat. Its concrete capabilities use the interfaces exposed by Agent Core.
- **Web App** owns the shared Conversation Surface, integrated Settings, backend transport, live delivery, and neutral management views. It remains independently runnable in a browser.
- **Desktop Shell** owns the Electron and TypeScript Windows host, starts and monitors the packaged Python backend, presents the Web App, and integrates the application with Windows lifecycle, tray, startup, and notification facilities. It contains no assistant domain behaviour.

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
