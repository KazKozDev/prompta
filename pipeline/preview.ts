import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { loadCatalog } from './catalog.ts';
import { runPipeline } from './index.ts';
import { renderPipelineResult } from './render.ts';

/** Превью карточки результата без LLM: гоняет пайплайн на фейковой модели
 *  и пишет HTML со стилями приложения. Открыть в браузере — увидеть вёрстку. */

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const catalog = loadCatalog(JSON.parse(readFileSync(join(root, 'catalog', 'catalog.json'), 'utf8')));

const BRIEF = JSON.stringify({
  goal: 'Разбирать заметки после встреч: вытащить решения, задачи и ответственных в таблицу',
  task_type: 'extraction',
  input: 'текст заметок на русском',
  output_format: 'markdown-таблица: Тип | Формулировка | Ответственный',
  constraints: ['извлекать только явно сказанное', 'не выдумывать ответственных'],
  language: 'ru',
  modality: 'text',
  stakes: 'high',
  assumptions: ['заметки приходят текстом, не аудио'],
  budget_calls: 1,
});

const CHOICE = JSON.stringify({
  key: 'contextual_prompting',
  reason: 'Задача заземлена на конкретном материале: заметки вставляются в промпт, ответ ограничен только ими.',
  confidence: 0.82,
  whyNotCheaper: 'zero_shot не удержит формат таблицы и границу «решение vs задача», few_shot — нет примеров в брифе.',
});

const fake = async (prompt: string): Promise<string> => {
  if (prompt.includes('Поток мыслей')) return BRIEF;
  if (prompt.includes('Доступные техники')) return CHOICE;
  return 'промпт';
};

const result = await runPipeline({
  thoughts: 'разбираю заметки после встреч',
  catalog,
  llm: fake,
  mode: 'deterministic',
});

result.synthesis.warnings.push('каркас техники на английском: в LLM-режиме он будет переведён на ru');
result.synthesis.warnings.push('нечем заполнить: examples — подставь вручную');

const card = renderPipelineResult(result);

const html = `<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>preview</title>
<link rel="stylesheet" href="http://localhost:3000/index.css">
</head>
<body>
  <div id="app" style="padding: 24px 30px">
    <section id="pipeline-section">
      <div class="pipeline-head">
        <h2><span class="material-symbols-outlined">route</span> Пайплайн: поток мыслей → промпт <span class="pipeline-badge">beta</span></h2>
        <p class="pipeline-hint">Опиши как думаешь, без структуры. Пайплайн соберёт бриф, отсеет неподходящие техники по каталогу и вернёт промпт с обоснованным конфигом.</p>
      </div>
      <div class="pipeline-grid">
        <div class="pipeline-input-col">
          <label for="pipeline-thoughts">Поток мыслей</label>
          <textarea id="pipeline-thoughts" rows="6">хочу чтобы нейросеть разбирала мои заметки после встреч и вытаскивала решения, задачи и ответственных в таблицу</textarea>
          <div class="pipeline-controls">
            <button class="pipeline-primary" type="button">Собрать промпт</button>
            <label class="pipeline-toggle"><input type="checkbox"><span>без LLM-синтеза</span></label>
          </div>
          <p class="pipeline-status">System prompting · предупреждений: 2</p>
        </div>
        <div class="pipeline-output">${card}</div>
      </div>
    </section>
  </div>
</body></html>`;

writeFileSync('/tmp/preview.html', html);
console.log('превью записано: /tmp/preview.html');
