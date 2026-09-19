# t10 real-process evidence

[PASS] the real server is up -- http://127.0.0.1:58886
[PASS] the turn finished -- ['busy_end', 'token_usage', 'turn_end', 'done']
[PASS] the model asked for the tool
[PASS] the record has the tool result -- 1
[PASS] the record carries the structured reference -- ref=1789787005099-list_notes-040c1975 chars=43795
[PASS] the model-visible result is the placeholder, not the original -- [Result too large: 43795 chars / 42.8 KB from tool "list_not
[PASS] GET /api/sessions/{id} serves a bounded display view that keeps the ref -- chars=1648 display_shortened=None
[PASS] the display view and the record are separate fields
[PASS] the first page is served over real HTTP -- 200
[PASS] the page carries the whole-original length -- 43795
[PASS] the page is the original text
[PASS] the page says how to continue
[PASS] paging continues at the right offset
[PASS] the placeholder is not what the endpoint serves
[PASS] a query read locates the passage -- 200
[PASS] the query reports where the match is
[PASS] a query miss is a 404, not a 500 -- 404
[PASS] an unknown ref is a 404 -- 404
[PASS] a ref that looks like a path is a 400 -- 400
[PASS] another session cannot follow this ref -- 404
[PASS] traversal attempt ..%2F..%2Fmellowday.sqlite3 is refused without a 500 -- 404
[PASS] traversal attempt ..%5C..%5Cmellowday.sqlite3 is refused without a 500 -- 400
[PASS] the artifact directory exists while the session lives -- D:\Projects\Agent Learn\Project\MellowDay-Rebuild\output\acceptance-r4\references-data\tool_results\t10evidence
[PASS] the session is deleted over real HTTP -- 200
[PASS] the deletion removed the artifact directory
[PASS] a stale ref answers 404 after the deletion -- 404
[PASS] no read recreated an artifact or a session directory -- []

FAILURES: 0 (all checks passed)
