const form = document.querySelector("#conversation-form");
const input = document.querySelector("#message-input");
const messages = document.querySelector("#messages");
const status = document.querySelector("#composer-status");
const submit = form.querySelector('button[type="submit"]');
const conversation = document.querySelector(".conversation");
const settingsPanel = document.querySelector("#settings-panel");
const settingsToggle = document.querySelector("#settings-toggle");
const settingsClose = document.querySelector("#settings-close");
const settingsStatus = document.querySelector("#settings-status");
const personaForm = document.querySelector("#persona-form");
const providerForm = document.querySelector("#provider-form");
const providerList = document.querySelector("#provider-list");
const cancelProviderEdit = document.querySelector("#cancel-provider-edit");
const toolList = document.querySelector("#tool-list");
const skillList = document.querySelector("#skill-list");
const toolCount = document.querySelector("#tool-count");
const skillCount = document.querySelector("#skill-count");
const confirmationList = document.querySelector("#confirmation-list");
const confirmationCount = document.querySelector("#confirmation-count");
const auditList = document.querySelector("#audit-list");
const auditCount = document.querySelector("#audit-count");
const conversationList = document.querySelector("#conversation-list");
const historyTitle = document.querySelector("#history-detail-title");
const historyMetadata = document.querySelector("#history-metadata");
const historyMessages = document.querySelector("#history-messages");
const resetHistory = document.querySelector("#reset-history");
const resetConfirmation = document.querySelector("#reset-confirmation");
const cancelReset = document.querySelector("#cancel-reset");
const confirmReset = document.querySelector("#confirm-reset");
const refreshHistory = document.querySelector("#refresh-history");
const refreshOperations = document.querySelector("#refresh-operations");
const backendStatus = document.querySelector("#backend-status");
const providerStatus = document.querySelector("#provider-status");
const sessionStatus = document.querySelector("#session-status");
const eventTypeFilter = document.querySelector("#event-type-filter");
const eventConversationFilter = document.querySelector("#event-conversation-filter");
const refreshEvents = document.querySelector("#refresh-events");
const runtimeEventList = document.querySelector("#runtime-event-list");
const logLevelFilter = document.querySelector("#log-level-filter");
const logSearchFilter = document.querySelector("#log-search-filter");
const refreshLogs = document.querySelector("#refresh-logs");
const runtimeLogList = document.querySelector("#runtime-log-list");
const diagnosticForm = document.querySelector("#diagnostic-form");
const diagnosticMessage = document.querySelector("#diagnostic-message");
const diagnosticResult = document.querySelector("#diagnostic-result");
const recentConfirmationList = document.querySelector("#recent-confirmation-list");
const taskForm = document.querySelector("#task-form");
const taskList = document.querySelector("#task-list");
const cancelTaskEdit = document.querySelector("#cancel-task-edit");
const noteForm = document.querySelector("#note-form");
const noteList = document.querySelector("#note-list");
const noteSearch = document.querySelector("#note-search");
const cancelNoteEdit = document.querySelector("#cancel-note-edit");
const reminderForm = document.querySelector("#reminder-form");
const reminderList = document.querySelector("#reminder-list");
const cancelReminderEdit = document.querySelector("#cancel-reminder-edit");

const activeConversationId = "main";
const liveStartedAt = Date.now() / 1000;
const deliveredReminderIds = new Set();
window.setTimeout(() => {
  const liveConversation = new EventSource(
    `/api/conversations/${encodeURIComponent(activeConversationId)}/live?after=${liveStartedAt}`,
  );
  liveConversation.addEventListener("reminder", (event) => {
    const delivery = JSON.parse(event.data);
    if (deliveredReminderIds.has(delivery.reminder_id)) return;
    deliveredReminderIds.add(delivery.reminder_id);
    appendMessage(delivery.role, delivery.content);
    status.textContent = "Reminder delivered.";
  });
}, 750);
let selectedConversationId = null;
let pendingResetConfirmation = null;
let eventCursor = 0;
let logCursor = 0;
let operationsPoll = null;

function makeEmptyState(content) {
  const empty = document.createElement("p");
  empty.className = "empty-state";
  empty.textContent = content;
  return empty;
}

function showWelcome() {
  messages.replaceChildren();
  const item = document.createElement("li");
  item.className = "welcome-note";

  const mark = document.createElement("span");
  mark.setAttribute("aria-hidden", "true");
  mark.textContent = "悠";

  const text = document.createElement("p");
  text.textContent =
    "Start anywhere. Say hello, share a thought, or simply see where the moment goes.";

  item.append(mark, text);
  messages.append(item);
}

function appendMessage(role, content, { scroll = true } = {}) {
  const item = document.createElement("li");
  item.className = `message message-${role}`;
  item.dataset.role = role;

  const label = document.createElement("span");
  label.className = "message-label";
  label.textContent = role === "user" ? "You" : "Mellowday";

  const text = document.createElement("p");
  text.textContent = content;

  item.append(label, text);
  messages.append(item);
  if (scroll) {
    item.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
}

async function loadActiveConversation() {
  try {
    const indexResponse = await fetch("/api/conversations");
    if (!indexResponse.ok) {
      throw new Error(`Request failed with ${indexResponse.status}`);
    }
    const index = await indexResponse.json();
    const isStored = index.conversations.some(
      (conversation) => conversation.conversation_id === activeConversationId,
    );
    if (!isStored) {
      showWelcome();
      return;
    }

    const response = await fetch(
      `/api/conversations/${encodeURIComponent(activeConversationId)}`,
    );
    if (!response.ok) throw new Error(`Request failed with ${response.status}`);

    const conversation = await response.json();
    messages.replaceChildren();
    conversation.messages.forEach((message) => {
      appendMessage(message.role, message.content, { scroll: false });
    });
  } catch (error) {
    showWelcome();
    status.textContent = "Stored conversation history is unavailable.";
  }
}

function clearHistoryDetail() {
  clearResetConfirmation();
  selectedConversationId = null;
  historyTitle.textContent = "No conversation selected";
  historyMetadata.textContent = "Choose a conversation to review its messages.";
  historyMessages.replaceChildren(makeEmptyState("No messages selected."));
  resetHistory.disabled = true;
}

function clearResetConfirmation() {
  pendingResetConfirmation = null;
  resetConfirmation.hidden = true;
  resetHistory.hidden = false;
  cancelReset.disabled = false;
  confirmReset.disabled = false;
}

function formatUpdatedAt(value) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value * 1000));
}

function renderConversationList(conversations) {
  conversationList.replaceChildren();
  if (conversations.length === 0) {
    conversationList.append(makeEmptyState("No conversations yet."));
    clearHistoryDetail();
    return;
  }

  conversations.forEach((conversation) => {
    const button = document.createElement("button");
    button.className = "conversation-card";
    button.type = "button";
    button.setAttribute(
      "aria-label",
      `${conversation.conversation_id} · ${conversation.message_count} messages`,
    );

    const identity = document.createElement("strong");
    identity.textContent = conversation.conversation_id;
    const count = document.createElement("span");
    count.textContent = `${conversation.message_count} messages`;
    const updated = document.createElement("small");
    updated.textContent = formatUpdatedAt(conversation.updated_at);
    button.append(identity, count, updated);
    button.addEventListener("click", () => loadConversationDetail(conversation));
    conversationList.append(button);
  });
}

async function loadConversations() {
  settingsStatus.textContent = "";
  try {
    const response = await fetch("/api/conversations");
    if (!response.ok) throw new Error(`Request failed with ${response.status}`);
    const payload = await response.json();
    renderConversationList(payload.conversations);
  } catch (error) {
    conversationList.replaceChildren(
      makeEmptyState("Conversation History is unavailable."),
    );
    clearHistoryDetail();
    settingsStatus.textContent = "The local history service could not be read.";
  }
}

async function loadConversationDetail(summary) {
  clearResetConfirmation();
  settingsStatus.textContent = "";
  try {
    const response = await fetch(
      `/api/conversations/${encodeURIComponent(summary.conversation_id)}`,
    );
    if (!response.ok) throw new Error(`Request failed with ${response.status}`);
    const payload = await response.json();
    selectedConversationId = summary.conversation_id;
    historyTitle.textContent = summary.conversation_id;
    historyMetadata.textContent =
      `${summary.message_count} messages · ${summary.character_count} characters · ` +
      `updated ${formatUpdatedAt(summary.updated_at)}`;
    historyMessages.replaceChildren();
    payload.messages.forEach((message) => {
      const item = document.createElement("li");
      item.className = `history-message history-message-${message.role}`;

      const role = document.createElement("span");
      role.className = "message-label";
      role.textContent = message.role === "user" ? "User" : "Assistant";
      const content = document.createElement("p");
      content.textContent = message.content;
      item.append(role, content);
      historyMessages.append(item);
    });
    resetHistory.disabled = false;
  } catch (error) {
    clearHistoryDetail();
    settingsStatus.textContent = "The selected conversation could not be read.";
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const content = input.value.trim();
  if (!content) return;

  appendMessage("user", content);
  input.value = "";
  input.disabled = true;
  submit.disabled = true;
  status.textContent = "Listening…";

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: "main", content }),
    });
    if (!response.ok) throw new Error(`Request failed with ${response.status}`);

    const turn = await response.json();
    appendMessage(turn.chat_content.role, turn.chat_content.content);
    status.textContent = "Reply received.";
  } catch (error) {
    status.textContent = "The local service could not complete that message.";
  } finally {
    input.disabled = false;
    submit.disabled = false;
    input.focus();
  }
});

refreshHistory.addEventListener("click", loadConversations);

resetHistory.addEventListener("click", async () => {
  if (!selectedConversationId) return;
  const conversationId = selectedConversationId;
  resetHistory.disabled = true;
  settingsStatus.textContent = "Preparing reset confirmation…";
  try {
    const response = await fetch(
      `/api/conversations/${encodeURIComponent(conversationId)}/reset-confirmation`,
      { method: "POST" },
    );
    if (!response.ok) throw new Error(`Request failed with ${response.status}`);
    const payload = await response.json();
    pendingResetConfirmation = payload.confirmation;
    resetHistory.hidden = true;
    resetConfirmation.hidden = false;
    settingsStatus.textContent = "Explicit confirmation is required.";
  } catch (error) {
    resetHistory.disabled = false;
    settingsStatus.textContent = "Reset confirmation could not be prepared.";
  }
});

async function decideReset(decision) {
  if (!selectedConversationId || !pendingResetConfirmation) return;
  const conversationId = selectedConversationId;
  cancelReset.disabled = true;
  confirmReset.disabled = true;
  settingsStatus.textContent =
    decision === "accept"
      ? "Resetting Conversation History…"
      : "Cancelling reset…";
  try {
    const response = await fetch(
      `/api/conversations/${encodeURIComponent(conversationId)}/reset`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          confirmation_id: pendingResetConfirmation.id,
          binding: pendingResetConfirmation.binding,
          decision,
        }),
      },
    );
    if (!response.ok) throw new Error(`Request failed with ${response.status}`);
    clearResetConfirmation();
    if (decision === "reject") {
      resetHistory.disabled = false;
      settingsStatus.textContent = "Reset cancelled.";
      return;
    }
    if (conversationId === activeConversationId) showWelcome();
    clearHistoryDetail();
    await loadConversations();
    settingsStatus.textContent = "Conversation History reset.";
  } catch (error) {
    cancelReset.disabled = false;
    confirmReset.disabled = false;
    settingsStatus.textContent = "Conversation History could not be reset.";
  }
}

cancelReset.addEventListener("click", () => decideReset("reject"));
confirmReset.addEventListener("click", () => decideReset("accept"));

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

function addText(parent, className, content) {
  const element = document.createElement("span");
  element.className = className;
  element.textContent = content;
  parent.append(element);
  return element;
}

function renderTools(tools) {
  toolList.replaceChildren();
  toolCount.textContent = String(tools.length);

  if (tools.length === 0) {
    addText(toolList, "empty-capability", "No Tools are registered.");
    return;
  }

  for (const tool of tools) {
    const card = document.createElement("article");
    card.className = "capability-card";

    const title = document.createElement("code");
    title.className = "capability-name";
    title.textContent = tool.name;
    const description = document.createElement("p");
    description.className = "capability-description";
    description.textContent = tool.description;

    const facts = document.createElement("dl");
    facts.className = "capability-facts";
    const values = [
      ["Side effect", tool.side_effect],
      ["Risk", tool.risk],
      [
        "Permissions",
        tool.permission_requirements.length
          ? tool.permission_requirements.join(", ")
          : "None",
      ],
    ];
    for (const [label, value] of values) {
      const fact = document.createElement("div");
      const term = document.createElement("dt");
      term.textContent = label;
      const detail = document.createElement("dd");
      detail.textContent = value;
      fact.append(term, detail);
      facts.append(fact);
    }

    const schema = document.createElement("details");
    schema.className = "schema-detail";
    const summary = document.createElement("summary");
    summary.textContent = "Input schema";
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(tool.input_schema, null, 2);
    schema.append(summary, pre);

    card.append(title, description, facts, schema);
    toolList.append(card);
  }
}

function renderSkills(skills) {
  skillList.replaceChildren();
  skillCount.textContent = String(skills.length);

  if (skills.length === 0) {
    addText(skillList, "empty-capability", "No Skills are registered.");
    return;
  }

  for (const skill of skills) {
    const card = document.createElement("article");
    card.className = "capability-card skill-card";

    const content = document.createElement("div");
    const title = document.createElement("code");
    title.className = "capability-name";
    title.textContent = skill.name;
    const description = document.createElement("p");
    description.className = "capability-description";
    description.textContent = skill.description;
    content.append(title, description);

    const control = document.createElement("label");
    control.className = "skill-enablement";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = skill.enabled;
    checkbox.setAttribute("aria-label", `Enable ${skill.name} Skill`);
    const state = addText(
      control,
      "skill-state",
      skill.enabled ? "Enabled" : "Disabled",
    );
    control.prepend(checkbox);

    checkbox.addEventListener("change", async () => {
      const intended = checkbox.checked;
      checkbox.disabled = true;
      settingsStatus.textContent = `Updating ${skill.name}.`;
      try {
        const response = await fetch(
          `/api/settings/skills/${encodeURIComponent(skill.name)}/enabled`,
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ enabled: intended }),
          },
        );
        if (!response.ok) throw new Error(`Request failed with ${response.status}`);
        const updated = await response.json();
        checkbox.checked = updated.skill.enabled;
        state.textContent = updated.skill.enabled ? "Enabled" : "Disabled";
        settingsStatus.textContent = `${skill.name} is ${state.textContent.toLowerCase()}.`;
      } catch (error) {
        checkbox.checked = !intended;
        settingsStatus.textContent = `Could not update ${skill.name}.`;
      } finally {
        checkbox.disabled = false;
      }
    });

    card.append(content, control);
    skillList.append(card);
  }
}

async function loadCapabilities() {
  const response = await fetch("/api/settings/capabilities");
  if (!response.ok) throw new Error(`Request failed with ${response.status}`);
  const capabilities = await response.json();
  renderTools(capabilities.tools);
  renderSkills(capabilities.skills);
}

async function loadPersona() {
  const response = await fetch("/api/settings/persona");
  if (!response.ok) throw new Error(`Request failed with ${response.status}`);
  const { persona } = await response.json();
  for (const [name, value] of Object.entries(persona)) {
    personaForm.elements.namedItem(name).value = value;
  }
}

function resetTaskForm() {
  taskForm.reset();
  taskForm.elements.namedItem("task_id").value = "";
  taskForm.querySelector('button[type="submit"]').textContent = "Add Task";
  cancelTaskEdit.hidden = true;
}

function editTask(task) {
  taskForm.elements.namedItem("task_id").value = task.id;
  taskForm.elements.namedItem("title").value = task.title;
  taskForm.elements.namedItem("details").value = task.details || "";
  taskForm.elements.namedItem("deadline").value = task.deadline || "";
  taskForm.querySelector('button[type="submit"]').textContent = "Save Task";
  cancelTaskEdit.hidden = false;
  taskForm.elements.namedItem("title").focus();
}

function taskAction(label, task, handler) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "text-button";
  button.textContent = label;
  button.setAttribute("aria-label", `${label} ${task.title}`);
  button.addEventListener("click", handler);
  return button;
}

function renderTasks(tasks) {
  taskList.replaceChildren();
  if (tasks.length === 0) {
    taskList.append(makeEmptyState("No Tasks yet."));
    return;
  }
  for (const task of tasks) {
    const card = document.createElement("article");
    card.className = "capability-card task-card";
    const heading = document.createElement("div");
    heading.className = "task-card-heading";
    const title = document.createElement("strong");
    title.textContent = task.title;
    const state = document.createElement("span");
    state.className = "skill-state";
    state.textContent = task.completed ? "Completed" : "Open";
    heading.append(title, state);
    const details = document.createElement("p");
    details.className = "capability-description";
    details.textContent = task.details || "No details";
    const deadline = document.createElement("p");
    deadline.className = "task-deadline";
    deadline.textContent = task.deadline ? `Deadline ${task.deadline}` : "No deadline";
    const actions = document.createElement("div");
    actions.className = "task-actions";
    actions.append(
      taskAction(task.completed ? "Reopen" : "Complete", task, async () => {
        const operation = task.completed ? "reopen" : "complete";
        const response = await fetch(
          `/api/settings/tasks/${encodeURIComponent(task.id)}/${operation}`,
          { method: "POST" },
        );
        if (!response.ok) {
          settingsStatus.textContent = "Task state could not be updated.";
          return;
        }
        settingsStatus.textContent = task.completed ? "Task reopened." : "Task completed.";
        await loadTasks();
      }),
      taskAction("Edit", task, () => editTask(task)),
      taskAction("Delete", task, async () => {
        if (!window.confirm(`Permanently delete ${task.title}?`)) return;
        const path = `/api/settings/tasks/${encodeURIComponent(task.id)}`;
        const requested = await fetch(`${path}/delete-confirmation`, {
          method: "POST",
        });
        if (!requested.ok) {
          settingsStatus.textContent = "Task could not be deleted.";
          return;
        }
        const { confirmation } = await requested.json();
        const response = await fetch(path, {
          method: "DELETE",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            confirmation_id: confirmation.id,
            binding: confirmation.binding,
            decision: "accept",
          }),
        });
        if (!response.ok) {
          settingsStatus.textContent = "Task delete confirmation is unavailable.";
          return;
        }
        settingsStatus.textContent = "Task deleted.";
        resetTaskForm();
        await loadTasks();
      }),
    );
    card.append(heading, details, deadline, actions);
    taskList.append(card);
  }
}

async function loadTasks() {
  const response = await fetch("/api/settings/tasks");
  if (!response.ok) throw new Error(`Request failed with ${response.status}`);
  const payload = await response.json();
  renderTasks(payload.tasks);
}

taskForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const taskId = taskForm.elements.namedItem("task_id").value;
  const button = taskForm.querySelector('button[type="submit"]');
  const values = Object.fromEntries(new FormData(taskForm).entries());
  const body = {
    title: values.title,
    details: values.details || null,
    deadline: values.deadline || null,
  };
  button.disabled = true;
  try {
    const response = await fetch(
      taskId ? `/api/settings/tasks/${encodeURIComponent(taskId)}` : "/api/settings/tasks",
      {
        method: taskId ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    );
    if (!response.ok) {
      const payload = await response.json();
      throw new Error(payload.detail?.message || `Request failed with ${response.status}`);
    }
    resetTaskForm();
    settingsStatus.textContent = taskId ? "Task saved." : "Task added.";
    await loadTasks();
  } catch (error) {
    settingsStatus.textContent = `Task could not be saved: ${error.message}`;
  } finally {
    button.disabled = false;
  }
});

cancelTaskEdit.addEventListener("click", resetTaskForm);

function noteLabel(note) {
  return note.title || "Untitled Note";
}

function resetNoteForm() {
  noteForm.reset();
  noteForm.elements.namedItem("note_id").value = "";
  noteForm.querySelector('button[type="submit"]').textContent = "Add Note";
  cancelNoteEdit.hidden = true;
}

function editNote(note) {
  noteForm.elements.namedItem("note_id").value = note.id;
  noteForm.elements.namedItem("title").value = note.title || "";
  noteForm.elements.namedItem("content").value = note.content;
  noteForm.querySelector('button[type="submit"]').textContent = "Save Note";
  cancelNoteEdit.hidden = false;
  noteForm.elements.namedItem("content").focus();
}

function noteAction(label, note, handler) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "text-button";
  button.textContent = label;
  button.setAttribute("aria-label", `${label} ${noteLabel(note)}`);
  button.addEventListener("click", handler);
  return button;
}

function renderNotes(notes) {
  noteList.replaceChildren();
  if (notes.length === 0) {
    noteList.append(makeEmptyState(noteSearch.value ? "No matching Notes." : "No Notes yet."));
    return;
  }
  for (const note of notes) {
    const card = document.createElement("article");
    card.className = "capability-card task-card";
    const heading = document.createElement("div");
    heading.className = "task-card-heading";
    const title = document.createElement("strong");
    title.textContent = noteLabel(note);
    const updated = document.createElement("span");
    updated.className = "skill-state";
    updated.textContent = `Updated ${formatUpdatedAt(note.updated_at)}`;
    heading.append(title, updated);
    const content = document.createElement("p");
    content.className = "note-content";
    content.textContent = note.content;
    const actions = document.createElement("div");
    actions.className = "task-actions";
    actions.append(
      noteAction("Edit", note, () => editNote(note)),
      noteAction("Delete", note, async () => {
        if (!window.confirm(`Permanently delete ${noteLabel(note)}?`)) return;
        const path = `/api/settings/notes/${encodeURIComponent(note.id)}`;
        const requested = await fetch(`${path}/delete-confirmation`, { method: "POST" });
        if (!requested.ok) {
          settingsStatus.textContent = "Note could not be deleted.";
          return;
        }
        const { confirmation } = await requested.json();
        const response = await fetch(path, {
          method: "DELETE",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            confirmation_id: confirmation.id,
            binding: confirmation.binding,
            decision: "accept",
          }),
        });
        settingsStatus.textContent = response.ok ? "Note deleted." : "Note delete confirmation is unavailable.";
        if (response.ok) {
          resetNoteForm();
          await loadNotes();
        }
      }),
    );
    card.append(heading, content, actions);
    noteList.append(card);
  }
}

async function loadNotes() {
  const query = noteSearch.value.trim();
  const response = await fetch(`/api/settings/notes?q=${encodeURIComponent(query)}`);
  if (!response.ok) throw new Error(`Request failed with ${response.status}`);
  const payload = await response.json();
  renderNotes(payload.notes);
}

noteForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const noteId = noteForm.elements.namedItem("note_id").value;
  const button = noteForm.querySelector('button[type="submit"]');
  const values = Object.fromEntries(new FormData(noteForm).entries());
  const body = { title: values.title || null, content: values.content };
  button.disabled = true;
  try {
    const response = await fetch(
      noteId ? `/api/settings/notes/${encodeURIComponent(noteId)}` : "/api/settings/notes",
      {
        method: noteId ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    );
    if (!response.ok) {
      const payload = await response.json();
      throw new Error(payload.detail?.message || `Request failed with ${response.status}`);
    }
    resetNoteForm();
    settingsStatus.textContent = noteId ? "Note saved." : "Note added.";
    await loadNotes();
  } catch (error) {
    settingsStatus.textContent = `Note could not be saved: ${error.message}`;
  } finally {
    button.disabled = false;
  }
});

noteSearch.addEventListener("input", loadNotes);
cancelNoteEdit.addEventListener("click", resetNoteForm);

function reminderInputValue(value) {
  const date = new Date(value);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function resetReminderForm() {
  reminderForm.reset();
  reminderForm.elements.namedItem("reminder_id").value = "";
  reminderForm.querySelector('button[type="submit"]').textContent = "Add Reminder";
  cancelReminderEdit.hidden = true;
}

function editReminder(reminder) {
  reminderForm.elements.namedItem("reminder_id").value = reminder.id;
  reminderForm.elements.namedItem("message").value = reminder.message;
  reminderForm.elements.namedItem("due_at").value = reminderInputValue(reminder.due_at);
  reminderForm.elements.namedItem("task_id").value = reminder.task_id || "";
  reminderForm.querySelector('button[type="submit"]').textContent = "Save Reminder";
  cancelReminderEdit.hidden = false;
  reminderForm.elements.namedItem("message").focus();
}

function reminderAction(label, reminder, handler) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "text-button";
  button.textContent = label;
  button.setAttribute("aria-label", `${label} ${reminder.message}`);
  button.addEventListener("click", handler);
  return button;
}

function reminderStateLabel(state) {
  return state.charAt(0).toUpperCase() + state.slice(1);
}

function renderReminders(reminders) {
  reminderList.replaceChildren();
  if (reminders.length === 0) {
    reminderList.append(makeEmptyState("No Reminders yet."));
    return;
  }
  for (const reminder of reminders) {
    const card = document.createElement("article");
    card.className = "capability-card task-card";
    const heading = document.createElement("div");
    heading.className = "task-card-heading";
    const message = document.createElement("strong");
    message.textContent = reminder.message;
    const state = document.createElement("span");
    state.className = "skill-state";
    state.textContent = reminderStateLabel(reminder.delivery_state);
    heading.append(message, state);
    const due = document.createElement("p");
    due.className = "task-deadline";
    due.textContent = `Due ${new Date(reminder.due_at).toLocaleString()}`;
    const link = document.createElement("p");
    link.className = "capability-description";
    link.textContent = reminder.task_id ? `Linked Task ${reminder.task_id}` : "No linked Task";
    const actions = document.createElement("div");
    actions.className = "task-actions";
    actions.append(
      reminderAction("Edit", reminder, () => editReminder(reminder)),
      reminderAction("Dismiss", reminder, async () => {
        const response = await fetch(
          `/api/settings/reminders/${encodeURIComponent(reminder.id)}/dismiss`,
          { method: "POST" },
        );
        settingsStatus.textContent = response.ok ? "Reminder dismissed." : "Reminder could not be dismissed.";
        if (response.ok) await loadReminders();
      }),
      reminderAction("Cancel", reminder, async () => {
        const response = await fetch(
          `/api/settings/reminders/${encodeURIComponent(reminder.id)}/cancel`,
          { method: "POST" },
        );
        settingsStatus.textContent = response.ok ? "Reminder cancelled." : "Reminder could not be cancelled.";
        if (response.ok) await loadReminders();
      }),
      reminderAction("Delete", reminder, async () => {
        if (!window.confirm(`Permanently delete ${reminder.message}?`)) return;
        const path = `/api/settings/reminders/${encodeURIComponent(reminder.id)}`;
        const requested = await fetch(`${path}/delete-confirmation`, { method: "POST" });
        if (!requested.ok) {
          settingsStatus.textContent = "Reminder could not be deleted.";
          return;
        }
        const { confirmation } = await requested.json();
        const response = await fetch(path, {
          method: "DELETE",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            confirmation_id: confirmation.id,
            binding: confirmation.binding,
            decision: "accept",
          }),
        });
        settingsStatus.textContent = response.ok ? "Reminder deleted." : "Reminder delete confirmation is unavailable.";
        if (response.ok) {
          resetReminderForm();
          await loadReminders();
        }
      }),
    );
    card.append(heading, due, link, actions);
    reminderList.append(card);
  }
}

async function loadReminders() {
  const response = await fetch("/api/settings/reminders");
  if (!response.ok) throw new Error(`Request failed with ${response.status}`);
  const payload = await response.json();
  renderReminders(payload.reminders);
}

reminderForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const reminderId = reminderForm.elements.namedItem("reminder_id").value;
  const button = reminderForm.querySelector('button[type="submit"]');
  const values = Object.fromEntries(new FormData(reminderForm).entries());
  const body = {
    message: values.message,
    due_at: new Date(values.due_at).toISOString(),
    task_id: values.task_id || null,
    conversation_id: activeConversationId,
  };
  button.disabled = true;
  try {
    const response = await fetch(
      reminderId ? `/api/settings/reminders/${encodeURIComponent(reminderId)}` : "/api/settings/reminders",
      {
        method: reminderId ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    );
    if (!response.ok) {
      const payload = await response.json();
      throw new Error(payload.detail?.message || `Request failed with ${response.status}`);
    }
    resetReminderForm();
    settingsStatus.textContent = reminderId ? "Reminder saved." : "Reminder added.";
    await loadReminders();
  } catch (error) {
    settingsStatus.textContent = `Reminder could not be saved: ${error.message}`;
  } finally {
    button.disabled = false;
  }
});

cancelReminderEdit.addEventListener("click", resetReminderForm);

function resetProviderForm() {
  providerForm.reset();
  providerForm.elements.namedItem("provider_id").value = "";
  providerForm.elements.namedItem("timeout_seconds").value = "60";
  providerForm.elements.namedItem("max_retries").value = "2";
  providerForm.querySelector('button[type="submit"]').textContent = "Add Provider";
  cancelProviderEdit.hidden = true;
}

function editProvider(provider) {
  for (const name of ["name", "base_url", "model", "timeout_seconds", "max_retries"]) {
    providerForm.elements.namedItem(name).value = provider[name];
  }
  providerForm.elements.namedItem("provider_id").value = provider.id;
  providerForm.elements.namedItem("api_key").value = "";
  providerForm.querySelector('button[type="submit"]').textContent = "Save Provider";
  cancelProviderEdit.hidden = false;
  providerForm.elements.namedItem("name").focus();
}

function providerAction(label, provider, handler) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "text-button";
  button.textContent = label;
  button.setAttribute("aria-label", `${label} ${provider.name}`);
  button.addEventListener("click", handler);
  return button;
}

function renderProviders(providers) {
  providerList.replaceChildren();
  if (providers.length === 0) {
    providerList.append(makeEmptyState("No model Providers configured."));
    return;
  }
  for (const provider of providers) {
    const card = document.createElement("article");
    card.className = "capability-card provider-card";

    const heading = document.createElement("div");
    heading.className = "provider-card-heading";
    const name = document.createElement("code");
    name.className = "capability-name";
    name.textContent = provider.name;
    const selection = document.createElement("span");
    selection.className = "skill-state";
    selection.textContent = provider.selected ? "Selected" : "Not selected";
    heading.append(name, selection);

    const facts = document.createElement("p");
    facts.className = "capability-description";
    const model = document.createElement("span");
    model.textContent = provider.model;
    const endpoint = document.createElement("span");
    endpoint.textContent = ` · ${provider.base_url} · `;
    const credential = document.createElement("span");
    credential.textContent = provider.api_key || "No credential";
    facts.append(model, endpoint, credential);

    const state = document.createElement("div");
    state.className = "provider-state";
    const enablement = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = provider.enabled;
    checkbox.setAttribute("aria-label", `Enable ${provider.name} Provider`);
    const stateText = document.createElement("span");
    stateText.textContent = provider.enabled ? "Enabled" : "Disabled";
    enablement.append(checkbox, stateText);
    state.append(enablement);

    checkbox.addEventListener("change", async () => {
      checkbox.disabled = true;
      try {
        const response = await fetch(
          `/api/settings/providers/${encodeURIComponent(provider.id)}/enabled`,
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ enabled: checkbox.checked }),
          },
        );
        if (!response.ok) throw new Error(`Request failed with ${response.status}`);
        settingsStatus.textContent = `${provider.name} is ${
          checkbox.checked ? "enabled" : "disabled"
        }.`;
        await loadProviders();
      } catch (error) {
        checkbox.checked = !checkbox.checked;
        checkbox.disabled = false;
        settingsStatus.textContent = `${provider.name} could not be updated.`;
      }
    });

    const actions = document.createElement("div");
    actions.className = "provider-actions";
    actions.append(
      providerAction("Edit", provider, () => editProvider(provider)),
      providerAction("Validate", provider, async () => {
        settingsStatus.textContent = `Validating ${provider.name}.`;
        try {
          const response = await fetch(
            `/api/settings/providers/${encodeURIComponent(provider.id)}/validate`,
            { method: "POST" },
          );
          if (!response.ok) throw new Error(`Request failed with ${response.status}`);
          const result = await response.json();
          if (!result.valid) {
            settingsStatus.textContent = `${provider.name} validation failed: ${result.failure.code}.`;
            return;
          }
          settingsStatus.textContent = `${provider.name} validated.`;
        } catch (error) {
          settingsStatus.textContent = `${provider.name} could not be validated.`;
        }
      }),
    );
    if (!provider.selected) {
      actions.append(
        providerAction("Select", provider, async () => {
          try {
            const response = await fetch(
              `/api/settings/providers/${encodeURIComponent(provider.id)}/select`,
              { method: "POST" },
            );
            if (!response.ok) throw new Error(`Request failed with ${response.status}`);
            settingsStatus.textContent = `${provider.name} selected.`;
            await loadProviders();
          } catch (error) {
            settingsStatus.textContent = `${provider.name} could not be selected.`;
          }
        }),
      );
    }
    card.append(heading, facts, state, actions);
    providerList.append(card);
  }
}

async function loadProviders() {
  const response = await fetch("/api/settings/providers");
  if (!response.ok) throw new Error(`Request failed with ${response.status}`);
  const payload = await response.json();
  renderProviders(payload.providers);
}

providerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const providerId = providerForm.elements.namedItem("provider_id").value;
  const submitButton = providerForm.querySelector('button[type="submit"]');
  const body = Object.fromEntries(new FormData(providerForm).entries());
  delete body.provider_id;
  body.timeout_seconds = Number(body.timeout_seconds);
  body.max_retries = Number(body.max_retries);
  if (!providerId && !body.api_key) {
    settingsStatus.textContent = "An API key is required for a new Provider.";
    return;
  }
  submitButton.disabled = true;
  try {
    const response = await fetch(
      providerId
        ? `/api/settings/providers/${encodeURIComponent(providerId)}`
        : "/api/settings/providers",
      {
        method: providerId ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    );
    if (!response.ok) throw new Error(`Request failed with ${response.status}`);
    const savedName = body.name;
    resetProviderForm();
    settingsStatus.textContent = `${savedName} saved.`;
    await loadProviders();
  } catch (error) {
    settingsStatus.textContent = "Provider configuration could not be saved.";
  } finally {
    submitButton.disabled = false;
  }
});

cancelProviderEdit.addEventListener("click", resetProviderForm);

personaForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = personaForm.querySelector('button[type="submit"]');
  button.disabled = true;
  settingsStatus.textContent = "Saving Persona.";
  const body = Object.fromEntries(new FormData(personaForm).entries());
  try {
    const response = await fetch("/api/settings/persona", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(`Request failed with ${response.status}`);
    const { persona } = await response.json();
    for (const [name, value] of Object.entries(persona)) {
      personaForm.elements.namedItem(name).value = value;
    }
    settingsStatus.textContent = "Persona saved.";
  } catch (error) {
    settingsStatus.textContent = "Persona could not be saved.";
  } finally {
    button.disabled = false;
  }
});

function renderConfirmations(confirmations) {
  confirmationList.replaceChildren();
  confirmationCount.textContent = String(confirmations.length);

  if (confirmations.length === 0) {
    addText(confirmationList, "empty-capability", "No confirmations are waiting.");
    return;
  }

  for (const confirmation of confirmations) {
    const card = document.createElement("article");
    card.className = "capability-card confirmation-card";

    const heading = document.createElement("div");
    heading.className = "confirmation-heading";
    const tool = document.createElement("code");
    tool.className = "capability-name";
    tool.textContent = confirmation.binding.tool;
    const expiry = document.createElement("time");
    expiry.className = "confirmation-expiry";
    expiry.dateTime = new Date(confirmation.expires_at * 1000).toISOString();
    expiry.textContent = `Expires ${new Date(
      confirmation.expires_at * 1000,
    ).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
    heading.append(tool, expiry);

    const context = document.createElement("p");
    context.className = "confirmation-context";
    context.textContent = `Conversation ${confirmation.binding.conversation_id}`;

    const argumentsDetail = document.createElement("details");
    argumentsDetail.className = "schema-detail";
    const summary = document.createElement("summary");
    summary.textContent = "Normalized arguments";
    const argumentsText = document.createElement("pre");
    argumentsText.textContent = JSON.stringify(
      confirmation.binding.arguments,
      null,
      2,
    );
    argumentsDetail.append(summary, argumentsText);

    const actions = document.createElement("div");
    actions.className = "confirmation-actions";
    for (const [decision, label] of [
      ["reject", "Reject"],
      ["accept", "Accept"],
    ]) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `decision-button decision-${decision}`;
      button.textContent = label;
      button.setAttribute(
        "aria-label",
        `${label} ${confirmation.binding.tool} confirmation`,
      );
      button.addEventListener("click", async () => {
        for (const control of actions.querySelectorAll("button")) {
          control.disabled = true;
        }
        settingsStatus.textContent = "Applying confirmation decision.";
        try {
          const response = await fetch(
            `/api/settings/confirmations/${encodeURIComponent(confirmation.id)}/decision`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                decision,
                binding: confirmation.binding,
              }),
            },
          );
          if (!response.ok) {
            throw new Error(`Request failed with ${response.status}`);
          }
          const result = await response.json();
          if (result.turn.chat_content.content) {
            appendMessage(
              result.turn.chat_content.role,
              result.turn.chat_content.content,
            );
          }
          settingsStatus.textContent = `Confirmation ${
            decision === "accept" ? "accepted" : "rejected"
          }.`;
          await Promise.all([
            loadConfirmations(),
            loadRecentConfirmations(),
            loadAuditHistory(),
          ]);
        } catch (error) {
          settingsStatus.textContent = "The confirmation decision could not be applied.";
          for (const control of actions.querySelectorAll("button")) {
            control.disabled = false;
          }
        }
      });
      actions.append(button);
    }

    card.append(heading, context, argumentsDetail, actions);
    confirmationList.append(card);
  }
}

async function loadConfirmations() {
  const response = await fetch("/api/settings/confirmations");
  if (!response.ok) throw new Error(`Request failed with ${response.status}`);
  const payload = await response.json();
  renderConfirmations(payload.confirmations);
}

function renderRecentConfirmations(confirmations) {
  recentConfirmationList.replaceChildren();
  if (confirmations.length === 0) {
    recentConfirmationList.append(makeEmptyState("No recent decisions."));
    return;
  }
  for (const confirmation of [...confirmations].reverse()) {
    const item = document.createElement("p");
    item.className = "runtime-record";
    const tool = document.createElement("code");
    tool.textContent = confirmation.tool;
    const state = document.createElement("span");
    state.textContent = confirmation.status;
    const occurred = document.createElement("time");
    occurred.dateTime = new Date(confirmation.decided_at * 1000).toISOString();
    occurred.textContent = new Date(
      confirmation.decided_at * 1000,
    ).toLocaleTimeString();
    item.append(tool, state, occurred);
    recentConfirmationList.append(item);
  }
}

async function loadRecentConfirmations() {
  const response = await fetch("/api/settings/confirmations/recent");
  if (!response.ok) throw new Error(`Request failed with ${response.status}`);
  const payload = await response.json();
  renderRecentConfirmations(payload.confirmations);
}

async function loadOperationStatus() {
  const response = await fetch("/api/settings/status");
  if (!response.ok) throw new Error(`Request failed with ${response.status}`);
  const payload = await response.json();
  backendStatus.textContent = payload.backend.ok ? "Healthy" : "Unavailable";
  const health = payload.provider.health?.state || "not_checked";
  const healthLabel = health
    .split("_")
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join(" ");
  providerStatus.textContent = `${payload.provider.name} · ${healthLabel}`;
  sessionStatus.textContent = `${payload.sessions} conversation${
    payload.sessions === 1 ? "" : "s"
  }`;
}

function appendRuntimeRecords(list, records, formatter, replace) {
  if (replace) list.replaceChildren();
  if (!replace && records.length > 0) {
    list.querySelector(".empty-capability")?.remove();
  }
  for (const record of records) {
    const item = document.createElement("li");
    item.className = "runtime-record";
    formatter(item, record);
    list.append(item);
  }
  if (replace && records.length === 0) {
    const item = document.createElement("li");
    item.className = "empty-capability";
    item.textContent = "No matching records.";
    list.append(item);
  }
}

async function loadRuntimeEvents({ incremental = false } = {}) {
  const query = new URLSearchParams({
    since: String(incremental ? eventCursor : 0),
    limit: "100",
  });
  if (eventTypeFilter.value) query.set("type", eventTypeFilter.value);
  if (eventConversationFilter.value.trim()) {
    query.set("conversation_id", eventConversationFilter.value.trim());
  }
  const response = await fetch(`/api/events/recent?${query}`);
  if (!response.ok) throw new Error(`Request failed with ${response.status}`);
  const payload = await response.json();
  appendRuntimeRecords(
    runtimeEventList,
    payload.events,
    (item, event) => {
      const type = document.createElement("code");
      type.textContent = event.type;
      const context = document.createElement("span");
      context.textContent = event.conversation_id || "Agent Core";
      item.append(type, context);
    },
    !incremental,
  );
  eventCursor = payload.cursor;
}

async function loadRuntimeLogs({ incremental = false } = {}) {
  const query = new URLSearchParams({
    since: String(incremental ? logCursor : 0),
    limit: "100",
  });
  if (logLevelFilter.value) query.set("level", logLevelFilter.value);
  if (logSearchFilter.value.trim()) query.set("q", logSearchFilter.value.trim());
  const response = await fetch(`/api/logs/recent?${query}`);
  if (!response.ok) throw new Error(`Request failed with ${response.status}`);
  const payload = await response.json();
  appendRuntimeRecords(
    runtimeLogList,
    payload.logs,
    (item, record) => {
      const level = document.createElement("code");
      level.textContent = record.level;
      const message = document.createElement("span");
      message.textContent = record.message;
      item.append(level, message);
    },
    !incremental,
  );
  logCursor = payload.cursor;
}

async function loadOperations() {
  await Promise.all([
    loadOperationStatus(),
    loadRuntimeEvents(),
    loadRuntimeLogs(),
  ]);
}

refreshOperations.addEventListener("click", async () => {
  try {
    await loadOperations();
    settingsStatus.textContent = "Operational data is up to date.";
  } catch (error) {
    settingsStatus.textContent = `Operational data is unavailable: ${error.message}`;
  }
});

refreshEvents.addEventListener("click", async () => {
  try {
    await loadRuntimeEvents();
  } catch (error) {
    settingsStatus.textContent = `Runtime events are unavailable: ${error.message}`;
  }
});

refreshLogs.addEventListener("click", async () => {
  try {
    await loadRuntimeLogs();
  } catch (error) {
    settingsStatus.textContent = `Runtime logs are unavailable: ${error.message}`;
  }
});

diagnosticForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = diagnosticForm.querySelector('button[type="submit"]');
  button.disabled = true;
  diagnosticResult.textContent = "Running diagnostic probe.";
  try {
    const response = await fetch("/api/settings/diagnostics/probe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: diagnosticMessage.value }),
    });
    if (!response.ok) throw new Error(`Request failed with ${response.status}`);
    const payload = await response.json();
    diagnosticResult.textContent = `${payload.turn.stop_reason} · ${
      payload.duration_ms
    } ms · ${payload.turn.chat_content.content}`;
    await Promise.all([loadOperationStatus(), loadRuntimeEvents()]);
  } catch (error) {
    diagnosticResult.textContent = `Diagnostic probe failed: ${error.message}`;
  } finally {
    button.disabled = false;
  }
});

function renderAuditHistory(events) {
  auditList.replaceChildren();
  auditCount.textContent = String(events.length);
  const ordered = [...events].reverse();

  if (ordered.length === 0) {
    const item = document.createElement("li");
    item.className = "empty-capability";
    item.textContent = "No runtime events have been recorded.";
    auditList.append(item);
    return;
  }

  for (const event of ordered) {
    const item = document.createElement("li");
    item.className = "audit-event";
    const type = document.createElement("code");
    type.textContent = event.type;
    const detail = document.createElement("span");
    detail.textContent = event.details.tool || event.conversation_id || "Agent Core";
    const occurred = document.createElement("time");
    occurred.dateTime = new Date(event.occurred_at * 1000).toISOString();
    occurred.textContent = new Date(event.occurred_at * 1000).toLocaleTimeString(
      [],
      { hour: "2-digit", minute: "2-digit", second: "2-digit" },
    );
    item.append(type, detail, occurred);
    if (event.details.undo) {
      const undo = document.createElement("details");
      undo.className = "audit-undo";
      const summary = document.createElement("summary");
      summary.textContent = "Undo available";
      const metadata = document.createElement("pre");
      metadata.textContent = JSON.stringify(event.details.undo, null, 2);
      undo.append(summary, metadata);
      item.append(undo);
    }
    auditList.append(item);
  }
}

async function loadAuditHistory() {
  const response = await fetch("/api/settings/audit");
  if (!response.ok) throw new Error(`Request failed with ${response.status}`);
  const payload = await response.json();
  renderAuditHistory(payload.events);
}

async function loadSettings() {
  settingsStatus.textContent = "Loading Settings data.";
  try {
    await Promise.all([
      loadPersona(),
      loadTasks(),
      loadNotes(),
      loadReminders(),
      loadProviders(),
      loadConversations(),
      loadCapabilities(),
      loadConfirmations(),
      loadRecentConfirmations(),
      loadAuditHistory(),
      loadOperations(),
    ]);
    settingsStatus.textContent = "Settings data is up to date.";
  } catch (error) {
    settingsStatus.textContent = "Settings data is unavailable.";
  }
}

settingsToggle.addEventListener("click", () => {
  conversation.hidden = true;
  settingsPanel.hidden = false;
  settingsToggle.setAttribute("aria-expanded", "true");
  loadSettings();
  if (operationsPoll !== null) window.clearInterval(operationsPoll);
  operationsPoll = window.setInterval(async () => {
    try {
      await Promise.all([
        loadOperationStatus(),
        loadRuntimeEvents({ incremental: true }),
        loadRuntimeLogs({ incremental: true }),
      ]);
    } catch (error) {
      settingsStatus.textContent = `Live operational updates are unavailable: ${
        error.message
      }`;
    }
  }, 1500);
});

settingsClose.addEventListener("click", () => {
  if (operationsPoll !== null) window.clearInterval(operationsPoll);
  operationsPoll = null;
  settingsPanel.hidden = true;
  conversation.hidden = false;
  settingsToggle.setAttribute("aria-expanded", "false");
  settingsToggle.focus();
});

loadActiveConversation();
