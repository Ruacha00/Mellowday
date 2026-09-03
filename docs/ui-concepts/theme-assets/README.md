# Mellowday 主题素材参考包

这组 Mellowday 专用素材由仓库所有者 Ruacha 提供，源文件首次记录于提交
`174b83f`，选定的运行时派生文件记录于提交 `6696d63`。素材来源与许可详见
[全仓素材记录](../../../ASSET_SOURCES.md)。

本目录只保存设计参考和候选素材，目前不属于应用运行时资源。应用代码不得直接引用 `docs/` 路径；实施主题功能时，由对应工单选择性复制 `runtime/` 与 `motifs/` 中的文件到正式静态资源目录。

需要让 IDE Agent 实施主题 UI 时，先让它完整阅读 [VIBE-CODING.md](./VIBE-CODING.md)。

## 目录

```text
theme-assets/
├─ README.md
├─ VIBE-CODING.md
├─ runtime/    # 已压缩的透明 WebP 候选运行时素材
├─ motifs/     # 可缩放的 SVG 小纹样
└─ source/     # 无损 PNG 源文件，仅用于再编辑和重新导出
```

## 素材清单

| 主题 | 徽景 | 角落装饰 | 小纹样 |
| --- | --- | --- | --- |
| 晴空 | `runtime/sky-emblem.webp` | `runtime/sky-corner.webp` | `motifs/sky-sparkle.svg` |
| 樱粉 | `runtime/sakura-emblem.webp` | `runtime/sakura-corner.webp` | `motifs/sakura-petal.svg` |
| 薄荷 | `runtime/mint-emblem.webp` | `runtime/mint-corner.webp` | `motifs/mint-leaf.svg` |
| 夜色 | `runtime/night-emblem.webp` | `runtime/night-corner.webp` | `motifs/night-star.svg` |
| 简约 | 无 | 无 | 无 |

徽景适合侧栏品牌区、欢迎区或空状态；角落装饰适合页面边缘；重复出现的小元素使用 SVG mask。页面背景、渐变、卡片、按钮、窗口框和分隔线继续使用 CSS，不切成图片。

## 固定设计决策

- 晴空、樱粉、薄荷、夜色是带装饰的固定配色主题，用户只能选择，不能改色。
- 简约主题不加载装饰图片，允许调整强调色与背景亮度。
- 主题素材不包含文字、按钮、窗口、头像或业务信息。
- 装饰层不参与布局、点击、聚焦和无障碍朗读。
- 不保留独立的右侧日程栏。
- 不加入二次元头像；二次元气质由色彩、纹样和微动效表达。

## 素材晋升规则

工单确认采用某个素材后：

1. 只复制 `runtime/` 和需要的 `motifs/` 文件到应用静态资源目录。
2. `source/` 始终留在 `docs/`，不进入安装包。
3. 应用只加载当前主题对应的文件；简约主题不发起素材请求。
4. 更新 Python package-data，使新增的静态资源子目录进入 wheel。
5. 在浅色、深色、窄屏和高 DPI 下完成视觉检查后，素材才算晋升完成。

## 已验证属性

- 所有 WebP 都保留透明通道，Alpha 范围为 `0–255`。
- 徽景为 `640×427`，约 28–45 KiB。
- 角落装饰为 `1280×853`，约 75–176 KiB。
- PNG 源图约 1.1–1.8 MiB，只用于设计编辑。
