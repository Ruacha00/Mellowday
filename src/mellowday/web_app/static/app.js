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

const activeConversationId = "main";
let selectedConversationId = null;
let pendingResetConfirmation = null;

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
          await Promise.all([loadConfirmations(), loadAuditHistory()]);
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
      loadProviders(),
      loadConversations(),
      loadCapabilities(),
      loadConfirmations(),
      loadAuditHistory(),
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
});

settingsClose.addEventListener("click", () => {
  settingsPanel.hidden = true;
  conversation.hidden = false;
  settingsToggle.setAttribute("aria-expanded", "false");
  settingsToggle.focus();
});

loadActiveConversation();
