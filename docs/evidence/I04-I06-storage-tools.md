# I04 / I06 事务存储与业务工具验证记录

日期：2026-09-19　执行：离线（无真实模型）
命令：python -m pytest tests/storage tests/personal_assistant -q
结果：37 passed

## 复核（主 agent 独立执行，非转述实施者结论）

- 工具数量 21，名称与契约一致，每个工具均具备 description 与 input_schema。
- 创建记录返回 id 与 operation_id；list 可读回；undo 首次生效，重复调用返回完全相同的 dict。
- 非法参数返回结构化错误（ok=false, error=missing_argument），不抛异常。
- 未知 kind 抛 ValueError。
- 库文件位于 MELLOWDAY_DATA_DIR 之下。

## 契约裁决

list_records(kind, include_done=True)：True 返回全部状态，False 只返回有效状态。
管理面需要看到并可恢复已失效/已删除的记忆，故默认 True；一切召回路径（recall_memories 与运行时记忆注入）恒只取 active。
该裁决已写入 docs/specs/CONTRACTS.md 第 5.1 节。

## 未完成

真实模型下的工具调用参数正确性未验证，属 P1 门禁范围。
