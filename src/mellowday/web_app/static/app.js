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
  settingsStatus.textContent = "Loading registered capabilities.";
  try {
    const response = await fetch("/api/settings/capabilities");
    if (!response.ok) throw new Error(`Request failed with ${response.status}`);
    const capabilities = await response.json();
    renderTools(capabilities.tools);
    renderSkills(capabilities.skills);
    settingsStatus.textContent = "Capability metadata is up to date.";
  } catch (error) {
    settingsStatus.textContent = "Capability metadata is unavailable.";
  }
}

settingsToggle.addEventListener("click", () => {
  conversation.hidden = true;
  settingsPanel.hidden = false;
  settingsToggle.setAttribute("aria-expanded", "true");
  loadCapabilities();
});

settingsClose.addEventListener("click", () => {
  settingsPanel.hidden = true;
  conversation.hidden = false;
  settingsToggle.setAttribute("aria-expanded", "false");
  settingsToggle.focus();
});
