# 主题 UI Vibe Coding 指南

## 触发条件

实现、重构或评审 Mellowday 的主题 UI 时使用本指南。素材清单与不可变设计决策以同目录的 [README.md](./README.md) 为准。

## 目标

把五张效果图实现为同一套页面结构上的五种外观：四个固定配色装饰主题，以及一个可调色、无装饰的简约主题。第一阶段保持现有后端接口和业务行为不变，只改造前端结构、主题系统和素材加载方式。

## 开始前读取

依次读取并遵守：

1. 仓库根目录 `AGENTS.md`、`CONTEXT.md`。
2. `docs/product-direction.md`。
3. 与 Web App、Persona 和桌面入口相关的 ADR。
4. `docs/ui-concepts/themes/` 下的五张效果图。
5. 本目录的 `README.md` 和候选素材。

完成标准：能够说清 Persona 只影响聊天、生活记录与记忆分离、设置页保持中性，以及四个固定主题与简约主题的差异。

## 实施路线

### 1. 建立基线

- 检查当前 Web App 入口、静态资源打包配置和浏览器测试。
- 使用 GitNexus 查询现有页面加载、消息追加和实时事件流程；修改现有符号前完成 upstream impact。
- 记录需要保持的 DOM id、可访问名称、API 和 SSE 行为。

完成标准：列出会受页面拆分影响的测试和调用流程，没有依靠猜测开始重写。

### 2. 先搭页面壳

建立稳定的 `AppShell`：侧栏、顶部栏、内容出口、全局实时连接和主题管理器。推荐页面：

```text
对话
今日
生活：任务 / 日历 / 提醒 / 笔记
记忆
设置：外观 / Persona 与主动聊天 / 服务与能力 / 历史审计 / 系统诊断
```

“今日”是独立页面，不建立常驻右侧日程栏。实时提醒和主动消息连接属于 `AppShell`，页面切换时继续存在。

完成标准：聊天行为保持不变，页面切换不会断开实时消息，也不会同时加载所有设置数据。

### 3. 建立主题注册表

主题模型至少包含：

```js
{
  id: "sky",
  kind: "fixed",
  editable: false,
  decorations: true,
  emblem: "...",
  corner: "...",
  motif: "..."
}
```

`sky`、`sakura`、`mint`、`night` 使用固定 token；`minimal` 使用 `kind: "custom"`、`editable: true`、`decorations: false`。通过 `<html data-theme="...">` 切换主题。选择结果与简约主题颜色先存入本地持久化，不为第一阶段新增后端接口。

完成标准：固定主题不显示调色控件；简约主题可以调色，且不会解析或请求任何装饰文件。

### 4. 晋升所需素材

从本目录选择采用的 WebP 和 SVG，复制到正式静态资源目录。应用不得引用 `docs/`。PNG 源文件继续留在本目录。

建议 DOM：

```html
<div class="theme-art" aria-hidden="true">
  <img class="theme-art__emblem" alt="" decoding="async">
  <img class="theme-art__corner" alt="" decoding="async">
  <i class="theme-art__motif"></i>
</div>
<main class="app-content">...</main>
```

装饰层使用绝对定位、`pointer-events: none`、`user-select: none`，内容层位于其上方。徽景控制在约 `140–260px`；角落装饰使用 `clamp()` 控制在约 `480–980px`。窄屏降低透明度或隐藏大型装饰，小纹样优先隐藏。

完成标准：装饰不改变内容布局，不遮挡点击和文字，文本对比度至少达到 `4.5:1`。

### 5. 用 CSS 完成剩余视觉

以下元素使用 CSS 或现有图标体系实现：

- 页面底色与渐变。
- 卡片、输入框、按钮和弹层。
- 拱形窗口框、分隔线和状态点。
- 阴影、圆角、间距和响应式布局。
- 轻量漂浮动画；在 `prefers-reduced-motion` 下关闭。

不要从效果图裁切文字、按钮或完整卡片。大图只承担低频装饰，小纹样只承担氛围点缀。

完成标准：去掉所有素材后页面仍然完整可用；素材只影响氛围，不承载业务意义。

### 6. 验证并收尾

至少验证：

- 五种主题刷新后保持选择。
- 四个固定主题没有调色入口。
- 简约主题无装饰请求、无装饰 DOM 可见状态。
- 主题切换不影响聊天、SSE、提醒确认和页面数据。
- 离开系统诊断页后停止诊断轮询。
- 桌面、窄屏、高 DPI、浅色和夜色场景没有遮挡或溢出。
- wheel 包含晋升后的 WebP/SVG，不包含 `source/` PNG。
- 现有浏览器测试通过，并新增主题持久化与无装饰请求测试。
- 提交前运行 GitNexus change detection。

完成标准：每项都有自动化结果或截图证据；没有用“看起来应该可以”代替验证。

## 可直接交给 IDE Agent 的工单

```text
实现 Mellowday 五主题前端框架。开始前完整阅读 AGENTS.md、CONTEXT.md、
docs/product-direction.md、相关 ADR，以及
docs/ui-concepts/theme-assets/VIBE-CODING.md。

保留现有后端 API、聊天行为和实时事件连接。建立 AppShell 与页面路由，去掉常驻右侧日程栏。
实现晴空、樱粉、薄荷、夜色四个固定配色装饰主题，以及可调色且无任何装饰请求的简约主题。
效果图只作为视觉参考；按钮、文字、卡片、窗口框和背景使用 HTML/CSS，不从效果图裁切。

按主题选择 docs/ui-concepts/theme-assets/runtime 和 motifs 中的候选素材，
将确认采用的文件复制到正式静态资源目录；source PNG 必须留在 docs，不进入 wheel。
素材位于独立、不可交互、aria-hidden 的装饰层，并按断点调整尺寸和透明度。

修改现有符号前执行 GitNexus upstream impact；完成后更新浏览器测试、检查 wheel 内容，
并运行 GitNexus change detection。提交实现、验证结果和采用的素材清单。
```
