# I21 second browser pass

[PASS] undo toolbar is laid out above the table -- toolbar y=127 h=36, table y=177
[PASS] undo button is visible and labelled
[PASS] notice line is present
[PASS] record without a due date falls back to a local created_at -- 2026-09-18 18:13（创建） vs expected 2026-09-18 18:13 from 2026-09-18T10:13:13.267817+00:00
[PASS] notes offer 归档 rather than 完成 -- 归档
[PASS] 归档 writes the status the store expects for notes -- archived
[PASS] finished note is still listed with its badge -- 已归档
[PASS] undo returns the note to active
[PASS] every edit input is rendered with a usable size -- [{'w': 234.375, 'h': 34, 'v': '会议纪要'}, {'w': 234.375, 'h': 34, 'v': '三行'}, {'w': 267.015625, 'h': 36, 'v': ''}]
[PASS] edit inputs are prefilled with the record -- ['会议纪要', '三行', '']
[PASS] save and cancel are both visible in edit state
[PASS] cancel returns the row to browse state

FAILURES: 0 (all checks passed)
