# Mellowday AppShell throwaway prototype

Original question: which AppShell structure still works for Mellowday at realistic chat density on desktop and narrow windows?

Final bounded question: does the accepted A+C structure still satisfy its layout and accessibility contracts when Rail/Dock focus state, hash-routed Life and Settings subnavigation, responsive boundaries, overlay focus behavior, and theme decoration coexist?

Run the existing application from the repository root:

```powershell
python -m mellowday serve
```

Then open:

```text
http://127.0.0.1:8000/static/prototypes/app-shell/index.html?variant=A
```

Use `variant=A`, `variant=B`, or `variant=C`; final validation targets `variant=A`. Product routes use hashes such as `#/conversation`, `#/life/tasks`, and `#/settings/appearance`. The page reads Conversation History through the existing GET endpoints. Sending, navigation, theme changes, and all other controls use memory-only prototype state. If no stored conversation has enough material, a clearly labeled density fixture is added in memory.

With the server already running, reproduce the final browser matrix with:

```powershell
python src/mellowday/web_app/static/prototypes/app-shell/final_validation.py
```

The verdict and screenshots are in `docs/prototype/mellowday-ui-final-validation-verdict-handoff.md` and `docs/prototype/screenshots/app-shell-final/`.

This directory is a throwaway prototype, not production UI or packaged static content.
