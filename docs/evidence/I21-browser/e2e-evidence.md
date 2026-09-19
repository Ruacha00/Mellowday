# I21 browser end-to-end evidence

[PASS] records toolbar with undo button is rendered
[PASS] table header has the local-time and action columns -- 标题 | 备注 | 时间（本地） | 状态 | 操作
[PASS] empty state is readable before any record exists -- 暂无记录：可在上方表单新建，或直接在对话中让助理创建。
[PASS] create shows a success notice
[PASS] new row is listed -- 买牛奶 / 低脂 / 2026-09-19 19:00 / 未完成 / 编辑完成删除
[PASS] time column shows LOCAL time, not the stored UTC value -- 2026-09-19 19:00
[PASS] tooltip still exposes the stored UTC instant -- 本地时间（浏览器时区）：2026-09-19 19:00 | 存储值 due_at：2026-09-19T11:00:00+00:00
[PASS] status badge starts as 未完成 -- 未完成
[PASS] completing a todo reports it
[PASS] row offers 重新打开 once finished -- 重新打开
[PASS] undo restores the previous status
[PASS] edit form prefills the local wall clock -- 2026-09-19T19:00
[PASS] edit form prefills title and detail
[PASS] saving reports success
[PASS] edited title is shown in the table -- 买燕麦奶
[PASS] assistant list_todos sees the value edited in the page -- ['买燕麦奶']
[PASS] assistant view keeps UTC and adds the local rendering -- 2026-09-19T11:00:00+00:00 / 2026-09-19T19:00:00+08:00
[PASS] web records API stores the ISO instant in UTC -- 2026-09-19T11:00:00+00:00
[PASS] web records API sends no due_at_local (page localises the UTC value itself) -- ['created_at', 'detail', 'due_at', 'id', 'kind', 'meta', 'source', 'status', 'title', 'updated_at']
[PASS] undo reports the edit it reverted
[PASS] undo restored the previous title -- 买牛奶
[PASS] a second undo is a notice, not an error -- 上一步已经撤销过了，无需重复撤销。
[PASS] delete reports that it can be undone
[PASS] deleted record disappears from the table
[PASS] undo of the delete reports success
[PASS] deleted record is restored -- 买牛奶
[PASS] a 404 from the backend is displayed to the user -- 保存失败：记录不存在（404：record not found）
[PASS] the failed row stays in edit mode so typing is not lost
[PASS] switching kind shows its own empty state -- 暂无记录：可在上方表单新建，或直接在对话中让助理创建。
console entries seen: ['error: Failed to load resource: the server responded with a status of 404 (Not Found)']
[PASS] no unexpected browser console errors

FAILURES: 0 (all checks passed)
