# Prompt Pipeline — нативное приложение для macOS

Окно на PyQt6; логика — тот же TS-пайплайн, вызывается через мост `bridge.ts`.
Никакого дублирования кода: UI только собирает запрос и рисует ответ.

```
desktop/
├── app.py           # окно: ввод, настройки модели, результат
├── bridge.ts        # JSON на stdin → JSON на stdout (обёртка над pipeline/)
└── build_app.sh     # собирает "Prompt Pipeline.app" для запуска из Finder
```

## Сборка и запуск

```bash
./desktop/build_app.sh          # → release/Prompt Pipeline.app
open "release/Prompt Pipeline.app"
```

Или без бандла, прямо из терминала:

```bash
python3 desktop/app.py
```

Приложение работает из исходников: правишь код — перезапускаешь лончер, пересобирать не нужно.

## Требования

- macOS 12+
- Python 3.12 с PyQt6 (`python3 -m pip install PyQt6`, если нет)
- Node.js 20+ в PATH — пайплайн исполняется им

## Что умеет

- Поле «поток мыслей» → бриф → техника с обоснованием → промпт и конфиг.
- Выбор **техники** — отдельная панель в две колонки: техники сгруппированы по категориям
  (Контекст, Рассуждение, Агенты, RAG…), у каждой одна строка-подсказка «для чего лучше».
  «Авто» — пайплайн решает сам; конкретная техника — промпт собирается по её методике.
- Провайдер: Ollama (без ключа), Gemini, OpenAI. Ключ живёт только в памяти окна.
- Модель по умолчанию — `minimax-m3.1-flash:cloud`. Полный цикл с тремя вариантами — 26–35 с
  (бриф ~3 с, выбор 5–12 с, синтез 16–20 с параллельно). Локальные модели на этой машине
  отвечают дольше 2 минут — не годятся.
- Жёсткий лимит токенов ставить нельзя: облачная модель «думающая», лимит уходит на рассуждение
  и ответ приходит пустым. Ограничение длины — словами в промпте (400 слов).
- Галочка «без LLM-синтеза» — офлайн-режим, синтез без вызова модели.
- Кнопка «Копировать» и `⌘↩` для запуска.
- **1–5 вариантов техник** на выбор: каждая со своим промптом и конфигом, синтез идёт параллельно
  (три варианта занимают столько же времени, сколько один).
- Кнопка **«Отмена»** прерывает запрос (процесс моста завершается).
- **История** последних прогонов в выпадающем списке — можно вернуться к любому результату.
- Процедуры (18 техник без промпта) показываются шагами, а не притворяются техниками.
- Самопроверка вёрстки без запуска окна:

```bash
python3 desktop/app.py --screenshot /tmp/app.png
```

## Ограничения

- Список моделей берётся у демона Ollama (`GET /api/tags`, кнопка ↻ для обновления, сейчас 99);
  поле редактируемое — можно вписать имя, которого нет в списке. Если демон не отвечает,
  показывается предупреждение и остаётся резервный список.
- Один запрос за раз: пока идёт генерация, кнопка заблокирована.
- История запросов и результатов сохраняется локально в `~/Library/Application Support/Prompta/history.sqlite3` и доступна после перезапуска. Поиск сверху ищет по запросам, техникам и текстам промптов. Ключи API не сохраняются.

## Claude-specific prompts

Enable **For Claude** to generate a prompt from the saved official Anthropic rules in `claude_prompt_rules/`. This targets Claude while keeping the selected generator model unchanged. Results include clickable official sources and rule IDs, preserved in history. General guidance is checked as of 2026-11-05; model-specific configuration is not inferred.

## ChatGPT and Gemini target prompts

**For ChatGPT** and **For Gemini** use separate official rule
sets in `chatgpt_prompt_rules/` and `gemini_prompt_rules/`. Choose at most one
target, including Claude. The provider/model controls still select the generator,
not the target of the resulting prompt. All modes are off by default. Source
links, per-variant rule IDs, and rule versions are preserved in history; short
history topics and full-request search remain available. Model-specific/API
settings are not treated as universal prompting rules.

## Generation feedback and prompt defaults

The thin line below Build prompt advances only when pipeline stages or variants finish;
it measures completed stages, not time or token generation. Successful runs finish at 100%;
errors and cancellations clear the line. New results ask the model for a short natural topic
used in the heading and history. Older results retain complete wording instead of keyword fragments.
Desktop LLM generation requests an opening worked input/output example by default (one-shot),
without duplicating an existing technique example. Explicit requests to omit examples take priority;
offline synthesis and non-generative procedures do not invent demonstrations.
The example guidance comes from Google Prompt Engineering v7, pp. 15–17, saved in
`archive-org-prompting/md/google-prompt-engineering-whitepaper-v7.md`.

Every result now starts with a separate zero-shot baseline and its own Copy button.
It is assembled from the task and brief without demonstrations, additional model calls,
or reducing the requested variant count. Manual and procedure results include the same baseline;
saved older results get a baseline from their saved task when displayed.

Mouse wheel and trackpad scrolling over any result prompt moves the outer results page.
Use a prompt's own scrollbar to move within that prompt; the thoughts editor keeps its own wheel scrolling.

## Grok target prompts

**For Grok** replaces the Skip LLM synthesis toggle in the fourth grid cell. It compiles prompts using the saved official xAI text-prompt rules; the selected generator stays unchanged. The deterministic bridge/API mode remains available for existing callers.

`grok_prompt_rules/official-manual.md` combines six downloaded official guides. Original Markdown, source URLs, hashes, extracted sections and scoped rules are stored alongside it. This finite corpus is not the complete xAI website. Multi-agent recommendations are reference-only; API settings are excluded from generated prompt text.

## Settings → Library

Read-only searchable inventory of source PDFs and Markdown, the technique catalog and citation map, all four official rule bundles, original downloaded snapshots, compiler instructions and orchestration, catalog maintenance, and evaluation materials. Each entry states its actual role in generation. Snapshot entries compare their SHA-256 to the saved source registry; other files show a local fingerprint without claiming independent source verification. Missing files and hash mismatches are visible. Model settings, keys and user history are excluded from the inventory.

### Local Whisper dictation

Click the microphone in Thoughts to record; click again to stop and transcribe.
Recording is limited to five minutes. Whisper detects the spoken language and
appends text without replacing existing thoughts. Audio stays in memory; neither
audio nor transcript is uploaded by the dictation worker. Generating a prompt
still uses the provider selected in Settings.

Setup (Python 3.12):

```sh
python3.12 -m venv --system-site-packages .venv-whisper
.venv-whisper/bin/python -m pip install -r desktop/requirements-voice.txt
.venv-whisper/bin/python -c "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-small', local_dir='.whisper-models/small', allow_patterns=['config.json','model.bin','tokenizer.json','vocabulary.txt'])"
```

The runtime loads only local model files. Grant macOS microphone permission on
first use. Dependencies and model weights are excluded from Git. Implementation:
`voice_input.py`; engine documentation: https://github.com/SYSTRAN/faster-whisper.
