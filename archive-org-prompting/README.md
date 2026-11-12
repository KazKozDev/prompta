# Статьи по техникам промптинга с archive.org

Подборка документов про **техники** промптинга (а не сборники готовых промптов), скачанных с
[archive.org](https://archive.org) 2026-11-03. В репозитории — markdown-версии с извлечённым текстом; оригинальные PDF
по ссылкам в таблице.

Все PDF свободно скачиваются (не borrow-only), лицензии указаны в front matter каждого `.md`.

Одно исключение: [The Prompt Report](https://arxiv.org/abs/2406.06608) взят с arXiv (CC BY 4.0) —
полного каталога техник на archive.org нет, а без него карта упиралась в 17 техник.

```
archive-org-prompting/
├── pdf/               8 PDF-оригиналов, 27 MB — только локально, в git не хранятся (ссылки в таблице)
├── md/                8 markdown-файлов, 760 KB — текст с разметкой страниц <!-- page N -->
├── techniques-map.md  сводная карта техник: где описана → для чего подходит → пример промпта
└── README.md
```

## Что внутри

| Документ | Автор, год | Стр. | О чём |
|---|---|---|---|
| [Prompt Engineering (Google whitepaper v7)](md/google-prompt-engineering-whitepaper-v7.md) · [PDF](https://archive.org/download/22365-3-prompt-engineering-v-7/22365_3_Prompt%20Engineering_v7%20%281%29.pdf) | Lee Boonstra, Google, 2025 | 68 | Самый системный текст в подборке: temperature / top-K / top-P, zero-shot и few-shot, system / role / contextual prompting, step-back, chain-of-thought, self-consistency, tree-of-thoughts, ReAct, automatic prompt engineering, best practices |
| [Review of Prompt Engineering Techniques in Finance: CoT, ToT, GoT](md/review-prompt-techniques-cot-tot-got.md) · [PDF](https://archive.org/download/review-of-prompt-engineering-techniques-in-finance-a-evaluation-of-chain-of-thou/Review_of_Prompt_Engineering_Techniques_in_Finance_A_Evaluation_of_Chain_of_Thought_Tree_of_Thought_and_Graph_of_Thought_Approaches.pdf) | Satyadhar Joshi, 2025 | 17 | Рецензируемая статья (IJIRCST 13(4), стр. 51–67): сравнение chain-of-thought, tree-of-thought и graph-of-thought, метрики оценки, применения в финансах, 100+ источников |
| [Prompt Engineering for Students of Medicine and Their Teachers](md/heston-prompt-engineering-medicine-2023.md) · [PDF](https://archive.org/download/prompt-engineering-for-students-of-medicine-and-their-teachers/Prompt%20Engineering%20for%20Students%20of%20Medicine%20and%20Their%20Teachers.pdf) | Thomas F. Heston, 2023 | 95 | Книга: анатомия хорошего промпта, типы промптов, стратегии проектирования, оценка эффективности, внедрение в преподавание |
| [Prompt Engineering in Medical Education](md/prompt-engineering-in-medical-education.md) · [PDF](https://archive.org/download/prompt-engineering-medical-education/ime-02-00019.pdf) | Heston & Khun, 2023 | 8 | Короткий обзор-таксономия техник (журнал IME) — удобно как быстрый конспект |
| [Prompt Engineering](md/antor-shah-prompt-engineering.md) · [PDF](https://archive.org/download/prompt-engineering/prompt%20engineering.pdf) | Antor Shah, 2025 | 12 | Введение: базовые техники, prompt chaining, RAG, роли. CC BY |
| [Prompt Engineering Guide: A Practical Beginner's Handbook](md/practical-beginners-handbook-ai.md) · [PDF](https://archive.org/download/a-practical-beginners-handbook-for-working-with-ai/A%20Practical%20Beginner%27s%20Handbook%20for%20Working%20with%20AI%20.pdf) | Sakhaoat, 2026 | 16 | Практическое пособие: структура промпта, zero-/few-shot, роли, примеры. CC0 |
| [The Art of Prompt Engineering with ChatGPT](md/nathan-hunter-art-of-prompt-engineering.md) · [PDF](https://archive.org/download/the-art-of-prompt-engineering-with-chat-gpt-a-hands-on-guide-nathan-hunter-dr-furqan-library/The%20Art%20of%20Prompt%20Engineering%20with%20chatGPT%20A%20Hands-On%20Guide%20%28Nathan%20Hunter%29%20%28Dr%20Furqan-Library%29.pdf) | Nathan Hunter, 2023 | 91 | Hands-on по ChatGPT: итерации, сценарии, персонажи, обход ограничений модели |
| [The Prompt Report: A Systematic Survey](md/the-prompt-report-arxiv-2406.06608.md) · [PDF](https://arxiv.org/pdf/2406.06608v6) | Schulhoff et al., 2025, arXiv (CC BY 4.0) | 80 | Каталог: 58 текстовых техник + 40 для других модальностей, словарь из 33 терминов, мета-анализ. Источник раздела 6 карты |

Сводка по техникам из этих документов — [techniques-map.md](techniques-map.md): 96 строк, ~85 техник
в таблицах «техника → где описана (страница или §) → для чего подходит → пример промпта»,
10 развёрнутых примеров, сравнение CoT / ToT / GoT и правило выбора техники под задачу.

Быстрый маршрут: начать с Google whitepaper (разделы про zero/few-shot и CoT), затем статья
про CoT/ToT/GoT для сравнения подходов, остальное — по мере надобности.

## Как это собиралось

1. Поиск через Advanced Search API archive.org по запросам `"prompt engineering"`,
   `"prompting techniques"`, `"few-shot prompting"`, `"chain of thought prompting"`,
   `title:("prompt engineering")` с фильтром `mediatype:texts`.
2. Отбор вручную: только тексты про техники, без «1000 промптов», маркетинговых PDF и
   image-prompt-библиотек. Дубликаты и переводы отброшены.
3. Скачивание файлов формата `Text PDF` через `https://archive.org/download/<id>/<file>`.
4. Текст извлечён `pdftotext` (poppler) без `-layout` — так сохраняется порядок чтения колонок
   в двухколоночных статьях. Страницы помечены `<!-- page N -->`.

## Ограничения

- Markdown — автоматическое извлечение: **таблицы, диаграммы и отступы в код-блоках искажены**.
  Для точных формулировок промптов сверяйтесь с PDF (поле `pdf_local` во front matter).
- Нумерация страниц, колонтитулы и номера страниц остались в тексте как есть — специально не
  вычищались, чтобы не потерять содержимое.
- `ultimate-guide-prompt-engineering-genai` (слайдовый PDF 8 стр.) исключён: колоночная вёрстка
  слайдов не восстанавливается в читаемый текст.

## Что ещё есть на archive.org по теме (не взято)

- `whitepaper-prompt-engineering-v-4` — та же книга Google, версия v4 (v7 новее, взят он).
- `promptengineering_202401`, `the-power-of-prompt`, `unlock-gpt-potential` — наборы готовых
  промптов и компиляции, не техники.
- `ai-image-prompt-bible-2026` — промпты для генерации изображений, другая тема.
- `ERIC_ED*`, `micro_IA*` — офлайн-микрофиши 1970–80-х про «prompting» в педагогике
  (подсказки ученикам), к LLM отношения не имеют.
