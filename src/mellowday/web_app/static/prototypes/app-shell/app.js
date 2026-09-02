// THROWAWAY PROTOTYPE — reads existing conversation GET endpoints; all mutations stay in memory.
const variants = {
  A: { name: "长期归巢", question: "固定导航轨能否承载长期使用与会话切换？" },
  B: { name: "横向工作台", question: "顶部工作台能否把更多宽度还给真实长对话？" },
  C: { name: "专注舞台", question: "弱化全局导航后，陪伴感与可达性能否并存？" },
};

const themes = {
  sky: { name: "晴空", swatch: "linear-gradient(145deg,#acd9ff,#eaf6ff)", motif: "sky-sparkle.svg" },
  sakura: { name: "樱粉", swatch: "linear-gradient(145deg,#ffb5c4,#fff0f3)", motif: "sakura-petal.svg" },
  mint: { name: "薄荷", swatch: "linear-gradient(145deg,#a9ddc5,#edf8f1)", motif: "mint-leaf.svg" },
  night: { name: "夜色", swatch: "linear-gradient(145deg,#071b3d,#214c83)", motif: "night-star.svg" },
  minimal: { name: "简约", swatch: "linear-gradient(145deg,#f5f6f7,#dfe7ef)", motif: null },
};

const secondaryRoutes = {
  life: [
    { path: "/life/tasks", label: "任务", description: "查看准备完成的事项与截止时间。" },
    { path: "/life/reminders", label: "提醒", description: "查看已经安排的通知时间。" },
    { path: "/life/calendar", label: "日历", description: "查看有明确开始与结束时间的安排。" },
    { path: "/life/notes", label: "笔记", description: "查看主动保存的自由文本。" },
  ],
  settings: [
    { path: "/settings/appearance", label: "外观", description: "调整当前客户端的主题与显示偏好。" },
    { path: "/settings/persona", label: "Persona", description: "管理 Assistant 的身份与聊天表达边界。" },
    { path: "/settings/proactive-chat", label: "主动聊天", description: "查看安静时段、冷却与每日上限。" },
    { path: "/settings/providers", label: "模型提供方", description: "查看本地配置的可替换推理提供方。" },
    { path: "/settings/capabilities", label: "能力", description: "查看当前可用的工具与 Skill。" },
    { path: "/settings/history", label: "对话历史", description: "中性地检查已保留的会话。" },
    { path: "/settings/audit", label: "操作记录", description: "查看动作、确认与撤销信息。" },
    { path: "/settings/diagnostics", label: "诊断", description: "查看本地运行状态与故障信息。" },
  ],
};

const primaryRouteLabels = {
  conversation: "对话",
  today: "今日",
  life: "生活",
  memory: "记忆",
  settings: "设置",
};

const densityFixture = [
  { role: "assistant", content: "下午好。你刚才说今天有点散，我在这里。我们可以先把脑子里的东西倒出来，不急着立刻变成任务。" },
  { role: "user", content: "嗯。下午要改完项目说明，还答应给家里打电话，晚上想出去走走。事情都不大，但挤在一起就有点烦。" },
  { role: "assistant", content: "听起来不是事情太难，而是它们一起占着注意力。先只看今天：\n\n- 项目说明：需要一段完整、不被打断的时间\n- 给家里打电话：十几分钟也能完成\n- 晚上散步：不是待办，是给今天留一点余地\n\n你想先梳理项目说明，还是先把时间排开？" },
  { role: "user", content: "先看项目说明吧。我卡在新版 AppShell 为什么要调整，写出来总像是在罗列功能。" },
  { role: "assistant", content: "可以把重点从“多了哪些入口”换成“为什么需要一个稳定的壳”。例如：\n\n```text\nAppShell 负责持续存在的产品上下文：\n导航、当前会话、主题与实时连接。\n具体页面只负责自己的内容。\n```\n\n这样读者先理解边界，再看布局选择。" },
  { role: "user", content: "这句方向对。还要说明对话永远是主入口，但 Today、Life、Memory 和 Settings 又不能像临时抽屉。" },
  { role: "assistant", content: "那可以再补一层：对话是日常归处，其他区域是稳定、可返回的产品区域。它们共享外壳，但不共享语气——Persona 只出现在聊天内容里，管理界面保持中性。" },
  { role: "user", content: "好。帮我记一个临时版本就行，不要真的写入笔记。" },
  { role: "assistant", content: "可以。我只把它留在当前预览里：\n\n“AppShell 让对话保持日常归处，同时给 Today、Life、Memory 与 Settings 稳定的位置；共享的是导航和运行上下文，不是同一种表达方式。”" },
  { role: "user", content: "这样清楚多了。电话放到五点半，散步不定时间。" },
  { role: "assistant", content: "收到——在这个结构预览里，我只按你的说法呈现，不会创建提醒或日程。你可以先用接下来这一段完整时间改说明，五点半再停下来打电话。" },
  { role: "user", content: "最后一个问题：如果窗口变窄，聊天内容不要变成满屏气泡，也别让装饰挡住输入框。" },
  { role: "assistant", content: "明白。窄窗口仍保留清晰的说话者与段落节奏；大角落装饰会降低存在感，小纹样直接隐藏，输入区和主题弹层始终在可操作层。" },
];

const state = {
  variant: "A",
  theme: "sky",
  conversations: [],
  currentConversationId: "density-preview",
  messages: [],
  source: "读取中",
  popoverOpen: false,
  drawerOpen: false,
  minimalHue: 211,
  minimalLightness: 97,
  route: "/conversation",
  railCollapsed: false,
  conversationSourceNote: "正在读取本地会话…",
};

const root = document.documentElement;
const body = document.body;
const appShell = document.querySelector("#app-shell");
const primaryRail = document.querySelector(".primary-rail");
const primaryNavItems = [...document.querySelectorAll("[data-route]")];
const railCollapse = document.querySelector("#rail-collapse");
const sectionKicker = document.querySelector("#section-kicker");
const pageTitle = document.querySelector("#page-title");
const conversationWorkspace = document.querySelector("#conversation-workspace");
const managementPage = document.querySelector("#management-page");
const secondaryNav = document.querySelector("#secondary-nav");
const managementContent = document.querySelector("#management-content");
const messagesElement = document.querySelector("#messages");
const messageAnnouncer = document.querySelector("#message-announcer");
const recentElement = document.querySelector("#recent-conversations");
const drawerRecentElement = document.querySelector("#drawer-conversations");
const conversationCount = document.querySelector("#conversation-count");
const sourceNote = document.querySelector("#source-note");
const densityBadge = document.querySelector("#density-badge");
const title = document.querySelector("#transcript-title");
const composer = document.querySelector("#composer");
const input = document.querySelector("#message-input");
const interactionStatus = document.querySelector("#interaction-status");
const themeTrigger = document.querySelector("#theme-trigger");
const themePopover = document.querySelector("#theme-popover");
const themeClose = document.querySelector("#theme-close");
const themeOptions = document.querySelector("#theme-options");
const minimalControls = document.querySelector("#minimal-controls");
const fixedThemeNote = document.querySelector("#fixed-theme-note");
const accentInput = document.querySelector("#accent-input");
const brightnessInput = document.querySelector("#brightness-input");
const activeThemeName = document.querySelector("#active-theme-name");
const variantLabel = document.querySelector("#variant-label");
const prototypeState = document.querySelector("#prototype-state");
const memoryToast = document.querySelector("#memory-toast");
const drawer = document.querySelector("#conversation-drawer");
const drawerLayer = document.querySelector("#conversation-drawer-layer");
const drawerBackdrop = document.querySelector(".drawer-backdrop");
const drawerTrigger = document.querySelector("#conversation-drawer-trigger");
const drawerClose = document.querySelector("#conversation-drawer-close");
const prototypeSwitcher = document.querySelector(".prototype-switcher");
const wideViewport = window.matchMedia("(min-width: 881px)");
let toastTimer;

function normalizeRoute(rawHash = window.location.hash) {
  const requested = rawHash.replace(/^#/, "") || "/conversation";
  if (requested === "/life") return "/life/tasks";
  if (requested === "/settings") return "/settings/appearance";
  if (["/conversation", "/today", "/memory"].includes(requested)) return requested;
  if (secondaryRoutes.life.some((item) => item.path === requested)) return requested;
  if (secondaryRoutes.settings.some((item) => item.path === requested)) return requested;
  return "/conversation";
}

function routeArea(route = state.route) {
  return route.split("/").filter(Boolean)[0] || "conversation";
}

function setConversationSourceNote(content) {
  state.conversationSourceNote = content;
  if (routeArea() === "conversation") sourceNote.textContent = content;
}

function appendTextElement(parent, tag, className, content) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = content;
  parent.append(element);
  return element;
}

function renderSecondaryNavigation(area) {
  secondaryNav.replaceChildren();
  const routes = secondaryRoutes[area];
  secondaryNav.hidden = !routes;
  if (!routes) return;
  secondaryNav.setAttribute("aria-label", `${primaryRouteLabels[area]}二级导航`);
  routes.forEach((route) => {
    const link = document.createElement("a");
    link.href = `#${route.path}`;
    link.textContent = route.label;
    link.className = "secondary-nav-item";
    if (route.path === state.route) link.setAttribute("aria-current", "page");
    secondaryNav.append(link);
  });
}

function renderManagementContent(area) {
  managementContent.replaceChildren();
  const currentRoute = secondaryRoutes[area]?.find((item) => item.path === state.route);
  const summary = document.createElement("div");
  summary.className = "management-summary";
  appendTextElement(summary, "span", "readonly-badge", "只读占位 · 路由验证");
  appendTextElement(
    summary,
    "p",
    "management-description",
    currentRoute?.description || (
      area === "today"
        ? "由当前 Life Record 派生今天的概览，不创建另一份记录。"
        : "在这里中性地检查、查找和管理长期 Memory。"
    ),
  );
  managementContent.append(summary);

  const grid = document.createElement("div");
  grid.className = "placeholder-grid";
  const cards = area === "today"
    ? [["接下来", "17:30 · 给家里打电话"], ["今天的任务", "项目说明 · 继续整理"], ["给自己留白", "晚间散步 · 不设提醒"]]
    : area === "memory"
      ? [["偏好", "不喜欢把随口聊天自动转成任务"], ["重要事项", "正在整理新版 AppShell 说明"], ["管理边界", "Memory 与 Life Record 分开保存"]]
      : [["当前页面", currentRoute?.label || primaryRouteLabels[area]], ["状态", "可信的只读内容占位"], ["验证重点", "路由、焦点、溢出与返回"]];
  cards.forEach(([heading, content]) => {
    const card = document.createElement("article");
    appendTextElement(card, "h2", "", heading);
    appendTextElement(card, "p", "", content);
    grid.append(card);
  });
  managementContent.append(grid);

  if (state.route === "/settings/appearance") {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "appearance-preview-button";
    button.textContent = "打开全局外观面板";
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      openThemePopover();
    });
    managementContent.append(button);
  }
}

function renderRoute({ focusHeading = false } = {}) {
  const area = routeArea();
  body.dataset.area = area;
  primaryNavItems.forEach((item) => {
    const isCurrent = item.dataset.route === area;
    item.classList.toggle("is-active", isCurrent);
    if (isCurrent) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });

  const isConversation = area === "conversation";
  conversationWorkspace.hidden = !isConversation;
  managementPage.hidden = isConversation;
  drawerTrigger.hidden = !isConversation;
  renderSecondaryNavigation(area);

  if (isConversation) {
    sectionKicker.textContent = "下午好";
    pageTitle.textContent = "我在这里，陪你梳理今天。";
    sourceNote.textContent = state.conversationSourceNote;
  } else {
    const currentRoute = secondaryRoutes[area]?.find((item) => item.path === state.route);
    sectionKicker.textContent = primaryRouteLabels[area];
    pageTitle.textContent = currentRoute?.label || (area === "today" ? "今天" : "记忆管理");
    sourceNote.textContent = area === "today"
      ? "Daily Review 只派生视图；源 Life Record 仍是事实来源。"
      : area === "memory"
        ? "Memory 独立于对话历史和 Life Record。"
        : "此处只验证页面结构，不实现业务编辑器。";
    renderManagementContent(area);
  }

  if (focusHeading) window.requestAnimationFrame(() => pageTitle.focus());
}

function applyRailState() {
  const isWide = wideViewport.matches;
  const isDock = state.variant === "A" && isWide && state.railCollapsed;
  root.dataset.rail = isWide ? (isDock ? "dock" : "full") : "narrow";
  railCollapse.setAttribute("aria-expanded", String(!isDock));
  railCollapse.title = isDock ? "展开导航" : "收起导航";
  railCollapse.querySelector("span[aria-hidden]").textContent = isDock ? "»" : "«";
  railCollapse.querySelector("span:last-child").textContent = isDock ? "展开导航" : "收起导航";
}

function toggleRail() {
  state.railCollapsed = !state.railCollapsed;
  applyRailState();
  showToast(state.railCollapsed ? "已进入专注状态；宽屏导航收为图标 Dock。" : "已恢复完整导航 Rail。");
}

function normalizeQueryState() {
  const params = new URLSearchParams(window.location.search);
  const requestedVariant = (params.get("variant") || "A").toUpperCase();
  const requestedTheme = params.get("theme") || "sky";
  state.variant = variants[requestedVariant] ? requestedVariant : "A";
  state.theme = themes[requestedTheme] ? requestedTheme : "sky";
}

function replaceQuery(updates) {
  const url = new URL(window.location.href);
  Object.entries(updates).forEach(([key, value]) => url.searchParams.set(key, value));
  window.history.replaceState(null, "", url);
}

function applyVariant(nextVariant, updateUrl = true) {
  state.variant = variants[nextVariant] ? nextVariant : "A";
  root.dataset.variant = state.variant;
  variantLabel.textContent = `${state.variant} · ${variants[state.variant].name}`;
  document.title = `Mellowday AppShell ${state.variant} · Throwaway prototype`;
  if (updateUrl) replaceQuery({ variant: state.variant });
  closeDrawer({ restoreFocus: false });
  applyRailState();
  updatePrototypeState();
}

function cycleVariant(direction) {
  const keys = Object.keys(variants);
  const currentIndex = keys.indexOf(state.variant);
  const nextIndex = (currentIndex + direction + keys.length) % keys.length;
  applyVariant(keys[nextIndex]);
}

function renderThemeOptions() {
  themeOptions.replaceChildren();
  Object.entries(themes).forEach(([id, theme]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "theme-option";
    button.dataset.theme = id;
    button.setAttribute("aria-pressed", String(id === state.theme));
    button.setAttribute("role", "listitem");

    const swatch = document.createElement("span");
    swatch.className = "theme-swatch";
    swatch.style.setProperty("--swatch", theme.swatch);
    swatch.setAttribute("aria-hidden", "true");
    const label = document.createElement("span");
    label.textContent = theme.name;
    button.append(swatch, label);
    button.addEventListener("click", () => applyTheme(id));
    themeOptions.append(button);
  });
}

function renderThemeArt() {
  const artRoot = document.querySelector("#theme-art-root");
  const emblemSlot = document.querySelector("#theme-emblem-slot");
  artRoot.replaceChildren();
  emblemSlot.replaceChildren();
  if (state.theme === "minimal") return;

  const art = document.createElement("div");
  art.className = "theme-art";
  art.setAttribute("aria-hidden", "true");
  const corner = document.createElement("img");
  corner.className = "theme-art__corner";
  corner.alt = "";
  corner.decoding = "async";
  corner.src = `./assets/${state.theme}-corner.webp`;
  art.append(corner);
  for (let index = 0; index < 5; index += 1) {
    const motif = document.createElement("i");
    motif.className = "theme-art__motif";
    motif.style.setProperty("--motif-url", `url(\"./assets/${themes[state.theme].motif}\")`);
    art.append(motif);
  }
  artRoot.append(art);

  const emblem = document.createElement("img");
  emblem.alt = "";
  emblem.decoding = "async";
  emblem.src = `./assets/${state.theme}-emblem.webp`;
  emblemSlot.append(emblem);
}

function applyTheme(nextTheme, updateUrl = true) {
  state.theme = themes[nextTheme] ? nextTheme : "sky";
  root.dataset.theme = state.theme;
  activeThemeName.textContent = themes[state.theme].name;
  document.querySelector('meta[name="theme-color"]').content =
    state.theme === "night" ? "#06152f" : "#eef7ff";
  minimalControls.hidden = state.theme !== "minimal";
  fixedThemeNote.hidden = state.theme === "minimal";
  root.style.setProperty("--minimal-hue", state.minimalHue);
  root.style.setProperty("--minimal-lightness", `${state.minimalLightness}%`);
  if (updateUrl) replaceQuery({ theme: state.theme });
  renderThemeOptions();
  renderThemeArt();
  updatePrototypeState();
}

function openThemePopover() {
  closeDrawer({ restoreFocus: false });
  state.popoverOpen = true;
  themePopover.hidden = false;
  themeTrigger.setAttribute("aria-expanded", "true");
  themeClose.focus();
}

function closeThemePopover({ restoreFocus = true } = {}) {
  if (!state.popoverOpen) return;
  state.popoverOpen = false;
  themePopover.hidden = true;
  themeTrigger.setAttribute("aria-expanded", "false");
  if (restoreFocus) themeTrigger.focus();
}

function openDrawer() {
  if (drawerTrigger.hidden || window.getComputedStyle(drawerTrigger).display === "none") return;
  closeThemePopover({ restoreFocus: false });
  state.drawerOpen = true;
  drawerLayer.hidden = false;
  appShell.inert = true;
  prototypeSwitcher.inert = true;
  drawerTrigger.setAttribute("aria-expanded", "true");
  drawerClose.focus();
}

function closeDrawer({ restoreFocus = true } = {}) {
  if (!state.drawerOpen) return;
  state.drawerOpen = false;
  drawerLayer.hidden = true;
  appShell.inert = false;
  prototypeSwitcher.inert = false;
  drawerTrigger.setAttribute("aria-expanded", "false");
  if (restoreFocus) drawerTrigger.focus();
}

function trapDrawerFocus(event) {
  if (!state.drawerOpen || event.key !== "Tab") return;
  const focusable = [...drawer.querySelectorAll("button, a[href], input, textarea, [tabindex]:not([tabindex='-1'])")]
    .filter((element) => !element.disabled && !element.hidden);
  if (focusable.length === 0) {
    event.preventDefault();
    drawer.focus();
    return;
  }
  const first = focusable[0];
  const last = focusable.at(-1);
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function updatePrototypeState() {
  prototypeState.textContent = `${themes[state.theme].name} · ${state.source}`;
}

function showToast(content) {
  window.clearTimeout(toastTimer);
  memoryToast.textContent = content;
  memoryToast.hidden = false;
  toastTimer = window.setTimeout(() => { memoryToast.hidden = true; }, 2400);
}

function friendlyConversationName(id) {
  if (id === "main") return "日常对话";
  return id.replaceAll("-", " ").replaceAll("_", " ");
}

function formatConversationTime(timestamp) {
  if (!timestamp) return "本地会话";
  try {
    return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })
      .format(new Date(timestamp * 1000));
  } catch {
    return "本地会话";
  }
}

function createRecentButton(summary) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "recent-item";
  button.classList.toggle("is-current", summary.conversation_id === state.currentConversationId);
  button.dataset.conversationId = summary.conversation_id;
  const name = document.createElement("strong");
  name.textContent = summary.conversation_id === "density-preview"
    ? "密度验证样本"
    : friendlyConversationName(summary.conversation_id);
  const meta = document.createElement("span");
  meta.textContent = summary.conversation_id === "density-preview"
    ? `${densityFixture.length} 条 · 内存`
    : `${summary.message_count} 条 · ${formatConversationTime(summary.updated_at)}`;
  button.append(name, meta);
  button.addEventListener("click", () => selectConversation(summary));
  return button;
}

function renderRecentConversations() {
  const densitySummary = { conversation_id: "density-preview", message_count: densityFixture.length, updated_at: 0 };
  const summaries = [densitySummary, ...state.conversations.slice(0, 8)];
  recentElement.replaceChildren(...summaries.map(createRecentButton));
  drawerRecentElement.replaceChildren(...summaries.map(createRecentButton));
  conversationCount.textContent = String(state.conversations.length);
}

function createTextBlocks(content) {
  const fragment = document.createDocumentFragment();
  const segments = content.split(/```/);
  segments.forEach((segment, segmentIndex) => {
    if (!segment) return;
    if (segmentIndex % 2 === 1) {
      const pre = document.createElement("pre");
      pre.textContent = segment.replace(/^\w*\n/, "").trim();
      fragment.append(pre);
      return;
    }
    const paragraphs = segment.trim().split(/\n\s*\n/);
    paragraphs.forEach((paragraph) => {
      const lines = paragraph.split("\n");
      if (lines.every((line) => line.trim().startsWith("- "))) {
        const list = document.createElement("ul");
        lines.forEach((line) => {
          const item = document.createElement("li");
          item.textContent = line.trim().slice(2);
          list.append(item);
        });
        fragment.append(list);
      } else {
        const element = document.createElement("p");
        element.textContent = paragraph.trim();
        fragment.append(element);
      }
    });
  });
  return fragment;
}

function createMessage(message, index) {
  if (message.role === "separator") {
    const separator = document.createElement("li");
    separator.className = "message-separator";
    separator.textContent = message.content;
    return separator;
  }

  const normalizedRole = message.role === "user" ? "user" : "assistant";
  const item = document.createElement("li");
  item.className = `message message-${normalizedRole}`;
  item.dataset.role = normalizedRole;

  const author = document.createElement("div");
  author.className = "message-author";
  const name = document.createElement("span");
  name.textContent = normalizedRole === "user" ? "你" : "Mellowday";
  const time = document.createElement("time");
  const minutes = 8 + index * 3;
  time.textContent = `下午 ${2 + Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}`;
  author.append(name, time);

  const body = document.createElement("div");
  body.className = "message-body";
  body.append(createTextBlocks(String(message.content || "")));
  item.append(author, body);
  return item;
}

function renderMessages({ scrollToEnd = false } = {}) {
  messagesElement.replaceChildren(...state.messages.map(createMessage));
  messagesElement.setAttribute("aria-busy", "false");
  if (scrollToEnd) messagesElement.scrollTop = messagesElement.scrollHeight;
}

function supplementForDensity(realMessages) {
  if (realMessages.length >= 10) return realMessages;
  const needed = Math.max(0, 10 - realMessages.length);
  if (realMessages.length === 0) return densityFixture;
  return [
    ...realMessages,
    { role: "separator", content: "以下为内存中的密度验证片段" },
    ...densityFixture.slice(0, needed),
  ];
}

async function selectConversation(summary) {
  closeDrawer({ restoreFocus: false });
  state.currentConversationId = summary.conversation_id;
  messagesElement.setAttribute("aria-busy", "true");
  if (summary.conversation_id === "density-preview") {
    state.messages = densityFixture.map((message) => ({ ...message }));
    state.source = "密度样本 · 内存";
    title.textContent = "今天，慢慢来";
    densityBadge.textContent = "完整密度样本";
    setConversationSourceNote("当前展示结构验证夹具；不会写入 Conversation History。");
    renderMessages();
    renderRecentConversations();
    updatePrototypeState();
    return;
  }

  try {
    const response = await fetch(`/api/conversations/${encodeURIComponent(summary.conversation_id)}`, { method: "GET" });
    if (!response.ok) throw new Error(`GET conversation failed: ${response.status}`);
    const payload = await response.json();
    const realMessages = Array.isArray(payload.messages) ? payload.messages : [];
    state.messages = supplementForDensity(realMessages);
    state.source = realMessages.length >= 10 ? "真实本地会话" : "真实会话 + 密度样本";
    title.textContent = friendlyConversationName(summary.conversation_id);
    densityBadge.textContent = realMessages.length >= 10 ? `${realMessages.length} 条真实消息` : `${realMessages.length} 条真实消息 · 已补足密度`;
    setConversationSourceNote(realMessages.length >= 10
      ? "通过现有 Conversation History GET 接口读取。"
      : "真实消息保留在前，密度片段仅存在于本次预览。");
  } catch (error) {
    state.messages = densityFixture.map((message) => ({ ...message }));
    state.source = "读取失败 · 密度样本";
    title.textContent = "今天，慢慢来";
    densityBadge.textContent = "本地回退样本";
    setConversationSourceNote("Conversation History 暂不可读，已使用内存夹具。");
  }
  renderMessages();
  renderRecentConversations();
  updatePrototypeState();
}

async function loadConversationIndex() {
  try {
    const response = await fetch("/api/conversations", { method: "GET" });
    if (!response.ok) throw new Error(`GET index failed: ${response.status}`);
    const payload = await response.json();
    state.conversations = Array.isArray(payload.conversations) ? payload.conversations : [];
    renderRecentConversations();
    if (state.conversations.length === 0) {
      await selectConversation({ conversation_id: "density-preview", message_count: densityFixture.length });
      state.source = "无已存会话 · 密度样本";
      setConversationSourceNote("现有接口中没有会话；展示内存中的真实密度夹具。");
      updatePrototypeState();
      return;
    }
    const initial = state.conversations.find((item) => item.conversation_id === "main") || state.conversations[0];
    await selectConversation(initial);
  } catch (error) {
    state.conversations = [];
    state.currentConversationId = "density-preview";
    state.messages = densityFixture.map((message) => ({ ...message }));
    state.source = "API 不可读 · 密度样本";
    setConversationSourceNote("Conversation History 暂不可读；展示内存夹具，操作仍可验证。");
    densityBadge.textContent = "本地回退样本";
    renderRecentConversations();
    renderMessages();
    updatePrototypeState();
  }
}

composer.addEventListener("submit", (event) => {
  event.preventDefault();
  const content = input.value.trim();
  if (!content) return;
  state.messages.push({ role: "user", content });
  input.value = "";
  input.style.height = "auto";
  renderMessages({ scrollToEnd: true });
  messageAnnouncer.textContent = "已在当前预览中加入你的消息。";
  interactionStatus.textContent = "消息只加入当前页面内存；未调用 POST 接口。";
  window.setTimeout(() => {
    state.messages.push({ role: "assistant", content: "我收到这条预览消息了。它只留在当前页面内存里，刷新后不会保存。" });
    renderMessages({ scrollToEnd: true });
    messageAnnouncer.textContent = "Mellowday 已在当前预览中回复。";
  }, 260);
});

input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 108)}px`;
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    composer.requestSubmit();
  }
});

document.querySelectorAll("[data-memory-action]").forEach((button) => {
  button.addEventListener("click", () => showToast(button.dataset.memoryAction));
});

document.querySelector("#previous-variant").addEventListener("click", () => cycleVariant(-1));
document.querySelector("#next-variant").addEventListener("click", () => cycleVariant(1));
railCollapse.addEventListener("click", toggleRail);
themeTrigger.addEventListener("click", () => state.popoverOpen ? closeThemePopover() : openThemePopover());
themeClose.addEventListener("click", () => closeThemePopover());
drawerTrigger.addEventListener("click", () => state.drawerOpen ? closeDrawer({ restoreFocus: true }) : openDrawer());
drawerClose.addEventListener("click", () => closeDrawer({ restoreFocus: true }));
drawerBackdrop.addEventListener("click", () => closeDrawer({ restoreFocus: true }));

accentInput.addEventListener("input", () => {
  const hex = accentInput.value.slice(1);
  const red = parseInt(hex.slice(0, 2), 16) / 255;
  const green = parseInt(hex.slice(2, 4), 16) / 255;
  const blue = parseInt(hex.slice(4, 6), 16) / 255;
  const max = Math.max(red, green, blue);
  const min = Math.min(red, green, blue);
  let hue = 0;
  if (max !== min) {
    if (max === red) hue = 60 * (((green - blue) / (max - min)) % 6);
    else if (max === green) hue = 60 * ((blue - red) / (max - min) + 2);
    else hue = 60 * ((red - green) / (max - min) + 4);
  }
  state.minimalHue = Math.round((hue + 360) % 360);
  root.style.setProperty("--minimal-hue", state.minimalHue);
});

brightnessInput.addEventListener("input", () => {
  state.minimalLightness = Number(brightnessInput.value);
  root.style.setProperty("--minimal-lightness", `${state.minimalLightness}%`);
});

document.addEventListener("click", (event) => {
  if (state.popoverOpen && !themePopover.contains(event.target) && !themeTrigger.contains(event.target)) {
    closeThemePopover({ restoreFocus: true });
  }
});

document.addEventListener("keydown", (event) => {
  trapDrawerFocus(event);
  const target = event.target;
  const isInteractive = Boolean(target.closest("button, a, input, textarea, [contenteditable='true']"));
  if (event.key === "Escape") {
    if (state.popoverOpen) closeThemePopover();
    else if (state.drawerOpen) closeDrawer({ restoreFocus: true });
    return;
  }
  if (!event.isComposing && !isInteractive && (event.key === "ArrowLeft" || event.key === "ArrowRight")) {
    event.preventDefault();
    cycleVariant(event.key === "ArrowLeft" ? -1 : 1);
  }
});

window.addEventListener("hashchange", () => {
  const normalized = normalizeRoute();
  if (`#${normalized}` !== window.location.hash) {
    const url = new URL(window.location.href);
    url.hash = normalized;
    window.history.replaceState(null, "", url);
  }
  state.route = normalized;
  closeDrawer({ restoreFocus: false });
  closeThemePopover({ restoreFocus: false });
  renderRoute({ focusHeading: true });
});

wideViewport.addEventListener("change", () => {
  applyRailState();
  window.requestAnimationFrame(() => {
    if (state.drawerOpen && window.getComputedStyle(drawerTrigger).display === "none") {
      closeDrawer({ restoreFocus: false });
    }
  });
});

normalizeQueryState();
state.route = normalizeRoute();
if (`#${state.route}` !== window.location.hash) {
  const url = new URL(window.location.href);
  url.hash = state.route;
  window.history.replaceState(null, "", url);
}
applyVariant(state.variant, false);
applyTheme(state.theme, false);
renderRoute();
loadConversationIndex();
