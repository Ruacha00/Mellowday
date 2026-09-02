# Mellowday UI prototype handoff

## Next-session focus

Build a clearly throwaway UI prototype that answers one question: does the proposed AppShell, Conversation Surface, theme popover, and non-interactive decoration layer still work at realistic content density?

This is a UI-look prototype, not a production migration. Keep all state in memory and make it runnable with one obvious command. Follow the existing Web App/static-serving convention rather than introducing a frontend framework or a new backend route unless the current code proves that unavoidable.

## Authoritative references

Read these in order before designing or editing:

- `AGENTS.md`
- `CONTEXT.md`
- `docs/product-direction.md`
- `docs/adr/0002-separate-core-assistant-and-web.md`
- `docs/adr/0003-persona-applies-only-to-chat.md`
- `docs/adr/0004-memory-is-not-a-life-record.md`
- `docs/adr/0008-make-desktop-application-the-primary-entry.md`
- all five references under `docs/ui-concepts/themes/`
- `docs/ui-concepts/theme-assets/README.md`
- `docs/ui-concepts/theme-assets/VIBE-CODING.md`

Treat `chatbot/` as a read-only reference clone. Do not modify, move, import from, or commit anything in it.

## Scope

Prototype only:

- the new AppShell framing and primary navigation;
- the chat page under realistic density;
- the theme popover, including all five documented themes;
- the decorative layer and its responsive/interaction behavior.

Use static, in-memory fixtures rich enough to expose layout failure: several recent conversations, a long mixed transcript (short and long turns, paragraphs, list/code-like content, timestamps/status where the concept calls for them), a multiline draft, and enough sidebar/header content to test truncation and scrolling.

The UI-prototype skill calls for visibly different alternatives on one route. Provide a small set of meaningful AppShell/density variants selected by a URL query parameter and a floating prototype-only switcher. Do not treat the five color themes as those structural variants.

## Hard boundaries

- Do not modify backend Python, APIs, persistence, SSE/runtime delivery, providers, Agent Core, or Personal Assistant behavior.
- Do not migrate or build Today/Life, Memory Management, or Settings functionality. If navigation needs those destinations for shell realism, keep them inert and clearly outside the evaluated path.
- Do not wire the prototype to real life records, memories, settings data, or conversation persistence.
- Do not promote candidate assets into production static/package-data locations for this experiment. The prototype may reference or copy only what is needed in a clearly throwaway prototype location; production asset promotion belongs to a later implementation decision.
- Decorations must remain semantic-free, `aria-hidden`, non-focusable, and `pointer-events: none`; removing them must leave the page fully usable.
- Preserve the product language boundaries in `CONTEXT.md`: Persona affects chat only; management surfaces remain neutral; Memory and Life Records remain distinct.
- Preserve all unrelated working-tree changes. At handoff time the tree was already dirty, including project/domain docs and the new UI-concept material.

## Existing implementation anchors

- Current Web App shell: `src/mellowday/web_app/static/index.html`
- Current browser behavior: `src/mellowday/web_app/static/app.js`
- Current styling: `src/mellowday/web_app/static/styles.css`
- Existing real-browser coverage: `tests/web_app/test_browser_conversation.py`
- Packaging/static configuration: `pyproject.toml`
- Local run instructions: `README.md`

The current page is a plain HTML/CSS/JS Web App served by the Python application. Prefer a self-contained prototype page and prototype-only assets/fixture script close to this surface. Mark every prototype artifact as throwaway.

## GitNexus guardrails

The bound GitNexus repository is `mellowday`. The index context reported commit `e66dca56ac268dfec41b9bd6b8e7f84b01551b0c`, 1,957 symbols, 10,144 relationships, and 170 processes, with no incomplete-index reason or stale warning at handoff time.

Before editing any existing function/class/method, run upstream impact analysis and report callers/processes/risk. Treat `UNKNOWN` as unresolved and confirm it with text search. Warn before proceeding on HIGH/CRITICAL risk. Because a new standalone prototype should avoid existing-symbol edits, prefer that route. If production files are touched, finish with `detect_changes({scope: "all", repo: "mellowday"})`; partial/truncated output is not a clean result.

## Visual direction

Use the five concept images as layout/atmosphere references, not as screenshots to crop into UI. Buttons, text, cards, popover, window framing, backgrounds, and dividers should remain HTML/CSS. Candidate WebP/SVG files are low-frequency atmospheric decoration only.

The prototype should make the shared structure legible across sky, sakura, mint, night, and minimal-custom. The four fixed themes have fixed tokens and decoration; minimal-custom exposes its limited color controls and must render without decorative images or visible decoration DOM. Theme selection belongs in a popover, not a migrated Settings page.

## Verification target

Use native Python Playwright in headless Chromium. If a local server helper is needed, run its `--help` before using it. Verify at least:

- a desktop-window viewport representative of the Windows app;
- a narrower viewport where sidebar, theme popover, composer, and large corner art are stressed;
- a high-density transcript without content hidden behind decorations or fixed chrome;
- keyboard focus, Escape/outside-click behavior, and focus return for the theme popover;
- all five theme choices and the structural variants;
- decoration layer does not affect layout, clicking, selection, focus order, or accessible reading;
- minimal-custom makes no decorative asset request and shows no active decorative layer;
- `prefers-reduced-motion` removes nonessential motion;
- no unexpected console errors.

Capture labeled screenshots for each structural variant in at least one fixed theme, plus targeted screenshots for night and minimal-custom. End with a short verdict: what holds, what breaks at realistic density, and which AppShell/density variant should be carried into a later production issue. Do not implement the production migration in the same task.

## Suggested skills

- `prototype` — use the UI branch; keep the artifact throwaway, variant-driven, and trivial to run.
- `frontend-design` — establish a distinctive Mellowday visual direction while respecting the supplied theme concepts.
- `webapp-testing` — exercise the static/dynamic prototype with native Python Playwright and capture screenshots.
- `gitnexus-exploring` — bind `mellowday` and trace the existing Web App only as needed.
- `gitnexus-impact-analysis` — mandatory before changing existing symbols.
- `stop-that-shit` in `change` mode — keep implementation limited to the prototype and necessary verification.

## Completion handoff

Return the prototype path, one-command run instruction, screenshot paths, tested viewport/state matrix, and the design verdict. List every file changed. Do not commit unless explicitly asked; if later captured per the prototype workflow, use a throwaway branch and link the verdict from the relevant implementation issue rather than merging prototype code to main.
