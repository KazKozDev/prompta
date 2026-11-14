# Prompta desktop app

A PyQt6 window over the same TypeScript pipeline as the CLI and MCP server. The UI collects the request
and draws the result; `bridge.ts` passes JSON to the pipeline and back, so no pipeline logic lives in Python.

## Run

```bash
./desktop/build_app.sh && open release/Prompta.app
```

Or straight from the terminal:

```bash
python3 desktop/app.py
```

## Standalone app (to give to others)

```bash
./desktop/build_standalone.sh
```

Builds `release/standalone/Prompta.app` and `Prompta.dmg` with their own Python, PyQt6 and Node: the
Mac it runs on needs nothing installed. Build needs `python3 -m pip install -r desktop/requirements.txt` and an
official Node build (nodejs.org; a Homebrew node links Homebrew libraries and is refused). CI builds the
same dmg as the `Prompta-dmg` artifact.

- Apple Silicon only; the minimum macOS is read from the bundled binaries (13.5 now).
- Signed ad hoc, not notarized (that needs an Apple Developer account). On another Mac the first launch
  is blocked: System Settings → Privacy & Security → **Open Anyway**.
- No dictation: Whisper and its model are ~500 MB. The microphone says so.
- MCP installs point into the app bundle: keep it in /Applications, reinstall after moving it.

## Releasing

One version for the whole project: `APP_VERSION` in `desktop/app.py` and `version` in `package.json`
(`test_version.py` keeps them equal). To publish:

1. Bump both to the new version and commit.
2. Tag the commit `v<version>` (for example `git tag v0.2.0`) and push the tag.

`.github/workflows/release.yml` then checks the tag against both versions, runs the tests, builds the standalone
dmg and attaches it to a GitHub release with generated notes.

## Development

The app runs from source: edit the code and relaunch, no rebuild needed. Rebuild the bundle only to get
the microphone helper (see dictation below).

Only one copy runs at a time: launching again brings the open window forward.

Screens without showing a window — the main window with a demo result and every Settings tab, in a
throwaway HOME (no history, settings, Keychain or network), so the pictures are the same on every run:

```bash
python3 desktop/screenshots.py /tmp/prompta-screens
```

CI uploads the same set as the `screens` artifact of the `app-bundle` job.
`python3 desktop/app.py --screenshot /tmp/app.png` renders the main window with your own settings and the live catalog.

Tests, as CI runs them: `cd desktop && python3 -m pytest -q test_history.py test_app.py test_mcp_settings.py test_single_instance.py`
for the UI (offscreen Qt), `npm test` for the bridge.

## Files

| File | Role |
| --- | --- |
| `app.py` | Main window `PromptaWindow`: input, settings, result, wiring |
| `history_view.py` · `history.py` | History in the window; local SQLite store and retention policy |
| `result_view.py` | Result layout: collapsible blocks, chips, captions |
| `controls.py` · `widgets.py` | Dropdowns, technique cards, variant picker, editors, dictation button |
| `workers.py` | Background threads: bridge calls, model and technique loading |
| `app.qss` · `theme.py` | The one stylesheet (every widget rule); `theme.py` loads it, plus prompt targets and chat URLs |
| `single_instance.py` | Keeps one running copy; a second launch brings it forward |
| `screenshots.py` | Offscreen PNGs of the main screens (local check and CI artifact) |
| `keychain.py` | API keys in the macOS login Keychain via `security` (stdin, never argv) |
| `library.py` · `mcp_settings.py` | Settings → Library and Settings → MCP server |
| `voice_input.py` · `mic_helper.c` | Whisper dictation worker and the `prompta-mic` microphone helper |
| `qt_log.py` | Filters two known Qt accessibility messages |
| `bridge.ts` | JSON on stdin → JSON on stdout, a wrapper over `pipeline/` |
| `build_app.sh` · `make_icon.py` | Builds `release/Prompta.app` (a launcher over the sources) and its icon |
| `build_standalone.sh` | Builds the self-contained `release/standalone/Prompta.app` and `.dmg` |

## Keys and history

- Keys stay in memory unless **Remember in Keychain** is on; then each provider's key is one Keychain
  item under the service `Prompta`.
- History is in `~/Library/Application Support/Prompta/history.sqlite3`, readable only by your account,
  without API keys. **Settings → History** sets size and age limits and has **Delete all history…**,
  which removes the database file. `PROMPTA_HISTORY_MAX` and `PROMPTA_HISTORY_DAYS` override it.

## Local Whisper dictation

Click the microphone in Thoughts to record, click again to stop and transcribe. Recording is limited to
five minutes. Whisper detects the language and appends text to the thoughts. Audio stays in memory and
nothing is uploaded by the dictation worker.

Setup (Python 3.12):

```sh
python3.12 -m venv --system-site-packages .venv-whisper
.venv-whisper/bin/python -m pip install -r desktop/requirements-voice.txt
.venv-whisper/bin/python -c "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-small', local_dir='.whisper-models/small', allow_patterns=['config.json','model.bin','tokenizer.json','vocabulary.txt'])"
```

Build the bundle once (`./desktop/build_app.sh`): it compiles `prompta-mic`, which carries the
microphone usage text the system Python lacks. Without it macOS records silence and never asks for
permission. Model weights and dependencies are not in Git.

## Console noise

macOS accessibility features poll text fields, and Qt 6 may print hundreds of lines like
`QTextCursor::setPosition: Position 'N' out of range` and `qt.accessibility.table: Cell requested … out of bounds`.
They do not affect the app; `qt_log.py` hides only these two. Full Qt output:
`PROMPTA_QT_DEBUG=1 python3 desktop/app.py`.
