"""Execute the actual browser paging handlers with an offline transport."""
import shutil
import subprocess

import pytest

from mellowday import paths


def test_continue_loading_preserves_ref_and_appends_second_page():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to execute browser paging handlers")
    script = r'''
const fs = require('fs');
const vm = require('vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[1], 'utf8');
const names = ['traceResultState', 'sessionEndpoint', 'toggleToolResult',
  'loadToolResult', 'toolResultNote', 'renderToolResultBox'];
const functions = names.map(name => {
  const match = source.match(new RegExp('^(?:async )?function ' + name + '\\(.*?^\\}', 'ms'));
  assert.ok(match, name);
  return match[0];
}).join('\n');
function element() {
  return {children: [], textContent: '', appendChild(child) {this.children.push(child);},
    set innerHTML(value) {this.children = [];}};
}
const original = 'first-page-'.repeat(800) + 'second-page-marker';
const urls = [];
const ctx = {
  state: {sessionId: 'a-', traceResults: {}},
  SESSION_ENDPOINTS: {toolResult: '/api/sessions/{session}/tool-results/{ref}'},
  TRACE_RESULT_PAGE: 8000,
  document: {createElement: element},
  requestJson: async url => {
    urls.push(url);
    const parsed = new URL(url, 'http://localhost');
    assert.equal(parsed.pathname, '/api/sessions/a-/tool-results/kept-reference');
    const offset = Number(parsed.searchParams.get('offset'));
    const end = Math.min(original.length, offset + 8000);
    return {ok: true, data: {ok: true, text: original.slice(offset, end),
      total_chars: original.length, next_offset: end < original.length ? end : null,
      has_more: end < original.length}};
  },
};
vm.createContext(ctx);
vm.runInContext(functions, ctx);
(async () => {
  const box = element(), button = element();
  await ctx.toggleToolResult('kept-reference', button, box);
  assert.equal(box.children[0].textContent, original.slice(0, 8000));
  const more = box.children.find(child => child.textContent === '继续加载');
  assert.ok(more, 'first page must offer another page');
  more.onclick();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(urls.length, 2);
  assert.ok(urls[1].includes('offset=8000'));
  assert.equal(box.children[0].textContent, original);
  assert.equal(box.children.some(child => child.textContent === '继续加载'), false);
  await ctx.toggleToolResult('kept-reference', button, box);
  await ctx.toggleToolResult('kept-reference', button, box);
  assert.equal(box.children[0].textContent, original);
  assert.equal(urls.length, 2, 'reopening uses the full cached result');
})().catch(error => {console.error(error); process.exitCode = 1;});
'''
    result = subprocess.run(
        [node, "-e", script, str(paths.static_dir() / "app.js")],
        text=True, capture_output=True, timeout=20, encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
