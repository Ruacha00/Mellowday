# Mellowday AppShell 原型结论交接

## 交接目的

供主设计会话把已验证的 AppShell 方向写入后续 UI spec。不要在该会话直接把原型代码晋升为生产实现；原型是结构证据，不是生产组件。

## 原型回答的问题

在保留真实 Conversation History 读取、真实聊天内容密度、五主题氛围层和窄窗口约束的情况下，哪一种 AppShell 能同时做到：

- 让 Conversation Surface 继续成为日常归处；
- 让 Today、Life、Memory Management、Settings 成为稳定且可返回的产品区域；
- 不让全局导航、最近会话、主题入口或装饰层挤压聊天阅读与输入；
- 在桌面窗口和窄窗口中保持同一产品结构。

产品定义与边界不要从本文复述，直接读取：

- `CONTEXT.md`
- `docs/product-direction.md`
- `docs/adr/0002-separate-core-assistant-and-web.md`
- `docs/adr/0003-persona-applies-only-to-chat.md`
- `docs/adr/0004-memory-is-not-a-life-record.md`
- `docs/adr/0008-make-desktop-application-the-primary-entry.md`
- `docs/adr/0010-use-react-typescript-and-vite-for-the-web-app.md`

## 原型与证据位置

- 原型说明：`src/mellowday/web_app/static/prototypes/app-shell/README.md`
- 页面：`src/mellowday/web_app/static/prototypes/app-shell/index.html`
- 行为与只读数据加载：`src/mellowday/web_app/static/prototypes/app-shell/app.js`
- 三种结构与尺寸：`src/mellowday/web_app/static/prototypes/app-shell/styles.css`
- 截图：`docs/prototype/screenshots/app-shell/`
- 上一阶段原型任务边界：`docs/prototype/mellowday-ui-prototype-handoff.md`
- 主题参考与素材规则：`docs/ui-concepts/theme-assets/README.md`、`docs/ui-concepts/theme-assets/VIBE-CODING.md`
- 五张视觉参考：`docs/ui-concepts/themes/`

运行现有 Web App 后访问：

`http://127.0.0.1:8000/static/prototypes/app-shell/index.html?variant=A`

可用 `variant=A|B|C`；主题可用 `theme=sky|sakura|mint|night|minimal`。

## A / B / C 的主要差异

### A — 长期归巢

- 桌面：固定左侧产品导航轨，品牌、五个产品区域和最近会话同处稳定位置。
- 对话：中间正文列保持克制宽度，主题入口位于对话页头。
- 窄窗：导航轨收成顶部单行产品导航，最近会话进入抽屉。
- 主要价值：最清楚地表达产品信息架构；长期使用时定位成本最低。
- 主要代价：桌面永久占用一列，需要给真正的“专注阅读”留可选收起方式。

### B — 横向工作台

- 桌面：产品导航和最近会话都进入顶部工作台；正文旁保留会话级上下文列。
- 对话：可利用更宽画布，但顶部与右侧同时承载信息。
- 窄窗：最终仍需收敛成与 A 类似的顶部导航，因此桌面特有结构没有形成足够收益。
- 主要价值：适合高信息密度、频繁切换会话的工作模式。
- 主要代价：全局导航、最近会话和右侧上下文与聊天争夺注意力及宽度；不适合作为陪伴型产品的默认入口。

### C — 专注舞台

- 桌面：左侧仅保留图标 dock，对话位于有边界的专注舞台；最近会话改为按需抽屉。
- 对话：正文列最窄、段落节奏最好，User turn 采用轻量块面强调。
- 窄窗：阅读和输入仍稳定，但全局产品区域的语义标签弱化。
- 主要价值：陪伴感、阅读感和主题氛围最好。
- 主要代价：Today、Life、Memory、Settings 的可发现性不足，不宜作为默认 AppShell。

## 最终选择

以 **A「长期归巢」作为生产 AppShell 的结构基线**，吸收 C 的以下部分：

- 对话正文宽度和纵向节奏；
- User turn 的轻量块面强调；
- 最近会话按需抽屉作为窄窗行为；
- 将 rail 收起后的状态视为可选“专注模式”，而不是默认导航结构。

不采用 B 作为基线，也不引入常驻右侧日程栏。B 的工作台和会话级上下文列可以作为未来高密度场景的参考，但不应进入第一版默认结构。

选择原因：A 是唯一在桌面端明确表达五个长期产品区域、同时在窄窗中不破坏聊天连续性的方案；C 的正文处理能补足 A 的专注感，而不会牺牲全局可发现性。

## 已验证并应进入 spec 的布局常量

以下是原型中已经过 `1440×900`、`1200×780` 和 `520×860` 浏览器验证的常量；它们是 spec 候选，不代表已完成生产实现。

### 共享桌面结构

- 桌面应用标题栏：`48px`。
- 主题 popover：最大宽度 `400px`，视口两侧至少保留 `17px`。
- 最近会话抽屉：最大宽度 `340px`，两侧至少保留 `20px`。
- 原型主题角落图：`clamp(500px, 68vw, 980px)`；不参与布局和交互。

### A 基线

- 左侧 rail：`244px`。
- 对话 workspace：最大 `820px`，桌面两侧总共至少保留 `60px`。
- Desktop message 元信息列：`88px`。

### B 参考结构

- 顶部工作台：`76px`（位于 `48px` 标题栏下）。
- Workspace：最大 `1020px`。
- 会话级上下文列：`220px`；与正文间距 `28px`。

### C 可借鉴结构

- 图标 dock 所在列：`82px`。
- 专注舞台外边距：上/下 `18px`，右 `20px`。
- 对话 workspace：最大 `720px`。

### 响应式断点

- `≤880px`：三种方案统一转为单列壳；标题栏 `42px`，顶部产品导航 `58px`；workspace 宽度 `calc(100% - 24px)`；最近会话使用抽屉；大角落装饰降到约 `20%` 透明度，小 motif 隐藏。
- `≤520px`：消息元信息与正文改为单列；User turn 最大约 `88%` 宽度；发送按钮只保留图标；主题 popover 使用近全宽布局。
- 生产 spec 需要明确 Desktop Shell 的最小窗口宽度；当前原型只验证到 `520px`，没有为更窄窗口作产品承诺。

## 已验证行为

- `GET /api/conversations` 与会话详情读取保留；原型所有发送、导航和主题操作只使用页面内存，没有 POST。
- 五个主题均通过切换验证。
- `minimal` 直接加载时没有装饰 DOM，也没有装饰素材请求。
- theme popover 支持 Escape、外部点击关闭和焦点返回。
- 输入框聚焦时，左右方向键不会触发原型 variant 切换。
- 装饰层为 `aria-hidden`、`pointer-events: none`，不影响阅读、布局、选择和焦点顺序。
- `prefers-reduced-motion`、桌面/窄窗和浏览器控制台检查通过。
- 关键截图：`A-sky-desktop.png`、`A-sky-narrow.png`、`A-sky-theme-popover.png`、`B-sky-desktop.png`、`C-sky-desktop.png`、`C-night-desktop.png`、`B-minimal-narrow.png`，均位于 `docs/prototype/screenshots/app-shell/`。

## Branch / commit 状态

- 当前 branch：`main`。
- 当前 HEAD：`e66dca56ac268dfec41b9bd6b8e7f84b01551b0c`（`Merge pull request #30 from Ruacha00/issue-1-finalize`）。
- **原型尚无 branch 或 commit**：原型文件、素材副本和截图目前都是未跟踪文件；不要把上面的 HEAD 当作原型提交。
- 本次 handoff 没有创建 branch、commit 或 GitHub Issue。
- 若要按 prototype 流程归档，应在后续明确授权后创建 throwaway branch，提交原型与截图，并从生产 UI spec/implementation issue 链接该 branch；不要将三变体和原型切换器直接合并到 main。

仓库中存在原型之外的既有 dirty changes。后续会话必须继续保留它们，不能用 reset/checkout 清理。

## 仍需进入 UI spec 的开放问题

1. **Rail 的收起语义**：A 是否默认常驻；收起状态是否需要记忆；收起后采用 C 的图标 dock，还是完全隐藏并用一个恢复按钮。
2. **最小窗口尺寸**：Desktop Shell 的最小宽高，以及 `520px` 以下是否属于支持范围。
3. **中间宽度导航**：`521–880px` 是否始终显示五个文字标签；中文、英文和系统缩放下如何避免拥挤。
4. **会话列表行为**：最近会话数量、排序、标题生成、未读/主动消息标记、滚动与搜索；这些不能由原型夹具决定。
5. **对话正文规范**：User turn 是否正式采用 C 的块面；长段落、Markdown、代码、工具结果、失败、确认和 proactive message 的统一内容样式。
6. **Composer 边界**：附件、表情、发送键盘规则、草稿生命周期和多行最大高度；原型中的按钮与内存草稿不是产品决定。
7. **主题偏好**：按 ADR 0010 落实 local storage 的 schema、默认主题、Minimal 的可调范围、迁移与恢复默认行为。
8. **素材晋升**：从 `docs/ui-concepts/theme-assets/` 选择哪些 WebP/SVG 进入正式静态资源、按主题懒加载，并更新 package data；原型副本不是已晋升资产。
9. **Desktop title bar 所有权**：Electron 标题栏、拖拽区、窗口控制和 Web App AppShell 的边界；原型标题栏只用于判断整体比例。
10. **导航和页面生命周期**：React/Vite 中 AppShell、页面 outlet、SSE/实时连接、主题管理器与各页面数据加载的拥有者；页面切换不得重建全局实时连接。
11. **可访问性验收**：最终对比度、主题 popover/dialog 语义、窄窗抽屉焦点陷阱、键盘快捷键和屏幕阅读顺序。
12. **视觉 token 固化**：A+C 合并后的间距、圆角、阴影、字体栈和五主题 token 需要在生产组件中重新定义，不能直接复制原型 CSS。

## 建议下一会话使用的 skills

- `doc-coauthoring`：把上述决策和开放问题整理成可评审的 UI spec。
- `frontend-design`：把 A 的信息架构与 C 的对话节奏收敛成一套明确视觉系统。
- `domain-modeling`：检查 spec 中 Conversation Surface、Today、Life、Memory Management、Settings 的术语边界。
- `gitnexus-plan`：生产实现前形成基于当前 React/Vite ADR 与现有 Web App 调用图的实施计划。
- `gitnexus-impact-analysis`：修改现有页面加载、消息追加或静态服务符号之前执行 upstream 影响分析。
- `stop-that-shit`：spec 阶段使用 `review`，实施阶段确认后使用 `change`，避免把原型任务扩展成后端或领域迁移。

## 建议主设计会话的第一步

先以本 handoff 和 `docs/prototype/screenshots/app-shell/A-sky-desktop.png`、`C-sky-desktop.png` 做一次 A+C 合并评审，然后把“已确定常量”和“开放问题”写入新的 UI spec/issue。不要从原型代码开始生产重构。
