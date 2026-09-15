# Mellowday 同类项目与长期记忆方案对标

研究日期：2026-09-15。对象：`ChatBot` 目录下的 Mellowday，目标为应届 AI Agent / 大模型应用开发岗位。

## 结论

Mellowday 值得继续做。更有价值的下一步，是借鉴成熟项目如何管理“事实来源、当前有效值、任务需要的记忆、记忆对实际操作的影响”。现有 26.5% 的完整记忆任务首轮正确率不能由“换成向量数据库”直接解释或修复。

最值得优先深入的三个参考对象：

1. **nanobot：学习轻量个人助手的记忆分层、归档降级与整理审计。** 与当前 Python 单用户助手体量最接近，适合研究整体组织。
2. **Graphiti：学习事实有效时间、历史保留、冲突候选的边界。** 对偏好更新最有启发；只吸收适合 Mellowday 的数据模型和判定规则，不建议直接迁移到整套图数据库。
3. **Letta Code：学习核心记忆与按需记忆分层、后台整理、记忆变更进入下一次模型请求的明确机制。** 适合研究“记住后真正被用上”；现行代码已经是 TypeScript 的 Letta Code，旧 Python MemGPT / Letta V1 教程不能直接代表当前实现。

**Akashic 是很重要的同龄项目参照**，值得单独追踪其证据约束与可恢复写入，但不能据小红书作者的 offer 叙述认定技术效果优于 Mellowday。**mem0 适合作为一个可插拔基线和反例**，当前 OSS 默认写入行为与常见旧教程已有显著差异。

## 研究方式与证据边界

- 从 Reddit、小红书已有调研、GitHub 用户 Issue 寻找实际需求和故障。社区帖是使用者或作者叙述，不自动等于受控实验。
- 技术事实以固定 commit 的源码核对；没有把厂商宣传、榜单或星数当成实用性证明。
- 初筛 11 个对象，源码深入 5 个：nanobot、Graphiti、Letta Code、Akashic、mem0。另有主线独立核对的 ReFind，见同目录 `community-and-refind.md`。
- 下载了只读稀疏源码快照，没有安装这些项目、运行付费模型实验，也没有修改 Mellowday 业务代码。
- 下文明确区分 **源码事实**、**用户报告**、**设计推断/建议**。一个项目有测试文件，只能证明作者编写了相应检查，本次没有运行这些测试。

## 1. Mellowday 当前问题应如何理解

根据本地 2026-09-14 评测：

| 证据 | 可以得出的判断 | 不能直接得出的判断 |
|---|---|---|
| 预置正确记忆的 Recall@5 为 84.17%，旧版 7.08% | 当前中文词项与概念匹配有明显进步 | 整条记忆链已达到 84% 正确率 |
| 完整任务首轮正确 53/200，即 26.5%；关闭记忆 1/200 | 记忆有实际收益，但多数任务仍未一次完成 | 问题一定全部在检索或 embedding |
| 长期偏好更新 3/40，即 7.5% | 更新类任务是优先调查方向 | 其余 37 次都错误使用旧偏好；其中还可能有澄清、未执行等情况 |
| 10,000 条记忆 warm 检索 P95 419.79 ms | 全量扫描随规模增加有成本 | 单用户产品已经完全不可用，必须先换分布式数据库 |

当前 `memory_context.py` 使用固定概念集合、英文词项和中文 bigram，扫描所有记忆，按分数及更新时间取 top 5；检索查询来自最新用户消息。`memory_policy.py` 用规则和证据原文约束写入。AgentCore 已有多步工具循环和确认边界。因此，研究重点应从“有没有 memory 模块”推进到以下链路：

```text
用户原始消息
  → 正确识别值得保存的事实
  → 判断新增、补充、替换、临时例外
  → 持久化并保留来源与有效时间
  → 结合当前任务检索
  → 排除过时/错误对象/不适用范围的事实
  → 正确填入工具参数并完成操作
```

本地证据：[简历证据与实验结果](<D:/Projects/Agent Learn/Project/resume-advice/evidence-run-20260914/简历证据与实验结果.md>)、[Mellowday 记忆报告](<D:/Projects/Agent Learn/Project/ChatBot/evals/memory_evidence/REPORT.md>)。以上数据不与外部 LoCoMo、LongMemEval 分数横向相减。

## 2. 广泛候选筛选

| 候选 | 类型与研究入口 | 对 Mellowday 的价值 | 本轮判断 |
|---|---|---|---|
| [nanobot](https://github.com/HKUDS/nanobot) | 完整轻量助手；小红书反复出现；用户 Issue 报告长期记忆问题 | 分层记忆、原文/摘要、整理调度、失败降级 | 优先；已读源码 |
| [Letta Code](https://github.com/letta-ai/letta-code) | 有状态助手 runtime；Reddit 长期讨论 | 核心/按需记忆、修改记忆后更新模型上下文、后台反思 | 优先；已读现行源码 |
| [Graphiti](https://github.com/getzep/graphiti) | 时间知识图谱记忆组件 | 当前事实与历史事实、实体归属、冲突处理、混合检索 | 优先学局部；已读源码与具体故障 |
| [Akashic Agent](https://github.com/kachofugetsu09/akashic-agent) | 小红书求职项目作者的长期个人助手 | 来源资格、消息 ID 证据、持久化恢复、同类项目技术叙事 | 强同类参照；已读源码，不以 offer 自述为验证 |
| [mem0](https://github.com/mem0ai/mem0) | 通用记忆组件 | 独立 add/search/update API、写入上下文、实体关联、可解释检索 | 适合作基线；当前 ADD-only 是重要限制 |
| [Hindsight](https://github.com/vectorize-io/hindsight) | 独立记忆服务 | 可研究 retain/recall/reflect 边界、事实/经验组织、多种检索 | 二线；本轮社区证据正反并存，未源码深挖 |
| [LangMem](https://github.com/langchain-ai/langmem) | 记忆抽取与更新工具库 | 热路径写入与后台整理的分工、schema 约束 | 二线局部参考；Mellowday 无须为此更换 AgentCore |
| [Khoj](https://github.com/khoj-ai/khoj) | 自托管个人知识助手 | 个人笔记、文件检索与助手产品整合 | 当 Mellowday 要做笔记/文档深度使用时再对标；与当前偏好更新问题距离较大 |
| [Cognee](https://github.com/topoteretes/cognee) | 文档/知识图谱记忆管线 | 多源知识组织、实体和关系构造 | 当前收益不确定；需要先证明个人事务任务依赖多跳关系 |
| [MemOS](https://github.com/MemTensor/MemOS) | 多组件记忆平台及插件 | 写入/更新调度、插件接入；Issue/修复可研究 API 成功却未保存等故障 | 本轮只初筛；不建议扩大到完整记忆平台建设 |
| [OpenViking](https://github.com/volcengine/OpenViking) | 分层上下文数据库 | 按摘要/目录逐步展开上下文、检索过程观测 | 对大体量资料有价值；目前单用户短事实记忆不足以支撑整套迁移成本 |

候选覆盖助手整体、轻量文本记忆、事实级记忆、图记忆、文档知识助手几个不同方向。这里的优先级是**对 Mellowday 当前问题的研究收益排序**，不是行业产品质量排名。

## 3. 深入对标 A：nanobot

### 已核对的源码

固定版本：[`499bf903022f429dd4501fdfbeeccadcb99dd51f`](https://github.com/HKUDS/nanobot/tree/499bf903022f429dd4501fdfbeeccadcb99dd51f)，提交时间 2026-09-14。

- [`nanobot/agent/memory.py`](https://github.com/HKUDS/nanobot/blob/499bf903022f429dd4501fdfbeeccadcb99dd51f/nanobot/agent/memory.py)：`MemoryStore`、`MemoryArchiver`、`Consolidator`。
- `get_memory_context()`，251–253 行，把长期 MEMORY 内容形成上下文。
- `build_dream_prompt()`，541–561 行，通过 cursor 只取未处理历史，默认每批 20 条，每条进入该 prompt 前截到 1,000 字符。
- `build_dream_tools()`，573–614 行，把后台整理可用工具和可写文件限制在指定档案/skills 范围。
- `_format_messages()`，641–661 行，使用共享的媒体 breadcrumb 逻辑，避免纯附件消息无正文时被直接遗漏。
- `MemoryArchiver.archive()`，820–933 行，模型失败、输出截断、意外 tool call、空摘要、超预算等情况转为有界原文 checkpoint；没有把这些情况当成“没有可记忆信息”。
- `dream_content_diff()` 与 `build_dream_commit_message()`，以实际文件变化构造整理审计信息；Git 跟踪 SOUL、USER、MEMORY 与整理 cursor。

### 从使用问题得到的经验

1. [Issue #3227](https://github.com/HKUDS/nanobot/issues/3227)，2026-04-16：用户称轻量架构容易学习，但长期/大型项目中细节保留不足。这是当时版本的使用报告，不能直接描述九月最新版本。
2. [Issue #5118](https://github.com/HKUDS/nanobot/issues/5118)，2026-07-27，后于 07-29 关闭：实时消息回放与归档的渲染方式不同，导致只存在于结构化 `media[]` 中的路径在归档时消失。报告者进一步指出，即便把路径给摘要模型，模型仍可能不复述它。当前源码已看到共享媒体渲染修复，但不能由此宣称所有附件长期回查完全可靠。
3. [Issue #2957](https://github.com/HKUDS/nanobot/issues/2957)，2026-04-09：用户报告 Dream 后 MEMORY.md 变空。该帖证据很短，不能单独断定具体根因；它提示整理本身是一种可能损坏信息的写操作，需要版本与恢复证据。

### 可以借鉴

- **热对话、历史原文/摘要、稳定档案分层。** 不把所有历史都当成同一种“memory text”。
- **自动学习和明确保存分开。** 自动整理可以后台执行；用户明确说“以后改为下午”应有明确的保存结果和立即可见的当前值。
- **失败状态可区分。** 没抽取到事实、模型不可用、输出格式错、超过预算，应留下不同状态。
- **可检查的整理变更。** 用户能知道何时、根据什么消息改了记忆；SQLite 的变更记录足以借鉴这点，不必把整个用户数据放进 Git。

### 不宜照搬

- 把所有长期事实集中在一个 Markdown 档案中，未必解决 Mellowday 的偏好冲突和细粒度检索。
- 后台 Dream 有延迟，不能假设“刚说完新偏好，下一次操作一定已读到”。
- 当前 Dream 输入仍有截断和批次边界，摘要和整理不是无损压缩。

## 4. 深入对标 B：Graphiti

固定版本：[`c035afb7990b6077331a81e98b04efcfd9bf8184`](https://github.com/getzep/graphiti/tree/c035afb7990b6077331a81e98b04efcfd9bf8184)，提交时间 2026-09-11。

### 源码事实

- [`graphiti_core/edges.py`](https://github.com/getzep/graphiti/blob/c035afb7990b6077331a81e98b04efcfd9bf8184/graphiti_core/edges.py#L263)，`EntityEdge` 包含事实文本、实体关系、来源 episode IDs，以及 `valid_at`（事实何时成立）、`invalid_at`（何时不再成立）、`expired_at`（系统何时标记其失效）、`reference_time`。
- [`edge_operations.py`](https://github.com/getzep/graphiti/blob/c035afb7990b6077331a81e98b04efcfd9bf8184/graphiti_core/utils/maintenance/edge_operations.py#L538)，`resolve_edge_contradictions()` 对被判为冲突的事实按有效时间处理；旧事实被标记失效，记录仍在。
- 同文件 684–695 行有“相同端点与规范化相同文本”的去重快速路径，避免每件事都交给模型。
- [`search_config_recipes.py`](https://github.com/getzep/graphiti/blob/c035afb7990b6077331a81e98b04efcfd9bf8184/graphiti_core/search/search_config_recipes.py#L33)，提供 BM25、向量相似度的融合检索，可用 RRF；另有 BFS 与 cross-encoder 配方。它们是可选方案，不是每次查询都必然执行全部方法。

### 特别值得学的反例

[Issue #1728](https://github.com/getzep/graphiti/issues/1728)，2026-08-04，报告基于 0.29.3：用户发现新事实可能把同一实体的无关有效事实判为已过时。报告者的图谱数量和人工检查结果只是其单一部署数据，不可推广成产品错误率。

本轮固定源码中仍能核对到对应风险路径：

- 399 行，重复检测使用具体 `edge_uuids` 过滤。
- 414 行，失效候选检索却使用空 `SearchFilters()`，在 group 范围内找相似事实。
- 700–713 行，给冲突判定模型的候选主要是 `idx` 和事实文本。
- 754–776 行，把模型返回的冲突索引转为失效候选，再应用时间规则。

这不能证明某次具体误判一定发生，但说明**“有时间知识图谱”与“可靠识别事实替换”是两件事**。结构边界不清楚，模型的一次误判会被持久化。

### 对 Mellowday 的直接启发

建议只为具有清楚替代关系的事实建立有边界的当前值，例如：

```text
主体=当前用户
属性=工作日提醒偏好时段
值=下午
适用范围=工作日
事实生效时间=用户声明的开始时间
记录时间=收到消息的时间
来源=消息 ID + 证据片段
替代=上一条同主体、同属性、同适用范围的事实 ID
```

“现在喜欢下午”可以替换同一范围的旧偏好；“这周三上午提醒我”更可能是一次任务约束；“去年喜欢上午”是历史描述，不能仅因写入时间更晚就覆盖当前值。

这是**本报告的设计建议**，并非声称 Graphiti 原样实现了上述业务规则。Mellowday 可先用 SQLite 表和事务完成，无需 Neo4j/FalkorDB。只有当任务真正依赖多实体、多跳关系时，再评估图数据库。

## 5. 深入对标 C：Letta Code / MemGPT 路线

### 必须先纠正版本认识

`letta-ai/letta` 当前主分支的 [`README`](https://github.com/letta-ai/letta/blob/5bcdd177d70fa2b31a754cfcd801e77b2e1ab16a/README.md) 明确指向 `letta-ai/letta-code`；历史 Python V1 API server 在 `archive` 分支。继续把旧 MemGPT 工具名和旧架构图当作现行默认，会得出错误对标。

本轮现行源码：[`51467f82d273867d82559fb1696d881fa335c7ff`](https://github.com/letta-ai/letta-code/tree/51467f82d273867d82559fb1696d881fa335c7ff)，UTC 提交日期 2026-09-15。

### 已验证的设计

- [`src/backend/local/system-prompt-compilation.ts`](https://github.com/letta-ai/letta-code/blob/51467f82d273867d82559fb1696d881fa335c7ff/src/backend/local/system-prompt-compilation.ts)：读取已提交的 MemFS revision；用 Git HEAD 获取 Markdown 内容；本地编译路径区分 `system/` 下的核心内容与外部记忆目录投影，并记录 `memfsRevision`。这给“本次模型实际看到哪个版本的记忆”提供了可检查的边界。
- [`post-turn-reflection.ts`](https://github.com/letta-ai/letta-code/blob/51467f82d273867d82559fb1696d881fa335c7ff/src/cli/helpers/post-turn-reflection.ts)：一轮结束并追加 transcript 后再判断反思触发条件，可关闭、按 compaction 事件或 step count 触发。
- [`reflection-v2.md`](https://github.com/letta-ai/letta-code/blob/51467f82d273867d82559fb1696d881fa335c7ff/src/agent/subagents/builtin/reflection-v2.md)：新布局使用根层核心档案与子目录 deferred memory；要求更新旧事实源头而不是只在其旁边追加新版本。仓库同时存在旧布局和新布局路径，不能将它们混成一个已经全场景统一的实现。
- 反思提示把事实/偏好与可复用流程技能分开，要求只把重复可用的多步过程做成 skill。这是运行约定，效果仍依赖模型与调用端执行。

### 用户实际遇到的边界

[Issue #808](https://github.com/letta-ai/letta-code/issues/808) 报告无界面的 headless 使用中，MemFS 同步冲突会让进程退出，需要解决冲突的机制。即使 Git 带来版本历史，也引入同步和冲突负担。Mellowday 单用户本地产品没有必要为了“先进架构”引入多端 Git 同步。

### 可以借鉴

1. 把少量稳定、常用个人资料作为核心上下文；其余按当前任务检索，不每轮注入全部档案。
2. 每次请求固定一个 `memory_revision` 或读取快照，日志记录已选事实；后续工具运行以这次快照为依据。
3. 自动整理与主任务执行分工明确；任务结束后再整理不必阻塞回复，但新偏好需要被下一次动作使用时要有可见的完成边界。
4. 记忆修改后要确认上下文确实刷新，不能只验证数据库中存在新值。

### 不宜照搬

完整 Letta Code 的终端、App Server、channels、Git worktree、反思子进程与 coding agent 工具集会改变 Mellowday 的技术路线。学习其几个边界即可，不建议迁移 runtime 来获得记忆功能。

## 6. 深入对标 D：Akashic Agent

固定版本：[`fdcbae3747be7a9b6743967234916b85403e11bb`](https://github.com/kachofugetsu09/akashic-agent/tree/fdcbae3747be7a9b6743967234916b85403e11bb)，提交日期 2026-09-14。

小红书作者在[分享帮我拿到字节暑期岗位的 agent 项目](https://www.xiaohongshu.com/explore/69e4ff92000000002102c20a)中介绍该项目，强调记忆与工具系统。该结果是作者自述，不代表已验证的招聘因果关系。

### 本轮真正值得借鉴的源码

- [`plugins/markdown_memory/message_plugin.py`](https://github.com/kachofugetsu09/akashic-agent/blob/fdcbae3747be7a9b6743967234916b85403e11bb/plugins/markdown_memory/message_plugin.py#L506)，`check_evidence()` 检查新增条目对应实际消息 ID，用户事实必须有真实用户输入作为来源，不能只依靠助手或后台报告。来源合法不等于事实语义一定正确，作者在架构记录中也明确承认这一点。
- 同文件 `prepare_profile_draft()`，142–181 行，先在内存生成并校验草稿，批次全部成功后交给持久化 writer；有一次受约束的格式修复机会。
- [`plugins/markdown_memory/store.py`](https://github.com/kachofugetsu09/akashic-agent/blob/fdcbae3747be7a9b6743967234916b85403e11bb/plugins/markdown_memory/store.py#L217)，每个 source_ref 的草稿、before-image、applied receipt 可重放；核对当前摘要 hash 与 before/after，避免途中修改被覆盖。
- [`plugins/context/search.py`](https://github.com/kachofugetsu09/akashic-agent/blob/fdcbae3747be7a9b6743967234916b85403e11bb/plugins/context/search.py#L17)，消息检索建立 SQLite FTS5 trigram 索引，支持 session/source/author/kind 过滤，短于 3 字符的词另走子串候选路径。该索引在内存构建，不能由“用了 FTS”推断其启动成本或万条场景性能优于 Mellowday。
- [ADR 0052](https://github.com/kachofugetsu09/akashic-agent/blob/fdcbae3747be7a9b6743967234916b85403e11bb/docs/decisions/0052-compaction-and-markdown-memory-are-ordinary-plugins.md)：记录为何退役重复的 PENDING/optimizer 调度，将持久化已提交 checkpoint 作为整理来源。说明作者也在删减架构复杂度。

### 很重要的限制

当前 Markdown 插件提示和校验只允许 **additions**，禁止隐式删除旧事实。它防止模型覆盖丢失已有档案，但本身不能证明解决了 Mellowday 的“当前偏好替换”。不要把“有复杂记忆系统”误读成“长期更新已可靠”。

README 中仍有旧 PENDING/Optimizer 说明，与较新的 ADR 和插件代码不完全一致。小红书四月宣传中的 MD+向量、HyDE/RRF 等能力也必须定位具体引擎和版本；本轮不把旧介绍直接归给当前 Markdown 路径。

评测目录有 LongMemEval 和 PersonaMem 的 ingest→consolidation→AgentLoop QA 接法，样本独立 workspace，有避免串题的结构。但本轮没有找到并复跑可与本地直接比较的同模型同任务结果，不能宣称其完整事务操作更好。

### 对 Mellowday 的研究价值

这是非常好的“同类项目成长记录”参照：消息来源、记忆投影、恢复写入、评测入口可以逐项学习。Mellowday 已有 SQLite 和确认机制，可以以更小的实现吸收同样的思路。没有必要复制其插件热切换、复杂恢复协议和所有后台行为。

## 7. 深入对标 E：mem0

固定版本：[`c7ee362aff94a369af70f13f2b4f853f6793ff4c`](https://github.com/mem0ai/mem0/tree/c7ee362aff94a369af70f13f2b4f853f6793ff4c)，提交日期 2026-09-11。

### 当前代码与常见介绍的差异

[`mem0/memory/main.py`](https://github.com/mem0ai/mem0/blob/c7ee362aff94a369af70f13f2b4f853f6793ff4c/mem0/memory/main.py#L879) 的 OSS 默认推断写入路径：

1. 读取最近 10 条消息和相关的既有记忆候选。
2. 把既有 UUID 映射成短索引，减少模型编造 ID。
3. 单次 LLM 调用 `ADDITIVE_EXTRACTION_PROMPT`。
4. 批量 embedding、哈希去重、写入新记忆以及关联 ID。

[`prompts.py`](https://github.com/mem0ai/mem0/blob/c7ee362aff94a369af70f13f2b4f853f6793ff4c/mem0/configs/prompts.py#L468) 明确 ADD-only。文件中仍存在旧 UPDATE/DELETE 提示函数，不代表当前默认 add 路径使用它。显式 `update()` / `delete()` API 存在，但这与“自动把新偏好替换旧偏好”不同。

[Issue #5867](https://github.com/mem0ai/mem0/issues/5867) 给出足球偏好从 Ronaldo 改为 Messi 的复现，指出 ADD-only 可使相互冲突的偏好并存。这与本轮源码吻合。不能仅根据过去两次 LLM 的旧架构文章，承诺接入当前 mem0 就自动获得可靠更新。

其他核对点：

- 当前检索支持阈值、可选 rerank、explain，以及过期过滤。
- `reference_date` 参数在 OSS 路径显式报不支持；不能把商业平台的时态能力当成开源本地版既有能力。
- 模型调用异常会抛出 LLMError，避免与“没有抽取到事实”混淆；但响应 JSON 解析失败仍可能得到空抽取结果。可见同一组件不同失败环节也未必统一。

### 对 Mellowday 的价值

- 可借鉴“近期对话 + 相关既有事实”一起参与抽取，帮助指代消解和去重。
- 可借鉴实体 ID、来源、关联记忆的显式字段，以及 embedding 批量调用。
- 可作为一条独立实验策略，验证通用组件相对当前规则方案的完整任务收益与成本。
- 不建议直接把当前 memory_policy 全部替换成 mem0 并宣称更新问题已解决。

## 8. 社区经验中的一致点与分歧

### 有用的一致问题意识

- 使用者反复提到重复、旧值残留、抽取成本、上下文膨胀和维护负担。
- [Hindsight 使用讨论](https://www.reddit.com/r/hermesagent/comments/1t5yjje/which_memory_tool_do_you_have_experience_with/)有人报告重复记忆和清理困难；[另一位使用者](https://www.reddit.com/r/ChatGPTCoding/comments/1vy6vsj/i_gave_all_my_ai_coding_agents_one_shared/)介绍以 Postgres/pgvector 与外部 embedding 部署共享记忆，体验更积极。前者不证明所有配置都重复，后者不证明其榜单结论成立。
- [LangMem 使用反思](https://www.reddit.com/r/LangChain/comments/1toabbw/why_i_stopped_defaulting_to_langmem_and_what_i/)同时谈到框架运行成本和自建的维护负担。其“三倍维护”等数字是个人经验，没有受控计量，不宜做普遍估算。
- [Cognee 使用讨论](https://www.reddit.com/r/openclaw/comments/1thtqyo/memory_cogneeneo4jlancedbgraphiti/)中，使用者主动避免把不断变化的项目当前状态无限写进高层知识页；这与 Mellowday 区分任务临时状态、长期偏好有关。

### 没有一致答案的部分

文本/文件检索与向量/图检索都有人支持。社区并没有证明每个个人助手必须用知识图谱、必须加多 Agent 或必须做拟人“梦境”。[Letta 与 mem0 基准争议讨论](https://www.reddit.com/r/LocalLLaMA/comments/1mon8it/woah_letta_vs_mem0_for_ai_memory_nerds/)包含厂商参与者，恰好说明测试配置和任务定义会改变结论；不能把争议中的任何一家自测当作 Mellowday 的选型排名。

Mellowday 的合适策略是保留多条小型可比较实现，比较自己的完整事务任务，而不是先选一位“记忆系统冠军”。

## 9. 建议的改造研究顺序

以下为对标后形成的建议，尚未实施，也不是已经证实的根因。

### P0：先定位失败落在哪个环节

沿现有 200 个主任务执行轨迹，给每次失败标记：

1. 该学的事实是否保存；来源是否正确。
2. 更新是否替换当前值，还是形成了两个冲突条目。
3. 检索查询是否理解了当前任务和指代。
4. 正确事实是否进入模型可见上下文；是否混入过时值。
5. 模型是否把正确事实用于实际工具参数。
6. 工具操作是否完成，还是澄清/退出/被边界拦截。

每次记录 memory IDs、版本、有效时间、选中原因和工具参数。不要仅靠终局对话回答判断“用了记忆”。

### P1：当前有效事实与历史证据分开

借鉴 Graphiti 的时间语义，加上 Akashic 的来源约束：

- 保存原消息 ID 与证据片段，同时允许规范化事实内容；“事实必须逐字出现在证据里”与“事实有真实来源”不是同一件事。
- 对明确可替代的主体/属性/范围执行有界更新；把新增、补充、替换、临时例外区分开。
- 保留旧值的历史可查性，同时默认当前事务只选择当前有效值。
- 当前请求里的明确约束优先于历史默认偏好；第三人的偏好不能替换当前用户。

这能形成很具体的技术主线：从简单文本记忆演进为有来源、有适用范围、有更新语义的个人事实存储。

### P2：检索围绕当前任务，并保留原文回查

借鉴 Letta/nanobot 的分层与主线 ReFind 的回查工具：

- 少量常用资料形成有预算的核心上下文。
- 当前任务的语义、最近澄清内容共同生成检索条件，不只用最后一句“就按这个来”。
- 当前事实优先；如果需要历史经过，再查原消息、时间和邻域。
- 先试有中文适配的 SQLite 全文索引与结构字段过滤；在未见词汇、跨表达案例仍明显漏召回时，再比较 embedding+全文融合。
- 不因一个项目使用了 RRF、HyDE、图遍历就同时加入所有步骤。

### P3：验证记忆是否改变实际行为

不能以“最终回复说记住了”验收。应使用完整场景：

| 场景 | 需要观察的结果 |
|---|---|
| 上周默认上午，本周明确改为下午 | 下个新会话的任务参数使用下午；旧值历史仍可查 |
| 今天例外上午，长期仍偏好下午 | 当次任务上午，下次默认下午 |
| 用户说朋友喜欢上午 | 不覆盖用户自己的偏好 |
| 用户先后改过三次，后来补述去年的偏好 | 当前值依据事实生效时间和语义，而不是简单取最后写入 |
| 用户说“还是按我最近的习惯” | 能从任务与最近澄清确定检索对象 |
| 模型说保存成功但记忆写失败 | 不把成功承诺留在界面；状态可以追踪 |
| 新记忆保存成功，但下一次请求仍缓存旧上下文 | 能从 memory revision 与实际 provider payload 发现 |
| 摘要漏掉事件日期或任务 ID | 可通过原始消息或结构化记录恢复所需信息 |

验收主指标仍是首次完整完成率、更新类首次正确率、错误偏好用于动作的次数、无依据写入、正常场景回退与成本/延迟。Recall@k 只作为定位中间环节的指标。

## 10. 推荐保持的小型实验矩阵

| 实验条件 | 用途 |
|---|---|
| 当前词项/概念检索 + 当前写入 | 可复现基线 |
| 原始历史在上下文预算内直接提供 | 检查“已有足够证据但模型仍不用”的上限问题；成本必须一起报 |
| 结构化当前值 + 原文回查 | 检验更新、指代和任务工具使用是否改善 |
| 上一条件 + embedding/全文融合 | 分离语义召回贡献，避免把写入修复和向量收益混在一起 |
| 可选 mem0 适配 | 验证通用组件在同一任务和成本约束下是否值得采用 |

保持模型、任务、成功判据一致，按任务族报告结果；另留没有参与修改的新表达和新主题。没有必要先把全部 11 个系统安装后跑一次排行榜。

## 11. 面向求职的最终技术主线

对标以后，Mellowday 最有说服力的定位可以是：**能基于跨会话个人信息正确完成事务的个人 Agent，重点解决偏好更新、来源追踪和记忆到工具执行的衔接。**

面试应能讲清：

- 为什么从旧方案走到当前方案，失败样本是什么。
- 参考了哪个项目的哪段机制，哪些部分不适合自己的体量。
- 如何区分长期默认、临时约束、历史事实和第三人信息。
- 为什么检索正确仍可能操作失败，如何沿调用链定位。
- 更新后完整任务有什么收益，付出了多少模型调用和延迟。

这条主线与已有 AgentCore、任务/日历/提醒工具相衔接，比再添加一个泛化“自我反思/知识图谱/多 Agent”标签更容易形成可验证的能力证据。

## 附：源码快照

只读研究副本位于本目录 `source-snapshots/`：`nanobot-git`、`graphiti-git`、`mem0-git`、`letta-git`、`letta-code-git`、`akashic-git`。这些是稀疏检出，没有安装其依赖或运行服务。固定 SHA 已在各章节记录；所有实际产品代码保持未修改。
