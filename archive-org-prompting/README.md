# Papers on prompting techniques from archive.org

A collection of documents about prompting **techniques** (not collections of ready-made prompts), downloaded from
[archive.org](https://archive.org) on 2026-11-03. The repository holds markdown versions with the extracted text; the original PDFs
are linked in the table.

All PDFs download freely (not borrow-only); licences are given in the front matter of each `.md`.

One exception: [The Prompt Report](https://arxiv.org/abs/2406.06608) was taken from arXiv (CC BY 4.0) —
archive.org has no full catalog of techniques, and without it the map was stuck at 17 techniques.

```
archive-org-prompting/
├── pdf/               8 original PDFs, 27 MB — local only, not stored in git (links in the table)
├── md/                8 markdown files, 760 KB — text with <!-- page N --> page markers
├── techniques-map.md  summary map of techniques: where described → what it suits → prompt example
└── README.md
```

## What's inside

| Document | Author, year | Pages | About |
|---|---|---|---|
| [Prompt Engineering (Google whitepaper v7)](md/google-prompt-engineering-whitepaper-v7.md) · [PDF](https://archive.org/download/22365-3-prompt-engineering-v-7/22365_3_Prompt%20Engineering_v7%20%281%29.pdf) | Lee Boonstra, Google, 2025 | 68 | The most systematic text in the collection: temperature / top-K / top-P, zero-shot and few-shot, system / role / contextual prompting, step-back, chain-of-thought, self-consistency, tree-of-thoughts, ReAct, automatic prompt engineering, best practices |
| [Review of Prompt Engineering Techniques in Finance: CoT, ToT, GoT](md/review-prompt-techniques-cot-tot-got.md) · [PDF](https://archive.org/download/review-of-prompt-engineering-techniques-in-finance-a-evaluation-of-chain-of-thou/Review_of_Prompt_Engineering_Techniques_in_Finance_A_Evaluation_of_Chain_of_Thought_Tree_of_Thought_and_Graph_of_Thought_Approaches.pdf) | Satyadhar Joshi, 2025 | 17 | Peer-reviewed article (IJIRCST 13(4), pp. 51–67): a comparison of chain-of-thought, tree-of-thought and graph-of-thought, evaluation metrics, applications in finance, 100+ references |
| [Prompt Engineering for Students of Medicine and Their Teachers](md/heston-prompt-engineering-medicine-2023.md) · [PDF](https://archive.org/download/prompt-engineering-for-students-of-medicine-and-their-teachers/Prompt%20Engineering%20for%20Students%20of%20Medicine%20and%20Their%20Teachers.pdf) | Thomas F. Heston, 2023 | 95 | A book: the anatomy of a good prompt, prompt types, design strategies, evaluating effectiveness, bringing it into teaching |
| [Prompt Engineering in Medical Education](md/prompt-engineering-in-medical-education.md) · [PDF](https://archive.org/download/prompt-engineering-medical-education/ime-02-00019.pdf) | Heston & Khun, 2023 | 8 | A short review and taxonomy of techniques (IME journal) — handy as a quick summary |
| [Prompt Engineering](md/antor-shah-prompt-engineering.md) · [PDF](https://archive.org/download/prompt-engineering/prompt%20engineering.pdf) | Antor Shah, 2025 | 12 | An introduction: basic techniques, prompt chaining, RAG, roles. CC BY |
| [Prompt Engineering Guide: A Practical Beginner's Handbook](md/practical-beginners-handbook-ai.md) · [PDF](https://archive.org/download/a-practical-beginners-handbook-for-working-with-ai/A%20Practical%20Beginner%27s%20Handbook%20for%20Working%20with%20AI%20.pdf) | Sakhaoat, 2026 | 16 | A practical handbook: prompt structure, zero-/few-shot, roles, examples. CC0 |
| [The Art of Prompt Engineering with ChatGPT](md/nathan-hunter-art-of-prompt-engineering.md) · [PDF](https://archive.org/download/the-art-of-prompt-engineering-with-chat-gpt-a-hands-on-guide-nathan-hunter-dr-furqan-library/The%20Art%20of%20Prompt%20Engineering%20with%20chatGPT%20A%20Hands-On%20Guide%20%28Nathan%20Hunter%29%20%28Dr%20Furqan-Library%29.pdf) | Nathan Hunter, 2023 | 91 | Hands-on with ChatGPT: iterations, scenarios, personas, working around the model's restrictions |
| [The Prompt Report: A Systematic Survey](md/the-prompt-report-arxiv-2406.06608.md) · [PDF](https://arxiv.org/pdf/2406.06608v6) | Schulhoff et al., 2025, arXiv (CC BY 4.0) | 80 | A catalog: 58 text techniques + 40 for other modalities, a glossary of 33 terms, a meta-analysis. The source of section 6 of the map |

The technique summary from these documents is [techniques-map.md](techniques-map.md): 96 rows, ~85 techniques
in "technique → where described (page or §) → what it suits → prompt example" tables,
10 expanded examples, a CoT / ToT / GoT comparison and a rule for choosing a technique for a task.

Quick route: start with the Google whitepaper (the zero/few-shot and CoT sections), then the article
on CoT/ToT/GoT to compare approaches, and the rest as needed.

## How it was assembled

1. Search through the archive.org Advanced Search API for `"prompt engineering"`,
   `"prompting techniques"`, `"few-shot prompting"`, `"chain of thought prompting"`,
   `title:("prompt engineering")` with the `mediatype:texts` filter.
2. Manual selection: only texts about techniques, no "1000 prompts", marketing PDFs or
   image-prompt libraries. Duplicates and translations were dropped.
3. Downloading the `Text PDF` files via `https://archive.org/download/<id>/<file>`.
4. Text extracted with `pdftotext` (poppler) without `-layout`, which keeps the reading order of columns
   in two-column articles. Pages are marked `<!-- page N -->`.

## Limitations

- The markdown is an automatic extraction: **tables, diagrams and indentation in code blocks are garbled**.
  For exact prompt wording check the PDF (the `pdf_local` field in the front matter).
- Page numbering, running headers and page numbers stay in the text as is — deliberately not
  cleaned up, so no content is lost.
- `ultimate-guide-prompt-engineering-genai` (an 8-page slide PDF) is excluded: the slides' column layout
  cannot be recovered into readable text.

## What else archive.org has on the topic (not taken)

- `whitepaper-prompt-engineering-v-4` — the same Google book, version v4 (v7 is newer and was taken).
- `promptengineering_202401`, `the-power-of-prompt`, `unlock-gpt-potential` — sets of ready-made
  prompts and compilations, not techniques.
- `ai-image-prompt-bible-2026` — prompts for image generation, a different topic.
- `ERIC_ED*`, `micro_IA*` — offline microfiche from the 1970s–80s about "prompting" in pedagogy
  (cues for students), unrelated to LLMs.
