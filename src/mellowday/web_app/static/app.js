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
const toolList = document.querySelector("#tool-list");
const skillList = document.querySelector("#skill-list");
const toolCount = document.querySelector("#tool-count");
const skillCount = document.querySelector("#skill-count");
const confirmationList = document.querySelector("#confirmation-list");
const confirmationCount = document.querySelector("#confirmation-count");
const auditList = document.querySelector("#audit-list");
const auditCount = document.querySelector("#audit-count");

function appendMessage(role, content) {
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
  item.scrollIntoView({ behavior: "smooth", block: "nearest" });
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
