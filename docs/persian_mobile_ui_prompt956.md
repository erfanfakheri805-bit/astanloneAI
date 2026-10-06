# Prompt 956 - Persian-first mobile UI

Scope: presentation only. No Python production module was changed; every file pinned by
Prompts 954/955 (`android_entry.py`, `core/core.py`, `interface/server.py`, ...) is
byte-identical.

## What changed

| Area | Files |
| --- | --- |
| Chat page (Persian, RTL, one portrait column, bottom composer, info bottom-sheet) | `app/src/main/python/interface/static/index.html`, `style.css`, `app.js` |
| Persian string table + display-only conversions | `app/src/main/python/interface/static/i18n.js` (new) |
| Android: portrait, `adjustResize`, RTL support, Persian app label, dark theme | `AndroidManifest.xml`, `res/values/strings.xml`, `styles.xml`, `colors.xml` (new), `res/layout/activity_main.xml`, `MainActivity.java` |
| Tests | `tests/test_persian_mobile_ui_prompt956.py` |

## Behaviour notes

* The page talks only to the existing local routes (`GET /api/status`, `POST /api/message`).
* Replies are inserted with `textContent`; each bubble uses `dir="auto"` + `unicode-bidi: plaintext`,
  so Persian, English, code and URLs are each laid out in their natural direction.
* `i18n.js` maps a fixed list of the runtime's English reply templates (AEL results, the
  conversation fallback, the greeting skill, ...) to Persian **for display only**. Names and quoted
  text are carried over unchanged; any reply that matches no template is shown exactly as the runtime
  produced it. The runtime's own strings (in frozen, hash-pinned modules) are not edited.
* The greeting lists only what the runtime really does today (simple conversation, remembering what
  the user teaches, running AEL commands) and says abilities grow gradually.
* Portrait is set on the single launcher activity; the soft keyboard resizes the WebView
  (`adjustResize`, `100dvh`, `interactive-widget=resizes-content`) so the composer stays visible.
* No external AI service, API key, model file or remote resource was added.
