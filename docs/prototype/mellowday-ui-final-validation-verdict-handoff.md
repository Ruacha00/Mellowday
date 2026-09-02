# Mellowday UI 最终有限原型验证结论交接

## Verdict

**A+C AppShell 的结构与可访问性合同通过，可以进入生产 UI spec。**

最终自动化矩阵共 79 项：**75 Pass / 4 Fail**。四个 Fail 全部是同一个候选素材问题：Sky、Sakura、Mint、Night 的 `corner.webp` 在 DPR 2 下缺少原生像素余量；Rail/Dock、二级导航、响应式边界、Popover、Drawer、Composer、主题语义、键盘、焦点、对比度、阅读顺序、live region、控制台和只读网络合同全部通过。

这些 Fail 不阻断 A+C 结构结论，但必须在生产 UI spec 中返回主设计会话决定素材尺寸策略。原型阶段到此完成，因为每个已定义项目都有结论，失败项有可复现证据。

## 证据位置与复现

- 原始逐项结果：`docs/prototype/screenshots/app-shell-final/final-validation-results.json`
- 一次性验证脚本：`src/mellowday/web_app/static/prototypes/app-shell/final_validation.py`
- 截图目录：`docs/prototype/screenshots/app-shell-final/`

运行现有应用后访问：

```text
http://127.0.0.1:8000/static/prototypes/app-shell/index.html?variant=A&theme=sky#/conversation
```

在服务已运行时复跑矩阵：

```powershell
python src/mellowday/web_app/static/prototypes/app-shell/final_validation.py
```

脚本使用 Chromium、`prefers-reduced-motion: reduce`、CSS 视口和 DPR 模拟；它不等同于真实 Electron/Windows 缩放验收。

## 结构合同

| 合同 | 结论 | 证据与复现 |
| --- | --- | --- |
| 宽屏默认完整 Rail | Pass | `1440×900` 与 `1200×780` 实测宽度 `244px`；截图 `sky-1440x900-dpr1.png`、`sky-1200x780-dpr1.png`。 |
| 显式 Rail → Dock → Rail | Pass | 键盘聚焦“收起导航”后按 Enter，宽度从 `244px` 变为 `82px`；再次 Enter 恢复。截图 `sky-1440x900-dpr1-dock-tooltip.png`。 |
| Dock 的五个区域语义 | Pass | 五项均保留可访问文本、`title` 工具提示、唯一 `aria-current="page"` 与可见选中状态。 |
| 专注状态保持正文与 Composer 合同 | Pass | Rail 和 Dock 下 workspace 均为 `820px`，Composer 均可见；Dock 下最近对话入口可用。 |
| 专注状态跨响应式边界记忆 | Pass | Dock 状态下缩至 `880px` 显示顶部导航且不显示 Dock；恢复 `1440px` 后回到 `82px` Dock。 |
| 一级导航只有五个产品区域 | Pass | 对话、今日、生活、记忆、设置，共五项；未把子页面或最近会话放入一级导航。 |
| Life 二级导航 | Pass | `#/life` 归一为 `#/life/tasks`；任务、提醒、日历、笔记横向排列，键盘可进入并返回。截图 `sky-1200x780-dpr1-life-tasks.png`。 |
| Settings 二级导航 | Pass | `#/settings` 归一为 `#/settings/appearance`；八个横向子页可滚动，键盘与浏览器 Back 均通过。截图 `sky-1200x780-dpr1-settings-appearance.png`。 |
| 子页内容边界 | Pass | 只读可信占位；无业务编辑器、无后端写操作。 |

## 弹层、抽屉与输入

| 合同 | 结论 | 证据与复现 |
| --- | --- | --- |
| Appearance 非模态命名 dialog | Pass | `role="dialog"`、`aria-modal="false"`、名称“外观”；Escape 与外部点击均关闭并返回触发点。 |
| `520px` Appearance 近全宽 | Pass | 实测 `x≈16.96px`、宽 `≈486.08px`；截图 `sky-520x640-dpr1-appearance-popover.png`。 |
| 最近对话模态 Drawer | Pass | `aria-modal="true"`；背景 `inert`；Tab/Shift+Tab 限制在抽屉；Escape 和关闭按钮返回触发点。截图 `sky-880x780-dpr1-modal-drawer.png`。 |
| Drawer 内容密度 | Pass | 单条最近会话实测高度 `≈51.59px`，不会拉伸填满抽屉。 |
| Composer 与输入法 | Pass | 输入框聚焦时方向键不切换原型；`isComposing=true` 的 Enter 不发送；普通 Enter 只加入页面内存。 |
| Live region | Pass | transcript 本身没有 `aria-live`；独立 `polite` announcer 只播报新增内存消息，不在初载、路由或布局切换时重读 transcript。 |

## 视口矩阵

| CSS 视口 | DPR 1 | DPR 2 | 结论 |
| --- | --- | --- | --- |
| `1440×900` | `sky-1440x900-dpr1.png` | `sky-1440x900-dpr2.png` | Pass：完整 Rail / Dock、Composer 和正文均无溢出。 |
| `1200×780` | `sky-1200x780-dpr1.png` | `sky-1200x780-dpr2.png` | Pass：默认桌面尺寸稳定。 |
| `881×780` | `sky-881x780-dpr1.png` | `sky-881x780-dpr2.png` | Pass：仍为 `244px` Rail。 |
| `880×780` | `sky-880x780-dpr1.png` | `sky-880x780-dpr2.png` | Pass：切为 `42px` 标题栏 + `58px` 顶部产品导航。 |
| `521×860` | `sky-521x860-dpr1.png` | `sky-521x860-dpr2.png` | Pass：仍使用双列消息元信息合同。 |
| `520×640` | `sky-520x640-dpr1.png` | `sky-520x640-dpr2.png` | Pass：元信息并入内容列；Composer、顶栏与弹层可操作，无横向溢出。 |

每个 DPR 1 视口均记录了截图、控制台、页面异常、HTTP 错误和可操作几何；关键边界在 DPR 2 再次覆盖。

## 主题与装饰

| 主题 | 结论 | 证据 |
| --- | --- | --- |
| Sky | 布局/语义 Pass；corner DPR 2 Fail | 完整 Rail、Dock、两个边界与 Popover 均通过；`sky-1200x780-dpr2.png`。 |
| Sakura | 布局/语义 Pass；corner DPR 2 Fail | emblem、corner、motif 请求与主题匹配；`sakura-1200x780-dpr2.png`。 |
| Mint | 布局/语义 Pass；corner DPR 2 Fail | emblem、corner、motif 请求与主题匹配；`mint-1200x780-dpr2.png`。 |
| Night | 布局/语义 Pass；corner DPR 2 Fail | 正文、焦点、裁切与深色对比通过；`night-1200x780-dpr2.png`。 |
| Minimal | Pass | `520×640`、亮度 `88%` 与 `100%` 均通过；无装饰 DOM、无 `/assets/` 请求、无横向溢出；`minimal-520x640-dpr2.png`。 |

四个固定主题的装饰层均保持 `aria-hidden="true"`、`pointer-events: none`，不产生页面滚动；emblem 的 `640px` 原始宽度足以覆盖 `108 CSS px × DPR 2`。

### 唯一失败：固定主题 corner 的 DPR 2 像素余量

四张 corner 均为 `1280px` 原始宽度。在 `1200×780 @ DPR 2` 中，corner 实测 `816 CSS px`，需要约 `1632` 物理像素，因此四项 `theme-*-candidate-resolution-dpr2` 均为 Fail。截图中未见遮挡、溢出或错误裁切，柔和背景也没有出现突兀锯齿，但不能据此声称素材具有原生 DPR 2 锐度。

复现：

1. 以 `1200×780`、DPR 2 打开任一固定主题。
2. 检查 `.theme-art__corner`：`naturalWidth === 1280`、`clientWidth === 816`。
3. 比较 `1280 < 816 × 2`。

按任务边界，本次没有重制、放大或晋升这些素材。

## 可访问性合同

| 合同 | 结论 | 证据摘要 |
| --- | --- | --- |
| 文本与状态对比度 | Pass | 四个固定主题的小字/强调文字最低 `5.47:1`；高亮按钮前景最低 `5.51:1`。Minimal 在亮度 `88–100%` 范围的小字最低 `5.18:1`。 |
| 可见焦点对比度 | Pass | 固定主题最低 `3.88:1`；Minimal 边界最低 `3.64:1`。 |
| 键盘可达 | Pass | 实际用 Enter 完成 Rail/Dock、一级导航、Life/Settings 二级导航和 Appearance 打开；Drawer 打开、焦点循环、Escape 与关闭按钮通过。 |
| 阅读顺序 | Pass | DOM 顺序为标题栏 → 产品导航 → 主内容；Composer 位于主内容末段。 |
| 装饰语义 | Pass | 装饰不进入选择、布局或焦点顺序。 |
| Reduced motion | Pass | 模拟 `prefers-reduced-motion: reduce` 时命中媒体查询，装饰动画时长降为 `0.01ms`，状态不依赖动画。 |

## 控制台与网络

- 所有记录场景：浏览器 console error `0`、page error `0`、HTTP `4xx/5xx` `0`。
- 所有请求方法均为 `GET` 或浏览器允许的只读辅助请求；非 GET 请求 `0`。
- Conversation History 只读取 `GET /api/conversations`；当前无已存会话时使用页面内存密度夹具。
- Composer Enter 验证后消息只进入页面内存，网络中仍无 POST。
- 固定主题只请求各自匹配的 emblem、corner、motif；Minimal 不请求装饰素材。

## 可直接进入生产 UI spec 的结论

1. 宽屏默认 `244px` Rail，显式专注状态为 `82px` Dock；该选择在客户端会话中保留，窄窗不显示 Dock，返回宽屏后恢复。
2. 正文最大宽度不因 Rail/Dock 切换改变；Composer 与最近会话入口始终可用。
3. `≤880px` 使用带五个文字标签的顶部产品导航；`≤520px` 把消息元信息并入内容列，Appearance 使用近全宽布局。
4. Life 默认 Tasks，Settings 默认 Appearance；两者使用页面标题下的横向二级导航和 hash route。
5. Appearance 是命名非模态 dialog；窄窗最近会话是背景 inert、焦点受限的模态 drawer。
6. transcript 不应整体成为 live region；只对新增内容做克制播报。
7. 四个固定主题保持匹配的 emblem/corner/motif；Minimal 不创建装饰 DOM、不请求装饰资源。
8. 生产 token 必须重新定义并满足本次验证的 AA 下限，不能直接复制原型 CSS。

## 返回主设计会话的决策

唯一需要返回主设计会话的失败是固定主题 corner 的高 DPR 策略：

- 提供视觉匹配且具有更高原生分辨率的生产 corner；或
- 在生产 spec 中限制 corner 的最大 CSS 渲染宽度，使 DPR 2 不超过素材原生像素；或
- 明确接受该装饰作为柔焦背景的放大表现并定义视觉验收标准。

原型不替主设计会话选择其中一种，也没有修改 `docs/ui-concepts/theme-assets/`。除此之外没有发现新的产品决策。

## 明确边界

- 本次 DPR 1 / DPR 2 是浏览器模拟，不是 Windows 显示缩放证据。
- 真实 Electron/Windows 100%、125%、150%、200% 缩放仍待 Desktop Shell 阶段验收，尤其包括窗口控制、文字重排和装饰素材渲染。
- 本次只修改 throwaway 原型、验证脚本、截图与本文；没有修改生产 Web App、Python API、数据库、package data、React/Vite 生产结构或 Desktop Shell。
- 原型文件没有晋升为生产代码或运行时素材。
- 下一步回到主流程执行 `to-spec`；本原型会话不创建实现票、不开始生产实现。
