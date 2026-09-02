# Mellowday UI 最终有限原型验证交接

## 目的

使用 `prototype` 流程完成生产 UI spec 前的最后一次结构验证。原型只回答一个问题：已经确认的 A+C AppShell 在 Rail 专注状态、二级导航、响应式边界、弹层/抽屉焦点和主题装饰共同存在时，是否仍满足布局与可访问性合同。

完成标准是产出逐项带证据的 verdict handoff；原型代码本身不是生产组件。

## 开始前读取

按顺序完整读取：

1. 根目录 `AGENTS.md`、`CONTEXT.md`、`docs/product-direction.md`。
2. `docs/adr/0008-make-desktop-application-the-primary-entry.md`。
3. `docs/adr/0010-use-react-typescript-and-vite-for-the-web-app.md`。
4. `docs/adr/0011-use-long-term-home-app-shell.md`。
5. `docs/adr/0012-define-first-version-conversation-experience.md`。
6. `docs/prototype/mellowday-ui-prototype-verdict-handoff.md`。
7. `src/mellowday/web_app/static/prototypes/app-shell/README.md` 及该原型现有 HTML、CSS、JavaScript。

ADR 是已确认决策的唯一来源；原型 verdict 提供证据，不得覆盖 ADR。

## 修改边界

仅在以下位置进行 throwaway 原型工作：

- `src/mellowday/web_app/static/prototypes/app-shell/`
- `docs/prototype/screenshots/app-shell-final/`
- 最终 verdict：`docs/prototype/mellowday-ui-final-validation-verdict-handoff.md`

保留仓库中所有既有 dirty changes。`chatbot/` 保持只读。生产 Web App、Python API、数据库、package-data、React/Vite 生产结构和 Desktop Shell 均不在本任务修改范围内。不要晋升素材，不要创建真实写操作，不要把原型组件复制到生产目录。

原型可以读取现有 Conversation History，用 fixture 或页面内存模拟导航状态；不得发送消息、修改 Memory 或 Life Record，也不得调用其他写接口。继续使用候选素材的原型副本，不修改 `docs/ui-concepts/theme-assets/`。

## 必须验证的结构

### Rail 与专注状态

- 宽屏默认显示完整 `244px` Rail。
- 提供显式控制，将 Rail 收为约 `82px` 图标 Dock，再恢复完整 Rail。
- 收起后五个产品区域仍有可访问名称、选中状态和工具提示。
- 宽屏收起状态在原型会话内被记忆；进入 `≤880px` 顶部导航后不显示 Dock，恢复宽屏时还原原状态。
- 专注状态不得改变正文宽度合同、Composer 可用性或最近会话入口。

### 二级导航

- Life 展示横向子导航，并默认进入 Tasks。
- Settings 展示横向子导航，并默认进入 Appearance。
- 一级导航始终只承载 Conversation、Today、Life、Memory Management、Settings。
- 子页面只需可信的只读占位内容；验证路由语义、焦点、溢出和返回，不实现业务编辑器。

### 弹层与抽屉

- Appearance 使用带名称的非模态 popover/dialog；验证 Escape、外部点击、焦点返回和窄窗近全宽布局。
- `≤880px` 的最近会话使用模态 drawer/dialog；背景不可交互，焦点限制在抽屉内，Escape 和关闭按钮均返回触发点。
- 输入框聚焦和输入法组合状态不得被导航或原型快捷操作劫持。

## 视口与主题矩阵

至少检查以下 CSS 视口；每一项记录截图、控制台错误和可操作性结论：

- `1440×900`
- `1200×780`
- `881×780`
- `880×780`
- `521×860`
- `520×640`

在 DPR 1 和 DPR 2 下覆盖关键矩阵，不把 DPR 模拟写成真实 Windows 缩放结论。真实 Electron/Windows 100%、125%、150%、200% 缩放保持为 Desktop Shell 阶段的验收项，因为本仓库当前尚无 Desktop Shell 实现。

至少覆盖：

- Sky：完整 Rail、图标 Dock、两个响应式边界、Appearance popover。
- Night：正文、焦点和装饰裁切。
- Minimal：窄窗、背景亮度边界、无装饰 DOM、无装饰素材请求。

四个固定主题继续使用各自匹配的 emblem、corner 和 motif 原型副本。检查高 DPR 下装饰是否出现明显模糊、遮挡、溢出或错误裁切；如果候选素材不足，只在 verdict 中记录，不在本任务重新制作或晋升资产。

## 可访问性合同

- 文本、控件、状态和可见焦点达到 WCAG 2.2 AA 对比度。
- 键盘可以完成一级导航、二级导航、Rail/Dock 切换、Appearance 操作和 drawer 开关。
- 阅读顺序保持为标题栏、产品导航、主内容、Composer。
- 新消息 live region 不得在初次装载或切换布局时重复朗读整个 transcript。
- 装饰层保持 `aria-hidden` 和 `pointer-events: none`，不进入布局、选择或焦点顺序。
- `prefers-reduced-motion` 下不得依赖动画传达状态。

## Verdict handoff

创建 `docs/prototype/mellowday-ui-final-validation-verdict-handoff.md`，逐项记录：

1. 每个结构、视口、主题和可访问性合同的 Pass/Fail。
2. 对应截图文件名及复现步骤。
3. 浏览器控制台、网络请求和 DPR 检查结果。
4. 哪些结论可以直接进入生产 UI spec。
5. 哪些失败揭示了新的产品决策；这些必须返回主设计会话，不得由原型自行决定。
6. 明确声明真实 Windows 高 DPI 验收仍待 Desktop Shell，以及原型文件没有晋升为生产代码。

只有所有已定义项目都有结论、失败项都有可复现证据时，原型阶段才完成。完成后回到主流程执行 `to-spec`；不要在原型会话开始生产实现、创建实现票或修改后端。
