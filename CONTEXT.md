# Mellowday

Mellowday (悠日) is a self-hosted assistant for one user. It combines long-term conversational companionship with practical daily-life management while keeping its persona, memories, and life records conceptually distinct.

## People and identity

**User**:
The single person served by one installation of the assistant.
_Avoid_: Account, tenant, member

**Assistant**:
The persistent personal companion that chats with the User and helps manage daily life.
_Avoid_: QQ bot, chatbot, agent instance

**Persona**:
The single User-managed identity, character, speaking style, relationship framing, and conversational boundaries of the Assistant. It affects Chat Content only.
_Avoid_: Persona profile, character slot, multiple personas

## Conversation

**Chat Content**:
Natural-language messages exchanged between the User and Assistant. Persona applies here, including conversational clarifications, failures, and refusals.
_Avoid_: Management copy, audit output

**Proactive Chat**:
A bounded, read-only message initiated by the Assistant for companionship, emotional support, or a timely check-in. It cannot perform another action as part of deciding or sending the message.
_Avoid_: Autonomous action, background task execution

**Natural Clarification**:
A question asked in the Persona's voice when the User's intent is too ambiguous to act on safely.
_Avoid_: Confirmation dialog, tool confirmation

## Knowledge about the User

**Memory**:
A durable User preference, fact, or important matter saved for use in relevant future conversations. Memory is not a task, reminder, calendar event, note, or raw chat transcript.
_Avoid_: Chat history, life record, knowledge dump

**Conversation History**:
The messages retained for continuity within a conversation. It may be stored locally for review but is not automatically treated as Memory.
_Avoid_: Memory

## Daily life

**Task**:
An action the User intends to complete, with a completion state and optional deadline.
_Avoid_: Reminder, memory

**Reminder**:
A scheduled notification to the User, optionally linked to a Task.
_Avoid_: Task, proactive chat

**Calendar Event**:
A planned occurrence with a start time and optional end time.
_Avoid_: Reminder, task

**Note**:
Free-form content the User deliberately saves for later reference.
_Avoid_: Memory, conversation history

**Daily Review**:
A derived view that helps the User inspect and plan the day from current life records. It is not an independent copy of those records.
_Avoid_: Daily record, daily memory

## Actions

**Life Record**:
The collective term for Tasks, Reminders, Calendar Events, and Notes. Each kind remains the source of truth for its own data.
_Avoid_: Memory

**Action Intent**:
A sufficiently clear request from the User to perform a reversible internal action. Action Intent authorizes that action without a second mechanical confirmation.
_Avoid_: Implicit guess, blanket confirmation

**Explicit Confirmation**:
An additional decision requested from the User only for high-risk or irreversible actions.
_Avoid_: Routine acknowledgement

## Product surface

**Conversation Surface**:
The product area where the User chats with the Assistant and receives proactive messages. It can be presented by the Desktop Application or in a browser.
_Avoid_: Chat client, separate frontend

**Today**:
The neutral product area that presents the Daily Review as the User's current-day overview.
_Avoid_: Daily record, settings page

**Life**:
The neutral product area for viewing and managing Tasks, Reminders, Calendar Events, and Notes. It does not own Memory.
_Avoid_: Settings, memory manager

**Memory Management**:
The neutral product area for reviewing and managing Memory independently of Life Records and Settings.
_Avoid_: Life, settings page, conversation history

**Desktop Application**:
The installed or portable Windows product entry that presents Mellowday's product areas and keeps local assistant services available while its window is hidden.
_Avoid_: Desktop wrapper, native rewrite

**Settings**:
The neutral product area for appearance, Persona and Proactive Chat configuration, providers, capabilities, Conversation History, audit information, and diagnostics. It does not own Memory or Life Records, and Persona does not apply to its copy.
_Avoid_: Separate admin backend, character dialogue
