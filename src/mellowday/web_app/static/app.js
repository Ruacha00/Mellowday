const form = document.querySelector("#conversation-form");
const input = document.querySelector("#message-input");
const messages = document.querySelector("#messages");
const status = document.querySelector("#composer-status");
const submit = form.querySelector('button[type="submit"]');

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

