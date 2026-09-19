const state = {
  sessionId: null,
  view: "chat",
  kind: "todos",
  busy: false,
  sessions: [],
  editingId: null,
  undo: null,
  skills: [],
  // name -> {open, rows, error, loading} for the expanded version list
  skillVersions: {},
  // name -> {open, loading, error, body, notes, ...} for the rule body panel
  skillDetail: {},
  // name -> true while the rule editor is open
  skillEdit: {},
  // "name@version" -> {open, loading, error, body, notes} for a history body
  skillVersionBody: {},
  // {name, version} while a rollback waits for its second confirmation
  skillConfirm: null,
  // history panel: expanded trace rows (by index) and read tool results (by ref)
  traceOpen: {},
  traceResults: {},
};

const el = (id) => document.getElementById(id);
const KIND_LABEL = { todos: "待办", calendar: "日历", reminders: "提醒", notes: "笔记", memories: "记忆" };
const RECORD_KINDS = ["todos", "calendar", "reminders", "notes", "memories"];

// Status values mirror mellowday.storage.store: doneValues are the statuses that
// mark a record as finished (the management page still lists them), and the
// paired value is what finishing / re-opening a record writes back.
const STATUS_RULES = {
  todos: {
    doneValues: ["done", "completed", "cancelled", "archived", "deleted"],
    doneValue: "done",
    openValue: "open",
    doneLabel: "完成",
    reopenLabel: "重新打开",
  },
  calendar: {
    doneValues: ["done", "completed", "cancelled", "archived", "deleted"],
    doneValue: "done",
    openValue: "scheduled",
    doneLabel: "完成",
    reopenLabel: "重新打开",
  },
  reminders: {
    doneValues: ["done", "delivered", "dismissed", "cancelled", "expired", "deleted"],
    doneValue: "done",
    openValue: "scheduled",
    doneLabel: "完成",
    reopenLabel: "重新打开",
  },
  notes: {
    doneValues: ["archived", "deleted"],
    doneValue: "archived",
    openValue: "active",
    doneLabel: "归档",
    reopenLabel: "恢复",
  },
  memories: {
    doneValues: ["expired", "deleted", "superseded"],
    doneValue: "expired",
    openValue: "active",
    doneLabel: "标记失效",
    reopenLabel: "恢复",
  },
};

const STATUS_LABEL = {
  todos: { open: "未完成", done: "已完成", completed: "已完成", cancelled: "已取消", archived: "已归档", deleted: "已删除" },
  calendar: { scheduled: "已安排", open: "已安排", done: "已完成", completed: "已完成", cancelled: "已取消", archived: "已归档", deleted: "已删除" },
  reminders: { scheduled: "待提醒", open: "待提醒", done: "已完成", delivered: "已提醒", dismissed: "已忽略", cancelled: "已取消", expired: "已过期", deleted: "已删除" },
  notes: { active: "有效", archived: "已归档", deleted: "已删除" },
  memories: { active: "生效中", expired: "已失效", deleted: "已删除", superseded: "已被替代" },
};

const ACTION_LABEL = { create: "新建", update: "修改", status: "状态切换", delete: "删除" };

function statusRule(kind) {
  return STATUS_RULES[kind] || STATUS_RULES.todos;
}

function normalizeStatus(status) {
  return String(status == null ? "" : status).trim().toLowerCase();
}

function isDoneStatus(kind, status) {
  return statusRule(kind).doneValues.includes(normalizeStatus(status));
}

function statusLabel(kind, status) {
  const value = normalizeStatus(status);
  if (!value) return "—";
  const labels = STATUS_LABEL[kind] || {};
  return labels[value] || String(status);
}

function toggleTarget(kind, status) {
  const rule = statusRule(kind);
  return isDoneStatus(kind, status)
    ? { status: rule.openValue, label: rule.reopenLabel }
    : { status: rule.doneValue, label: rule.doneLabel };
}

// --------------------------------------------------------------- local time

function pad2(value) {
  return String(value).padStart(2, "0");
}

function parseMoment(value) {
  if (value == null) return null;
  const text = String(value).trim();
  if (!text) return null;
  let parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) {
    // Some engines reject fractional seconds longer than milliseconds.
    parsed = new Date(text.replace(/(\.\d{3})\d+/, "$1"));
  }
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function formatLocalMoment(value) {
  const parsed = parseMoment(value);
  if (!parsed) return "";
  return parsed.getFullYear() + "-" + pad2(parsed.getMonth() + 1) + "-" + pad2(parsed.getDate()) +
    " " + pad2(parsed.getHours()) + ":" + pad2(parsed.getMinutes());
}

// 被技能取代的事实（CONTRACTS 6quater.2）：记录不删除，meta 里记着来源。
// 管理页不能只给一个状态徽章——用户要看到「被哪条习惯取代、什么时候、为什么」，
// 以及这条事实已经不再参与召回。
function recordMeta(record) {
  const raw = record && record.meta;
  if (raw && typeof raw === "object") return raw;
  if (typeof raw === "string" && raw.trim()) {
    try {
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (err) {
      return {};
    }
  }
  return {};
}

function supersedeSourceText(record) {
  if (!record || normalizeStatus(record.status) !== "superseded") return "";
  const meta = recordMeta(record);
  const skill = String(meta.superseded_by_skill || "").trim();
  const at = formatLocalMoment(meta.superseded_at) || String(meta.superseded_at || "").trim();
  const reason = String(meta.superseded_reason || "").trim();
  if (!skill && !at && !reason) {
    return "已被习惯取代：记录里没有来源信息（技能名/时间）。该事实不再参与召回。";
  }
  const parts = [];
  if (skill) parts.push("被习惯「" + skill + "」取代");
  if (meta.superseded_skill_state === "disabled") parts.push("取代时该习惯已停用");
  if (at) parts.push("时间 " + at);
  if (reason) parts.push("原因：" + reason);
  return parts.join(" · ") + "。该事实不再参与召回（可在管理页恢复为生效中）。";
}

// The management page must never print the stored UTC value: reading due_at
// directly shows a time that is wrong by the UTC offset. due_at_local (sent by
// the backend when it is available) is already local, otherwise the stored
// instant is rendered through the browser timezone; records without a due date
// fall back to the local rendering of created_at.
function recordTimeText(record) {
  const due = record.due_at_local || record.due_at;
  if (due) {
    const text = formatLocalMoment(due) || String(due);
    const hint = ["本地时间（浏览器时区）：" + text];
    hint.push("存储值 due_at：" + (record.due_at || "（空）"));
    if (record.due_at_local) hint.push("due_at_local：" + record.due_at_local);
    return { text: text, title: hint.join("\n") };
  }
  const created = formatLocalMoment(record.created_at);
  if (!created) return { text: "—", title: "该记录没有时间信息" };
  return {
    text: created + "（创建）",
    title: "本地时间（浏览器时区）：" + created + "\n存储值 created_at：" + (record.created_at || "（空）"),
  };
}

function toDatetimeLocalValue(record) {
  const parsed = parseMoment(record.due_at_local || record.due_at);
  if (!parsed) return "";
  return parsed.getFullYear() + "-" + pad2(parsed.getMonth() + 1) + "-" + pad2(parsed.getDate()) +
    "T" + pad2(parsed.getHours()) + ":" + pad2(parsed.getMinutes());
}

// ------------------------------------------------------------------ request

async function requestJson(url, options) {
  try {
    const response = await fetch(url, options);
    const text = await response.text();
    let data = null;
    if (text) {
      try { data = JSON.parse(text); } catch { data = null; }
    }
    if (!response.ok) {
      const detail = (data && (data.detail || data.error)) || ("HTTP " + response.status);
      return { ok: false, status: response.status, error: typeof detail === "string" ? detail : JSON.stringify(detail), data: data };
    }
    if (data && data.ok === false) {
      return { ok: false, status: response.status, error: String(data.error || "操作失败"), data: data };
    }
    return { ok: true, status: response.status, data: data || {} };
  } catch (err) {
    return { ok: false, status: 0, error: "无法连接后端服务（" + err + "）", data: null };
  }
}

function describeError(result) {
  if (!result.status) return String(result.error || "未知错误");
  if (result.error === "unknown_operation_id") return "服务端已找不到这条操作记录（数据可能已重置）";
  if (result.status === 404) return "记录不存在（404：" + result.error + "）";
  if (result.status === 400) return "请求被拒绝（400：" + result.error + "）";
  return result.error + "（HTTP " + result.status + "）";
}

// ------------------------------------------------------- records page chrome

function showRecordsNotice(message, tone) {
  const node = el("records-notice");
  if (!node) return;
  node.textContent = message || "";
  node.className = "records-notice" + (message && tone ? " " + tone : "");
}

function ensureRecordsChrome() {
  const view = el("view-records");
  if (!view || el("records-toolbar")) return;
  const toolbar = document.createElement("div");
  toolbar.id = "records-toolbar";
  toolbar.className = "records-toolbar";
  const undo = document.createElement("button");
  undo.type = "button";
  undo.id = "records-undo";
  undo.className = "ghost";
  undo.textContent = "撤销上一步";
  undo.onclick = undoLastOperation;
  const notice = document.createElement("span");
  notice.id = "records-notice";
  notice.className = "records-notice";
  toolbar.append(undo, notice);
  const head = view.querySelector(".view-head");
  if (head && head.parentNode === view) view.insertBefore(toolbar, head.nextSibling);
  else view.insertBefore(toolbar, view.firstChild);
  updateUndoButton();
}

function updateUndoButton() {
  const button = el("records-undo");
  if (!button) return;
  const pending = state.undo;
  if (!pending) {
    button.textContent = "撤销上一步";
    button.title = "本页还没有可撤销的写操作";
    button.classList.remove("spent");
    return;
  }
  const label = ACTION_LABEL[pending.action] || "修改";
  button.textContent = pending.consumed ? "已撤销上一步" : "撤销上一步";
  button.title = pending.consumed
    ? "上一步（" + label + "）已经撤销过了"
    : "撤销上一步（" + label + "：" + (pending.title || "未命名") + "）";
  button.classList.toggle("spent", Boolean(pending.consumed));
}

// The most recent write of this page keeps its operation_id so it can be undone
// once; the store consumes an operation_id exactly once.
function rememberOperation(payload, action, title) {
  if (!payload || !payload.operation_id) return;
  state.undo = {
    operationId: String(payload.operation_id),
    action: action,
    kind: state.kind,
    title: title || payload.title || "",
    consumed: false,
  };
  updateUndoButton();
}

async function undoLastOperation() {
  const pending = state.undo;
  if (!pending) {
    showRecordsNotice("本页还没有可撤销的写操作。", "warn");
    return;
  }
  if (pending.consumed) {
    showRecordsNotice("上一步已经撤销过了，无需重复撤销。", "warn");
    return;
  }
  const result = await requestJson("/api/records/undo/" + encodeURIComponent(pending.operationId), { method: "POST" });
  if (!result.ok) {
    showRecordsNotice("撤销失败：" + describeError(result), "error");
    return;
  }
  pending.consumed = true;
  updateUndoButton();
  const label = ACTION_LABEL[pending.action] || "修改";
  const where = pending.kind && pending.kind !== state.kind ? KIND_LABEL[pending.kind] + "：" : "";
  state.editingId = null;
  showRecordsNotice("已撤销上一步（" + where + label + "「" + (pending.title || "未命名") + "」）。", "ok");
  loadRecords();
}

// ------------------------------------------------------------------- layout

function render(view) {
  state.view = view;
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  const recordKind = RECORD_KINDS.includes(view) ? view : null;
  el("view-chat").classList.toggle("active", view === "chat");
  el("view-records").classList.toggle("active", Boolean(recordKind));
  el("view-skills").classList.toggle("active", view === "skills");
  el("view-settings").classList.toggle("active", view === "settings");
  if (recordKind) {
    if (state.kind !== recordKind) {
      state.kind = recordKind;
      state.editingId = null;
      showRecordsNotice("", "ok");
    }
    el("records-title").textContent = KIND_LABEL[recordKind];
    ensureRecordsChrome();
    loadRecords();
  }
  if (view === "skills") loadSkills();
  if (view === "settings") loadConfig();
  if (view === "chat") loadSessions();
}

function bubble(role, text = "") {
  const node = document.createElement("div");
  node.className = "msg " + role;
  node.textContent = text;
  el("messages").appendChild(node);
  node.scrollIntoView({ block: "end" });
  return node;
}

function chip(html) {
  const node = document.createElement("div");
  node.className = "chip";
  node.innerHTML = html;
  el("messages").appendChild(node);
  node.scrollIntoView({ block: "end" });
  return node;
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

async function refreshHealth() {
  try {
    const res = await fetch("/api/health").then((r) => r.json());
    el("chat-status").textContent = res.model_configured
      ? "模型已配置，可直接对话。"
      : "尚未配置模型：请在「设置」中填写 API Key。";
  } catch {
    el("chat-status").textContent = "无法连接后端服务。";
  }
}

async function loadSessions() {
  const res = await fetch("/api/sessions").then((r) => r.json());
  state.sessions = res.sessions || [];
  const list = el("session-list");
  list.innerHTML = "";
  state.sessions.forEach((s) => {
    const li = document.createElement("li");
    li.textContent = s.title || "（空会话）";
    li.title = s.session_id;
    if (s.session_id === state.sessionId) li.classList.add("active");
    li.onclick = () => openSession(s.session_id);
    list.appendChild(li);
  });
}

// ------------------------------------------------------------------ history

// The history surface reads the raw execution record (CONTRACTS.md 6ter): the
// display history only ever had user/assistant text, so tool calls, tool
// results and errors were invisible after reopening a session. Every path
// lives in this one table, like the habit page, so a wrong path is one line.
const SESSION_ENDPOINTS = {
  detail: "/api/sessions/{session}",
  // Restricted reference read: ref is a bare name, the backend resolves it
  // inside the current session's artifact directory only. Never scrape a ref
  // out of the placeholder text: the structured field is the only contract.
  toolResult: "/api/sessions/{session}/tool-results/{ref}",
};

// One page of a stored tool result; the backend caps it (ARTIFACT_MAX_CHARS).
const TRACE_RESULT_PAGE = 8000;
// Characters of a tool result/argument shown inline before "expand".
const TRACE_RESULT_PREVIEW_CHARS = 1200;
const TRACE_ARGUMENT_PREVIEW_CHARS = 1200;

function sessionEndpoint(name, params) {
  const template = SESSION_ENDPOINTS[name];
  if (!template) return SESSION_ENDPOINTS.detail;
  const values = params || {};
  return Object.keys(values).reduce(function (url, key) {
    return url.replace("{" + key + "}", encodeURIComponent(String(values[key])));
  }, template);
}

// A ref read can fail because the artifact is gone, because the ref is not a
// bare name, or because the backend route is not there yet. All three have to
// be readable: a silent empty box would look like an empty result.
function describeTraceFailure(result) {
  const detail = String(result.error || "未知错误");
  if (!result.status) return detail;
  if (result.status === 404) return detail + "（HTTP 404：本会话没有这个产物，或后端还没有受限引用读取接口）";
  if (result.status === 400) return detail + "（HTTP 400：引用不合法）";
  return detail + "（HTTP " + result.status + "）";
}

function traceRowState(index) {
  const key = String(index);
  if (!state.traceOpen[key]) state.traceOpen[key] = false;
  return state.traceOpen[key];
}

function traceResultState(ref) {
  const key = String(ref == null ? "" : ref);
  if (!state.traceResults[key]) {
    state.traceResults[key] = {
      ref: key,
      open: false, loading: false, error: "", text: "",
      offset: 0, totalChars: 0, hasMore: false,
    };
  }
  return state.traceResults[key];
}

function traceTurnSuffix(entry) {
  const turn = entry && entry.turn;
  return turn == null ? "" : "（第 " + turn + " 轮）";
}

// The bounded view arrives as trace_display; when a deployment does not send it
// the page still has to stay usable, so the raw value is bounded here instead
// of dumping a multi-megabyte payload into the DOM.
function boundTraceText(text, limit) {
  const raw = String(text == null ? "" : text);
  if (raw.length <= limit) return raw;
  const keep = Math.max(1, Math.floor((limit - 64) / 2));
  const omitted = raw.length - keep * 2;
  return raw.slice(0, keep) + "\n\n……（此处省略 " + omitted + " 字，共 " + raw.length + " 字）……\n\n" + raw.slice(-keep);
}

function traceTextValue(view, entry, field) {
  const source = view && typeof view === "object" ? view : entry;
  const raw = source && source[field] != null ? source[field] : (entry ? entry[field] : "");
  return raw == null ? "" : String(raw);
}

function formatToolArguments(raw) {
  const text = String(raw == null ? "" : raw);
  if (!text.trim()) return "（没有参数）";
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch (err) {
    return text;
  }
}

function renderHistoryNotice(text, tone) {
  const node = document.createElement("div");
  node.className = "trace-notice" + (tone ? " " + tone : "");
  node.textContent = text;
  const container = el("messages");
  if (container) container.appendChild(node);
  return node;
}

// The raw record contains transport chunks ("message", written as the answer
// streams) next to the committed reply ("assistant"): rendering both would show
// every answer twice, so a chunk is skipped once its turn has a committed row.
function committedAssistantTurns(trace) {
  const turns = new Set();
  trace.forEach((entry) => {
    if (String(entry && entry.type) === "assistant") turns.add(String(entry && entry.turn));
  });
  return turns;
}

function renderHistory(payload) {
  const container = el("messages");
  if (!container) return;
  container.innerHTML = "";
  const trace = Array.isArray(payload.trace) ? payload.trace : [];
  const display = Array.isArray(payload.trace_display) ? payload.trace_display : [];
  const historyMessages = Array.isArray(payload.messages) ? payload.messages : [];

  if (!trace.length) {
    historyMessages.forEach((m) => bubble(m.role === "user" ? "user" : "assistant", m.content));
    if (!historyMessages.length) renderHistoryNotice("这个会话还没有任何内容。", "warn");
    renderHistoryNotice("这个会话没有执行记录：看不到工具调用、结果与错误（可能是更早版本留下的会话）。", "warn");
    return;
  }

  const committed = committedAssistantTurns(trace);
  const seenTexts = new Set();
  let toolRows = 0;
  trace.forEach((entry, index) => {
    const node = buildTraceNode(entry, display[index], index, committed, seenTexts);
    if (!node) return;
    if (node.classList.contains("trace-tool")) toolRows += 1;
    container.appendChild(node);
  });
  if (!toolRows) {
    renderHistoryNotice("这个会话的执行记录里只有对话消息，没有工具调用。", "warn");
  }
  appendUnmirroredMessages(historyMessages, seenTexts);
}

// A display message that never reached the trace (or an older session whose
// record was trimmed) must still be visible: losing it silently is exactly the
// failure this panel exists to prevent.
function appendUnmirroredMessages(historyMessages, seenTexts) {
  const missing = historyMessages.filter(
    (m) => !seenTexts.has(String(m && m.content != null ? m.content : "")),
  );
  if (!missing.length) return;
  renderHistoryNotice("有 " + missing.length + " 条对话内容在原始记录里没有对应条目，下面按顺序补显示：", "warn");
  missing.forEach((m) => bubble(m.role === "user" ? "user" : "assistant", m.content));
}

function buildTraceNode(entry, view, index, committed, seenTexts) {
  const type = String((entry && entry.type) || "");
  const shown = view && typeof view === "object" ? view : entry;
  if (type === "user") {
    const text = traceTextValue(shown, entry, "text");
    seenTexts.add(text);
    return bubble("user", text);
  }
  if (type === "assistant") {
    const text = traceTextValue(shown, entry, "text");
    seenTexts.add(text);
    return bubble("assistant", text);
  }
  if (type === "message") {
    const text = traceTextValue(shown, entry, "text");
    seenTexts.add(text);
    if (committed.has(String(entry && entry.turn))) return null;
    return bubble("assistant", text);
  }
  if (type === "tool_call") return buildToolCallRow(entry, shown, index);
  if (type === "tool_result") return buildToolResultRow(entry, shown, index);
  if (type === "error") return buildErrorRow(entry);
  return null;
}

function buildToolCallRow(entry, shown, index) {
  const row = document.createElement("div");
  row.className = "trace-row trace-tool trace-tool-call";
  const head = document.createElement("button");
  head.type = "button";
  head.className = "trace-head";
  head.textContent = "调用工具 " + ((entry && entry.name) || "（未命名）") + traceTurnSuffix(entry);
  const body = document.createElement("div");
  body.className = "trace-body";
  const pre = document.createElement("pre");
  pre.className = "trace-pre";
  const argumentsText = formatToolArguments(traceTextValue(shown, entry, "arguments"));
  pre.textContent = boundTraceText(argumentsText, TRACE_ARGUMENT_PREVIEW_CHARS);
  body.appendChild(pre);
  body.hidden = !traceRowState(index);
  head.onclick = () => {
    state.traceOpen[String(index)] = !traceRowState(index);
    body.hidden = !traceRowState(index);
  };
  row.append(head, body);
  return row;
}

function buildToolResultRow(entry, shown, index) {
  const row = document.createElement("div");
  row.className = "trace-row trace-tool trace-tool-result";
  // The structured field only. Parsing a ref out of the placeholder text is
  // forbidden by CONTRACTS 6ter.2 and breaks the moment the wording changes.
  const ref = entry && entry.ref != null ? String(entry.ref) : "";
  const truncated = Boolean((entry && entry.truncated) || ref);
  const chars = entry && entry.chars ? Number(entry.chars) : 0;

  const head = document.createElement("button");
  head.type = "button";
  head.className = "trace-head";
  head.textContent = "工具结果 " + ((entry && entry.name) || "（未命名）") + traceTurnSuffix(entry) +
    (truncated ? "（超长结果，完整原文按引用保存）" : "");

  const body = document.createElement("div");
  body.className = "trace-body";
  const preview = document.createElement("pre");
  preview.className = "trace-pre";
  const previewText = traceTextValue(shown, entry, "result");
  preview.textContent = boundTraceText(previewText, TRACE_RESULT_PREVIEW_CHARS) || "（空结果）";
  body.appendChild(preview);

  if (ref) {
    const actions = document.createElement("div");
    actions.className = "trace-actions";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ghost trace-original";
    button.textContent = "查看原文";
    const meta = document.createElement("span");
    meta.className = "trace-meta";
    meta.textContent = "ref " + ref + (chars ? " · " + chars + " 字" : "");
    const box = document.createElement("div");
    box.className = "trace-original-box";
    const stateEntry = traceResultState(ref);
    if (stateEntry.open) {
      button.textContent = "收起原文";
      box.textContent = stateEntry.text ? "" : "（点「查看原文」读取）";
    }
    button.onclick = () => toggleToolResult(ref, button, box);
    actions.append(button, meta);
    body.append(actions, box);
  } else if (truncated) {
    const note = document.createElement("p");
    note.className = "trace-note warn";
    note.textContent = "这条超长结果没有结构化 ref（只有占位提示），无法展开原文；上面是它进入上下文时的文本。";
    body.appendChild(note);
  }

  body.hidden = !traceRowState(index);
  head.onclick = () => {
    state.traceOpen[String(index)] = !traceRowState(index);
    body.hidden = !traceRowState(index);
  };
  row.append(head, body);
  return row;
}

function buildErrorRow(entry) {
  const row = document.createElement("div");
  row.className = "trace-row trace-error trace-tool";
  const phase = entry && entry.phase ? "（阶段：" + entry.phase + "）" : "";
  row.textContent = "错误" + phase + traceTurnSuffix(entry) + "：" + ((entry && entry.message) || "（没有错误信息）");
  return row;
}

async function toggleToolResult(ref, button, box) {
  const entry = traceResultState(ref);
  entry.open = !entry.open;
  if (!entry.open) {
    button.textContent = "查看原文";
    box.innerHTML = "";
    return;
  }
  button.textContent = "收起原文";
  if (entry.text) {
    renderToolResultBox(entry, box);
    return;
  }
  await loadToolResult(ref, box, false);
}

async function loadToolResult(ref, box, append) {
  const entry = traceResultState(ref);
  if (entry.loading) return;
  entry.loading = true;
  box.innerHTML = "";
  const loading = document.createElement("p");
  loading.className = "trace-note";
  loading.textContent = "正在读取原文…";
  box.appendChild(loading);
  const url = sessionEndpoint("toolResult", { session: state.sessionId, ref: ref }) +
    "?offset=" + Number(entry.offset || 0) + "&limit=" + TRACE_RESULT_PAGE;
  const result = await requestJson(url);
  entry.loading = false;
  box.innerHTML = "";
  if (!result.ok) {
    entry.error = describeTraceFailure(result);
    box.appendChild(toolResultNote("原文读取失败：" + entry.error, "error"));
    return;
  }
  const data = result.data || {};
  if (data.ok === false) {
    entry.error = String(data.message || data.error || "受限引用读取被拒绝");
    box.appendChild(toolResultNote("原文读取失败：" + entry.error, "error"));
    return;
  }
  const page = String(data.text == null ? "" : data.text);
  entry.error = "";
  entry.text = append ? entry.text + page : page;
  if (data.next_offset == null) entry.offset = Number(entry.offset || 0) + page.length;
  else entry.offset = Number(data.next_offset);
  if (data.total_chars != null) entry.totalChars = Number(data.total_chars);
  entry.hasMore = Boolean(data.has_more);
  renderToolResultBox(entry, box);
}

function toolResultNote(text, tone) {
  const node = document.createElement("p");
  node.className = "trace-note" + (tone ? " " + tone : "");
  node.textContent = text;
  return node;
}

function renderToolResultBox(entry, box) {
  box.innerHTML = "";
  const pre = document.createElement("pre");
  pre.className = "trace-pre trace-original-text";
  pre.textContent = entry.text || "（原文为空）";
  box.appendChild(pre);
  const shown = entry.text.length;
  const total = entry.totalChars || shown;
  box.appendChild(toolResultNote("已显示 " + shown + " / " + total + " 字" + (entry.hasMore ? "" : "（已到结尾）")));
  if (entry.hasMore) {
    const more = document.createElement("button");
    more.type = "button";
    more.className = "ghost trace-more";
    more.textContent = "继续加载";
    more.onclick = () => {
      more.disabled = true;
      loadToolResult(entry.ref || "", box, true);
    };
    box.appendChild(more);
  }
}

async function openSession(id) {
  state.sessionId = id;
  state.traceOpen = {};
  state.traceResults = {};
  const container = el("messages");
  if (container) container.innerHTML = "";
  const result = await requestJson(sessionEndpoint("detail", { session: id }));
  if (!result.ok) {
    renderHistoryNotice("读取会话失败：" + describeError(result), "error");
    renderHistoryNotice("会话列表仍可用；可以点其它会话，或稍后重试。", "warn");
    loadSessions();
    return;
  }
  renderHistory(result.data || {});
  loadSessions();
}

async function send(message) {
  state.busy = true;
  el("send").disabled = true;
  el("abort").hidden = false;
  bubble("user", message);
  const target = bubble("assistant", "");
  let raw = "";
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ session_id: state.sessionId, message }),
    });
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split("\n\n");
      buffer = frames.pop();
      for (const frame of frames) {
        const line = frame.split("\n").find((l) => l.startsWith("data: "));
        if (!line) continue;
        let event;
        try { event = JSON.parse(line.slice(6)); } catch { continue; }
        handleEvent(event, target, (t) => { raw += t; });
      }
    }
    if (!raw.trim()) target.textContent = "（无输出）";
  } catch (err) {
    target.className = "msg error";
    target.textContent = "请求失败：" + err;
  } finally {
    state.busy = false;
    el("send").disabled = false;
    el("abort").hidden = true;
    loadSessions();
  }
}

// The runtime reports why a habit write did not happen; those reasons must be
// shown to the user rather than swallowed, so they are spelled out here.
const SKILL_REASON_TEXT = {
  user_denied: "你选择了不允许",
  no_confirmer: "当前没有可用的确认入口，未写入",
  permission_mode: "当前权限模式不允许自动写入",
  disabled: "自动学习已关闭",
  plan_mode: "计划模式下不写入",
  no_window: "这一轮没有可学习的反馈",
  no_model_client: "没有可用的模型连接",
  skills_unavailable: "习惯库暂不可用",
};

function describeSkillReason(reason) {
  const raw = String(reason || "");
  if (SKILL_REASON_TEXT[raw]) return SKILL_REASON_TEXT[raw];
  if (raw.startsWith("confirm_error:")) return "确认过程出错（" + raw.slice("confirm_error:".length) + "）";
  if (raw.startsWith("permission_mode:")) return "当前权限模式不允许自动写入（" + raw.slice("permission_mode:".length) + "）";
  return raw || "原因未知";
}

function describeSkillAction(action) {
  if (action === "add") return "（新建）";
  if (action === "merge") return "（合并进已有习惯）";
  return "";
}

function skillLabel(event) {
  return event.skill || "(未知习惯)";
}

function describeSkillSkip(event) {
  const reason = describeSkillReason(event.reason);
  const stage = event.stage ? "（阶段：" + event.stage + "）" : "";
  return reason + stage;
}

function handleEvent(event, target, appendRaw) {
  switch (event.type) {
    case "session":
      state.sessionId = event.session_id;
      break;
    case "text_delta":
      target.textContent += event.text;
      appendRaw(event.text);
      target.scrollIntoView({ block: "end" });
      break;
    case "tool_start":
      chip("<b>调用工具</b> " + escapeHtml(event.name));
      break;
    case "tool_result": {
      // Large results carry structured fields (CONTRACTS 6ter.2): say what
      // happened instead of pretending the placeholder is the whole answer.
      const saved = event.truncated && event.ref
        ? '<span class="trace-note">（结果过长，完整原文按引用保存：ref ' + escapeHtml(String(event.ref)) + '，可在历史会话里展开）</span>'
        : "";
      chip("<b>工具结果</b> " + escapeHtml(event.name) + "<pre>" + escapeHtml(String(event.result).slice(0, 400)) + "</pre>" + saved);
      break;
    }
    case "confirmation": {
      const box = document.createElement("div");
      box.className = "confirm";
      box.innerHTML = "<span class=\"confirm-text\">需要确认：" + escapeHtml(event.summary) + "</span>";
      const yes = document.createElement("button");
      yes.textContent = "允许";
      const no = document.createElement("button");
      no.textContent = "拒绝";
      no.className = "ghost";
      const answer = (approved) => {
        fetch("/api/confirmations/" + encodeURIComponent(event.id), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: event.session_id || state.sessionId, approved }),
        });
        box.remove();
      };
      yes.onclick = () => answer(true);
      no.onclick = () => answer(false);
      box.append(yes, no);
      el("messages").appendChild(box);
      break;
    }
    case "error":
      bubble("error", event.message);
      break;
    case "notice":
    case "warning":
      chip(escapeHtml(event.message));
      break;
    case "skill_candidate_proposed":
      chip("<b>学习到的习惯</b> " + escapeHtml(skillLabel(event)) + describeSkillAction(event.action) + " —— 待确认");
      break;
    case "skill_candidate_applied":
      chip("<b>习惯已更新</b> " + escapeHtml(skillLabel(event)) + describeSkillAction(event.action) + "：" + escapeHtml(event.skill || ""));
      // The habit list may have gained a card or changed version.
      if (state.view === "skills") loadSkills();
      break;
    case "skill_write_denied":
      chip("<b>习惯未写入</b> " + escapeHtml(event.skill || "(未知)") + "：" + escapeHtml(describeSkillReason(event.reason)));
      break;
    case "skill_candidate_failed":
      chip("<b>习惯写入失败</b> " + escapeHtml(event.skill || "(未知)") + "：" + escapeHtml(describeSkillReason(event.reason)));
      break;
    case "skill_candidate_skipped":
      chip("<b>本轮未学习习惯</b>：" + escapeHtml(describeSkillSkip(event)));
      break;
    default:
      break;
  }
}

async function abort() {
  if (!state.sessionId) return;
  await fetch("/api/chat/" + encodeURIComponent(state.sessionId) + "/abort", { method: "POST" });
}

// ------------------------------------------------------------------ records

function actionLink(text, tone, handler) {
  const node = document.createElement("span");
  node.className = "link" + (tone && tone !== "normal" ? " " + tone : "");
  node.textContent = text;
  node.onclick = handler;
  return node;
}

function buildRow(record) {
  const tr = document.createElement("tr");
  tr.dataset.id = record.id;
  if (state.editingId === record.id) {
    tr.className = "editing";
    editCells(record).forEach((cell) => tr.appendChild(cell));
  } else {
    viewCells(record).forEach((cell) => tr.appendChild(cell));
  }
  return tr;
}

function viewCells(record) {
  const title = document.createElement("td");
  title.className = "cell-title";
  title.textContent = record.title || "（无标题）";

  const detail = document.createElement("td");
  detail.className = "cell-detail";
  detail.textContent = record.detail || "—";
  if (state.kind === "memories") {
    const source = supersedeSourceText(record);
    if (source) {
      const note = document.createElement("span");
      note.className = "record-source warn";
      note.textContent = source;
      detail.appendChild(note);
    }
  }

  const time = document.createElement("td");
  time.className = "cell-time";
  const rendered = recordTimeText(record);
  time.textContent = rendered.text;
  if (rendered.title) time.title = rendered.title;

  const status = document.createElement("td");
  const badge = document.createElement("span");
  badge.className = "status-badge" + (isDoneStatus(state.kind, record.status) ? " done" : "");
  badge.textContent = statusLabel(state.kind, record.status);
  status.appendChild(badge);

  const actions = document.createElement("td");
  actions.className = "row-actions";
  actions.append(
    actionLink("编辑", "edit", () => startEdit(record.id)),
    actionLink(toggleTarget(state.kind, record.status).label, "toggle", () => toggleStatus(record)),
    actionLink("删除", "danger", () => removeRecord(record)),
  );

  return [title, detail, time, status, actions];
}

function editCells(record) {
  const titleInput = document.createElement("input");
  titleInput.className = "cell-input";
  titleInput.value = record.title || "";
  titleInput.placeholder = "标题（必填）";
  const titleCell = document.createElement("td");
  titleCell.appendChild(titleInput);

  const detailInput = document.createElement("input");
  detailInput.className = "cell-input";
  detailInput.value = record.detail || "";
  detailInput.placeholder = "备注（可选）";
  const detailCell = document.createElement("td");
  detailCell.appendChild(detailInput);

  const dueInput = document.createElement("input");
  dueInput.type = "datetime-local";
  dueInput.className = "cell-input due";
  dueInput.value = toDatetimeLocalValue(record);
  const dueCell = document.createElement("td");
  dueCell.appendChild(dueInput);

  const statusCell = document.createElement("td");
  const badge = document.createElement("span");
  badge.className = "status-badge" + (isDoneStatus(state.kind, record.status) ? " done" : "");
  badge.textContent = statusLabel(state.kind, record.status);
  statusCell.appendChild(badge);

  const actionCell = document.createElement("td");
  actionCell.className = "row-actions";
  let saving = false;
  const save = actionLink("保存", "edit", async () => {
    if (saving) return;
    saving = true;
    await saveEdit(record, { title: titleInput.value, detail: detailInput.value, due: dueInput.value });
    saving = false;
  });
  const cancel = actionLink("取消", "cancel", () => {
    state.editingId = null;
    showRecordsNotice("已取消编辑。", "warn");
    loadRecords();
  });
  actionCell.append(save, cancel);

  return [titleCell, detailCell, dueCell, statusCell, actionCell];
}

function startEdit(recordId) {
  state.editingId = recordId;
  showRecordsNotice("编辑中：改完点「保存」，或点「取消」返回浏览态。", "warn");
  loadRecords();
}

async function saveEdit(record, draft) {
  const title = String(draft.title || "").trim();
  if (!title) {
    showRecordsNotice("标题不能为空，未保存。", "error");
    return;
  }
  const payload = { title: title, detail: String(draft.detail || "").trim() };
  // Same conversion as the create form: the local wall-clock input becomes ISO.
  payload.due_at = draft.due ? new Date(draft.due).toISOString() : null;
  const result = await requestJson("/api/records/" + state.kind + "/" + encodeURIComponent(record.id), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!result.ok) {
    // Stay in edit mode so nothing the user typed is lost.
    showRecordsNotice("保存失败：" + describeError(result), "error");
    return;
  }
  rememberOperation(result.data, "update", result.data.title || title);
  state.editingId = null;
  showRecordsNotice("已保存「" + title + "」。", "ok");
  loadRecords();
}

async function toggleStatus(record) {
  const target = toggleTarget(state.kind, record.status);
  const result = await requestJson("/api/records/" + state.kind + "/" + encodeURIComponent(record.id), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status: target.status }),
  });
  if (!result.ok) {
    showRecordsNotice("状态更新失败：" + describeError(result), "error");
    return;
  }
  rememberOperation(result.data, "status", record.title);
  showRecordsNotice("「" + (record.title || "未命名") + "」已" + target.label + "。", "ok");
  loadRecords();
}

async function removeRecord(record) {
  const result = await requestJson("/api/records/" + state.kind + "/" + encodeURIComponent(record.id), { method: "DELETE" });
  if (!result.ok) {
    showRecordsNotice("删除失败：" + describeError(result), "error");
    return;
  }
  rememberOperation(result.data, "delete", record.title);
  if (state.editingId === record.id) state.editingId = null;
  showRecordsNotice("已删除「" + (record.title || "未命名") + "」，可点「撤销上一步」恢复。", "ok");
  loadRecords();
}

async function loadRecords() {
  const table = el("records-table");
  if (!table) return;
  const head = table.querySelector("thead");
  const body = table.querySelector("tbody");
  head.innerHTML = "<tr><th>标题</th><th>备注</th><th>时间（本地）</th><th>状态</th><th>操作</th></tr>";
  body.innerHTML = "";
  const result = await requestJson("/api/records/" + state.kind);
  if (!result.ok) {
    body.innerHTML = '<tr><td colspan="5" class="empty">读取失败：请确认后端服务是否正常。</td></tr>';
    showRecordsNotice("读取记录失败：" + describeError(result), "error");
    return;
  }
  const records = (result.data && result.data.records) || [];
  if (!records.length) {
    body.innerHTML = '<tr><td colspan="5" class="empty">暂无记录：可在上方表单新建，或直接在对话中让助理创建。</td></tr>';
    return;
  }
  records.forEach((record) => body.appendChild(buildRow(record)));
}

// -------------------------------------------------------------- skills (habits)

// The habit page drives the endpoints fixed by the runtime contract
// (docs/specs/CONTRACTS.md 4.5). Every path lives in this one table, so a wrong
// path is a one-line fix and a static test failure instead of a silent 404.
const SKILL_ENDPOINTS = {
  list: "/api/skills",
  detail: "/api/skills/{name}",
  update: "/api/skills/{name}",
  disable: "/api/skills/{name}/disable",
  enable: "/api/skills/{name}/enable",
  versions: "/api/skills/{name}/versions",
  versionBody: "/api/skills/{name}/versions/{version}",
  restore: "/api/skills/{name}/versions/{version}/restore",
};

// A disabled habit cannot be rolled back or edited: the backend answers 400
// skill_disabled, so the page has to say what to do instead of failing quietly.
const SKILL_DISABLED_HINT = "请先恢复该技能再回退版本";

// Skill names are free text (they are often Chinese), so every placeholder is
// percent-encoded before it goes into the URL.
function skillEndpoint(name, params) {
  const template = SKILL_ENDPOINTS[name];
  if (!template) return SKILL_ENDPOINTS.list;
  const values = params || {};
  return Object.keys(values).reduce(function (url, key) {
    return url.replace("{" + key + "}", encodeURIComponent(String(values[key])));
  }, template);
}

function skillEnabled(skill) {
  return Boolean(skill) && skill.enabled !== false;
}

function skillVersionState(name) {
  const key = String(name == null ? "" : name);
  if (!state.skillVersions[key]) {
    state.skillVersions[key] = { open: false, rows: [], error: "", loading: false };
  }
  return state.skillVersions[key];
}

// The current rule body, the provenance section and the edit draft all live per
// habit: the list is re-rendered on every action, so open/editing state has to
// survive a render.
function skillDetailState(name) {
  const key = String(name == null ? "" : name);
  if (!state.skillDetail[key]) {
    state.skillDetail[key] = {
      open: false, loading: false, error: "",
      body: "", notes: "", description: "", whenToUse: "", version: "",
    };
  }
  return state.skillDetail[key];
}

function skillEditState(name) {
  const key = String(name == null ? "" : name);
  if (!state.skillEdit[key]) state.skillEdit[key] = false;
  return state.skillEdit[key];
}

function skillVersionBodyState(name, version) {
  const key = String(name == null ? "" : name) + "@" + String(version == null ? "" : version);
  if (!state.skillVersionBody[key]) {
    state.skillVersionBody[key] = { open: false, loading: false, error: "", body: "", notes: "" };
  }
  return state.skillVersionBody[key];
}

function showSkillsNotice(message, tone) {
  const node = el("skills-notice");
  if (!node) return;
  node.textContent = message || "";
  node.className = "skills-notice" + (message && tone ? " " + tone : "");
}

// Every failure prints the HTTP status together with the backend detail; the
// disabled-skill case gets the actionable hint the contract asks for.
function describeSkillFailure(result) {
  if (!result.status) return String(result.error || "未知错误");
  const detail = String(result.error || "");
  if (detail.indexOf("disabled") >= 0 || detail.indexOf(SKILL_DISABLED_HINT) >= 0) {
    return SKILL_DISABLED_HINT + "（HTTP " + result.status + "：" + detail + "）";
  }
  return detail + "（HTTP " + result.status + "）";
}

function skillButton(label, className, handler) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.textContent = label;
  button.onclick = handler;
  return button;
}

function skillStateBadge(skill) {
  const badge = document.createElement("span");
  const enabled = skillEnabled(skill);
  badge.className = "status-badge skill-state " + (enabled ? "enabled" : "disabled");
  badge.textContent = enabled ? "启用中" : "已停用";
  return badge;
}

function renderSkillsMessage(text) {
  const container = el("skills-list");
  if (!container) return;
  container.innerHTML = "";
  const node = document.createElement("div");
  node.className = "empty";
  node.textContent = text;
  container.appendChild(node);
}

async function loadSkills() {
  const container = el("skills-list");
  if (!container) return;
  const result = await requestJson(skillEndpoint("list"));
  if (!result.ok) {
    renderSkillsMessage("读取失败：请确认后端服务是否正常。");
    showSkillsNotice("读取习惯列表失败：" + describeSkillFailure(result), "error");
    return;
  }
  const skills = (result.data && result.data.skills) || [];
  state.skills = skills;
  container.innerHTML = "";
  if (!skills.length) {
    renderSkillsMessage("还没有学到任何习惯。在对话中明确纠正助理的做法后，它会作为习惯出现在这里，可以查看、编辑、停用或恢复。");
    return;
  }
  skills.forEach((skill) => container.appendChild(buildSkillCard(skill)));
}

function buildSkillCard(skill) {
  const enabled = skillEnabled(skill);
  const card = document.createElement("div");
  card.className = "skill-card" + (enabled ? "" : " disabled");
  card.dataset.skill = String(skill.name == null ? "" : skill.name);
  if (skill.path) card.title = "技能文件：" + skill.path;

  const head = document.createElement("div");
  head.className = "skill-head";

  const title = document.createElement("div");
  title.className = "skill-title";
  const name = document.createElement("span");
  name.className = "skill-name";
  name.textContent = skill.name || "（未命名习惯）";
  title.append(name, skillStateBadge(skill));
  head.appendChild(title);

  const entry = skillVersionState(skill.name);
  const detail = skillDetailState(skill.name);
  const editing = skillEditState(skill.name);
  const actions = document.createElement("div");
  actions.className = "skill-actions";
  actions.append(
    skillButton(detail.open ? "收起规则" : "查看规则", "ghost skill-view", () => toggleSkillDetail(skill)),
    skillButton(editing ? "取消编辑" : "编辑规则", "ghost skill-edit", () => (editing ? cancelSkillEdit(skill) : startSkillEdit(skill))),
    skillButton(enabled ? "停用" : "恢复", "ghost skill-toggle", () => toggleSkill(skill)),
    skillButton(entry.open ? "收起版本" : "查看版本", "ghost", () => toggleSkillVersions(skill)),
  );
  head.appendChild(actions);
  card.appendChild(head);

  const meta = document.createElement("div");
  meta.className = "skill-meta";
  const updated = formatLocalMoment(skill.updated_at);
  meta.textContent = "版本 " + (skill.version || "—") +
    " · 来源 " + (skill.source || "project") +
    " · 更新 " + (updated || "—");
  card.appendChild(meta);

  const description = document.createElement("p");
  description.className = "skill-desc";
  description.textContent = skill.description || "（这个习惯还没有描述）";
  card.appendChild(description);

  if (detail.open) card.appendChild(buildSkillDetail(skill, detail, editing));
  if (entry.open) card.appendChild(buildSkillVersions(skill, entry));
  return card;
}

// The habit page used to show only name/description/version: the rules the
// assistant actually follows were invisible. This panel is the read view plus
// the editor (one of the two, never both).
function buildSkillDetail(skill, detail, editing) {
  const panel = document.createElement("div");
  panel.className = "skill-detail";
  if (detail.loading && !detail.body) {
    panel.textContent = "正在读取规则…";
    return panel;
  }
  if (detail.error) {
    panel.textContent = "规则读取失败：" + detail.error;
    return panel;
  }
  if (editing) return buildSkillEditor(skill, detail, panel);

  const hint = document.createElement("p");
  hint.className = "skill-hint";
  hint.textContent = "当前规则（版本 " + (detail.version || "—") + "）。点「编辑规则」可以改这些规则并保存为新版本，之后的新对话按新规则执行。";
  panel.appendChild(hint);

  const body = document.createElement("pre");
  body.className = "skill-body";
  body.textContent = detail.body || "（这个习惯还没有规则正文）";
  panel.appendChild(body);

  if (detail.notes) {
    const notesTitle = document.createElement("p");
    notesTitle.className = "skill-hint";
    notesTitle.textContent = "演化溯源（只读，记录每次学习与编辑的理由，不是规则本身）";
    const notes = document.createElement("pre");
    notes.className = "skill-notes";
    notes.textContent = detail.notes;
    panel.append(notesTitle, notes);
  }
  return panel;
}

function buildSkillEditor(skill, detail, panel) {
  const form = document.createElement("div");
  form.className = "skill-editor";

  const descLabel = document.createElement("label");
  descLabel.className = "skill-field";
  descLabel.textContent = "用途描述（必填）";
  const descInput = document.createElement("input");
  descInput.className = "skill-input skill-input-desc";
  descInput.value = detail.description || "";
  descLabel.appendChild(descInput);

  const whenLabel = document.createElement("label");
  whenLabel.className = "skill-field";
  whenLabel.textContent = "何时使用";
  const whenInput = document.createElement("input");
  whenInput.className = "skill-input skill-input-when";
  whenInput.value = detail.whenToUse || "";
  whenLabel.appendChild(whenInput);

  const rulesLabel = document.createElement("label");
  rulesLabel.className = "skill-field";
  rulesLabel.textContent = "规则正文（必填，保存时整体替换）";
  const rulesInput = document.createElement("textarea");
  rulesInput.className = "skill-textarea skill-input-rules";
  rulesInput.rows = 8;
  rulesInput.value = detail.body || "";
  rulesLabel.appendChild(rulesInput);

  const hint = document.createElement("p");
  hint.className = "skill-hint";
  hint.textContent = "保存复用已有版本机制：当前正文先存成一个历史版本，版本号 +1，随时可以回退；需要先恢复技能才能编辑已停用的习惯。";

  let saving = false;
  const save = skillButton("保存并生成新版本", "skill-save", async () => {
    if (saving) return;
    saving = true;
    await saveSkillEdit(skill, {
      description: descInput.value,
      whenToUse: whenInput.value,
      instructions: rulesInput.value,
    });
    saving = false;
  });
  const cancel = skillButton("取消", "ghost", () => cancelSkillEdit(skill));
  const actions = document.createElement("div");
  actions.className = "skill-editor-actions";
  actions.append(save, cancel);

  form.append(descLabel, whenLabel, rulesLabel, hint, actions);
  panel.appendChild(form);
  return panel;
}

async function toggleSkillDetail(skill) {
  const entry = skillDetailState(skill.name);
  entry.open = !entry.open;
  if (entry.open && !entry.body) await fetchSkillDetail(skill);
  loadSkills();
}

async function fetchSkillDetail(skill) {
  const entry = skillDetailState(skill.name);
  entry.loading = true;
  const result = await requestJson(skillEndpoint("detail", { name: skill.name }));
  entry.loading = false;
  if (!result.ok) {
    entry.error = describeSkillFailure(result);
    showSkillsNotice("读取「" + skill.name + "」的规则失败：" + entry.error, "error");
    return;
  }
  const data = result.data || {};
  entry.error = "";
  entry.body = String(data.body || "");
  entry.notes = String(data.notes || "");
  entry.description = String(data.description || "");
  entry.whenToUse = String(data.when_to_use || "");
  entry.version = String(data.version || "");
}

async function startSkillEdit(skill) {
  if (!skillEnabled(skill)) {
    showSkillsNotice("「" + skill.name + "」已停用：" + SKILL_DISABLED_HINT + "。", "warn");
    return;
  }
  const entry = skillDetailState(skill.name);
  if (!entry.body) await fetchSkillDetail(skill);
  if (entry.error) {
    showSkillsNotice("规则没读出来，无法编辑：" + entry.error, "error");
    return;
  }
  entry.open = true;
  state.skillEdit[String(skill.name)] = true;
  showSkillsNotice("编辑「" + skill.name + "」：改完点「保存并生成新版本」，或点「取消」。", "warn");
  loadSkills();
}

function cancelSkillEdit(skill) {
  state.skillEdit[String(skill.name)] = false;
  showSkillsNotice("已取消编辑，「" + skill.name + "」的内容没有变化。", "warn");
  loadSkills();
}

async function saveSkillEdit(skill, draft) {
  const description = String(draft.description || "").trim();
  const instructions = String(draft.instructions || "").trim();
  if (!description) {
    showSkillsNotice("用途描述不能为空，未保存。", "error");
    return;
  }
  if (!instructions) {
    showSkillsNotice("规则正文不能为空，未保存。", "error");
    return;
  }
  const payload = { description: description, instructions: instructions };
  const when = String(draft.whenToUse || "").trim();
  if (when) payload.when_to_use = when;

  const result = await requestJson(skillEndpoint("update", { name: skill.name }), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!result.ok) {
    showSkillsNotice("保存「" + skill.name + "」失败：" + describeSkillFailure(result), "error");
    return;
  }
  const data = result.data || {};
  state.skillEdit[String(skill.name)] = false;
  const entry = skillDetailState(skill.name);
  entry.open = true;
  if (data.changed === false) {
    showSkillsNotice("「" + skill.name + "」的内容没有变化，未生成新版本。", "warn");
  } else {
    showSkillsNotice(
      "已保存「" + skill.name + "」：版本 " + (data.previous_version || "—") + " → " +
      (data.version || "—") + "；之后的新对话按新规则执行，可以回退到旧版本。", "ok",
    );
  }
  await fetchSkillDetail(skill);
  loadSkills();
}

function buildSkillVersions(skill, entry) {
  const panel = document.createElement("div");
  panel.className = "skill-versions";
  if (entry.loading && !entry.rows.length) {
    panel.textContent = "正在读取版本…";
    return panel;
  }
  if (entry.error) {
    panel.textContent = "版本读取失败：" + entry.error;
    return panel;
  }
  if (!skillEnabled(skill)) {
    const hint = document.createElement("p");
    hint.className = "skill-hint";
    hint.textContent = "该习惯已停用：" + SKILL_DISABLED_HINT + "。";
    panel.appendChild(hint);
  }
  if (!entry.rows.length) {
    const none = document.createElement("p");
    none.className = "skill-hint";
    none.textContent = "还没有历史版本：习惯在被修改或回退过之后才会留下版本记录。";
    panel.appendChild(none);
    return panel;
  }
  const head = document.createElement("div");
  head.className = "skill-versions-head";
  head.textContent = "共 " + entry.rows.length + " 个版本（新的在上；回退会再生成一个新版本）";
  panel.appendChild(head);
  entry.rows.forEach((version) => panel.appendChild(buildSkillVersionRow(skill, version)));
  return panel;
}

function buildSkillVersionRow(skill, version) {
  const row = document.createElement("div");
  row.className = "skill-version" + (version.current ? " current" : "");

  const label = document.createElement("span");
  label.className = "skill-version-label";
  label.textContent = version.version || "—";

  const time = document.createElement("span");
  time.className = "skill-version-time";
  time.textContent = formatLocalMoment(version.updated_at) || version.updated_at || "—";

  row.append(label, time);
  if (version.current) {
    const badge = document.createElement("span");
    badge.className = "status-badge current-badge";
    badge.textContent = "当前版本";
    row.appendChild(badge);
  }

  const actions = document.createElement("span");
  actions.className = "skill-version-actions";
  const pending = state.skillConfirm;
  if (pending && pending.name === skill.name && pending.version === version.version) {
    // Rolling a habit back changes what every later conversation does, so it
    // takes one more explicit click than the enable/disable toggle.
    const ask = document.createElement("span");
    ask.className = "skill-confirm";
    ask.textContent = "确认回退到 " + version.version + "？之后的新对话都会按这个版本执行。";
    actions.append(
      ask,
      skillButton("确认回退", "skill-confirm-yes", confirmSkillRestore),
      skillButton("取消", "ghost", cancelSkillRestore),
    );
  } else if (!version.current) {
    const link = document.createElement("span");
    link.className = "link";
    link.textContent = "回退到此版本";
    link.onclick = () => requestSkillRestore(skill, version.version);
    actions.appendChild(link);
  }
  const bodyToggle = document.createElement("span");
  bodyToggle.className = "link version-body-link";
  bodyToggle.textContent = skillVersionBodyState(skill.name, version.version).open ? "收起正文" : "查看正文";
  bodyToggle.onclick = () => toggleSkillVersionBody(skill, version.version);
  actions.appendChild(bodyToggle);
  row.appendChild(actions);

  if (skillVersionBodyState(skill.name, version.version).open) {
    row.appendChild(buildSkillVersionBody(skill, version.version));
  }
  return row;
}

function buildSkillVersionBody(skill, version) {
  const entry = skillVersionBodyState(skill.name, version);
  const box = document.createElement("div");
  box.className = "skill-version-body";
  if (entry.loading && !entry.body) {
    box.textContent = "正在读取版本正文…";
    return box;
  }
  if (entry.error) {
    box.textContent = "版本正文读取失败：" + entry.error;
    return box;
  }
  const body = document.createElement("pre");
  body.className = "skill-body";
  body.textContent = entry.body || "（这个版本没有规则正文）";
  box.appendChild(body);
  return box;
}

async function toggleSkillVersionBody(skill, version) {
  const entry = skillVersionBodyState(skill.name, version);
  entry.open = !entry.open;
  if (entry.open && !entry.body) {
    entry.loading = true;
    const result = await requestJson(skillEndpoint("versionBody", { name: skill.name, version: version }));
    entry.loading = false;
    if (!result.ok) {
      entry.error = describeSkillFailure(result);
      showSkillsNotice("读取「" + skill.name + "」版本 " + version + " 的正文失败：" + entry.error, "error");
    } else {
      const data = result.data || {};
      entry.error = "";
      entry.body = String(data.body || "");
      entry.notes = String(data.notes || "");
    }
  }
  loadSkills();
}

async function toggleSkill(skill) {
  const enabled = skillEnabled(skill);
  // Disabling archives the habit so it stops reaching new conversations;
  // enabling moves it back. Both are idempotent on the backend.
  const action = enabled ? "disable" : "enable";
  const label = enabled ? "停用" : "恢复";
  const result = await requestJson(skillEndpoint(action, { name: skill.name }), { method: "POST" });
  if (!result.ok) {
    showSkillsNotice(label + "「" + skill.name + "」失败：" + describeSkillFailure(result), "error");
    return;
  }
  const changed = !(result.data && result.data.changed === false);
  showSkillsNotice("已" + label + "习惯「" + skill.name + "」" + (changed ? "" : "（本来就是该状态）") +
    "：后续新对话按新的状态执行。", "ok");
  loadSkills();
}

async function toggleSkillVersions(skill) {
  const entry = skillVersionState(skill.name);
  entry.open = !entry.open;
  if (entry.open) await fetchSkillVersions(skill);
  loadSkills();
}

async function fetchSkillVersions(skill) {
  const entry = skillVersionState(skill.name);
  entry.loading = true;
  const result = await requestJson(skillEndpoint("versions", { name: skill.name }));
  entry.loading = false;
  if (!result.ok) {
    entry.rows = [];
    entry.error = describeSkillFailure(result);
    showSkillsNotice("读取「" + skill.name + "」的版本失败：" + entry.error, "error");
    return;
  }
  entry.error = "";
  entry.rows = (result.data && result.data.versions) || [];
}

function requestSkillRestore(skill, version) {
  if (!skillEnabled(skill)) {
    // Refused by the backend with 400 skill_disabled; explain before sending a
    // request that is known to fail.
    showSkillsNotice("「" + skill.name + "」已停用：" + SKILL_DISABLED_HINT + "。", "warn");
    return;
  }
  state.skillConfirm = { name: skill.name, version: version };
  showSkillsNotice("回退会把「" + skill.name + "」的内容换成版本 " + version +
    "，之后的新对话都按这个版本执行。请再点一次「确认回退」。", "warn");
  loadSkills();
}

function cancelSkillRestore() {
  state.skillConfirm = null;
  showSkillsNotice("已取消回退，习惯内容没有变化。", "warn");
  loadSkills();
}

async function confirmSkillRestore() {
  const pending = state.skillConfirm;
  if (!pending) return;
  const skill = (state.skills || []).find((item) => item.name === pending.name);
  state.skillConfirm = null;
  const result = await requestJson(
    skillEndpoint("restore", { name: pending.name, version: pending.version }),
    { method: "POST" },
  );
  if (!result.ok) {
    showSkillsNotice("回退失败：" + describeSkillFailure(result), "error");
    loadSkills();
    return;
  }
  const data = result.data || {};
  const entry = skillVersionState(pending.name);
  entry.rows = [];
  entry.error = "";
  const detail = skillDetailState(pending.name);
  detail.body = "";
  detail.error = "";
  if (skill) await fetchSkillVersions(skill);
  showSkillsNotice("已把「" + pending.name + "」回退到版本 " + (data.restored_from || pending.version) +
    "，并记为版本 " + (data.version || "—") + "。", "ok");
  loadSkills();
}

async function loadConfig() {
  const cfg = await fetch("/api/config").then((r) => r.json());
  el("cfg-model").value = cfg.model;
  el("cfg-base").value = cfg.api_base || "";
  el("cfg-turns").value = cfg.max_turns || "";
  el("settings-status").textContent = cfg.configured ? "当前已配置（密钥 " + (cfg.api_key_hint || "已设置") + "）" : "当前未配置";
}

ensureRecordsChrome();

el("composer").addEventListener("submit", (e) => {
  e.preventDefault();
  const value = el("input").value.trim();
  if (!value || state.busy) return;
  el("input").value = "";
  send(value);
});
el("input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); el("composer").requestSubmit(); }
});
el("abort").onclick = abort;
el("skills-reload").onclick = () => { showSkillsNotice("正在刷新…", "warn"); loadSkills(); };
el("new-session").onclick = () => { state.sessionId = null; el("messages").innerHTML = ""; loadSessions(); };
document.querySelectorAll(".nav-item").forEach((b) => (b.onclick = () => render(b.dataset.view)));
el("record-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const title = el("record-title").value.trim();
  if (!title) {
    showRecordsNotice("标题不能为空，未新建。", "error");
    return;
  }
  const payload = { title: title, detail: el("record-detail").value };
  if (el("record-due").value) payload.due_at = new Date(el("record-due").value).toISOString();
  const result = await requestJson("/api/records/" + state.kind, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
  if (!result.ok) {
    showRecordsNotice("新建失败：" + describeError(result), "error");
    return;
  }
  rememberOperation(result.data, "create", title);
  el("record-title").value = ""; el("record-detail").value = ""; el("record-due").value = "";
  showRecordsNotice("已新建「" + title + "」。", "ok");
  loadRecords();
});
el("settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  await fetch("/api/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model: el("cfg-model").value,
      api_base: el("cfg-base").value,
      api_key: el("cfg-key").value,
      max_turns: el("cfg-turns").value ? Number(el("cfg-turns").value) : null,
    }),
  });
  el("cfg-key").value = "";
  el("settings-status").textContent = "已保存";
  refreshHealth();
});

refreshHealth();
loadSessions();
