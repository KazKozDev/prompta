import type { PipelineResult } from './types.ts';

/** Чистый рендер результата пайплайна в HTML — без React, чтобы можно было тестировать и превьюить. */

export function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] as string);
}

export function shortTokens(maxTokens: string): string {
  const head = maxTokens.split('(')[0].trim();
  return head.length <= 12 ? head : maxTokens;
}

export function renderPipelineResult(result: PipelineResult): string {
  const { brief, choice, synthesis } = result;
  const cfg = synthesis.config;
  const confidence = Math.round(choice.confidence * 100);

  const chips = [
    ['тип', brief.task_type],
    ['язык', brief.language],
    ['цена ошибки', brief.stakes],
  ]
    .map(([label, value]) => `<span class="pipeline-chip">${label}: <b>${escapeHtml(value)}</b></span>`)
    .join('');

  const alternativeCards = (result.alternatives ?? [])
    .map((alt, index) => {
      const altWarnings = [...new Set(alt.synthesis.warnings)];
      return `
      <div class="pipeline-alt">
        <div class="pipeline-alt-head">
          <span class="pipeline-alt-title">Вариант ${index + 2}: ${escapeHtml(alt.choice.name)}</span>
          <span class="pipeline-chip">${escapeHtml(alt.choice.key)}</span>
          <span class="pipeline-confidence">${Math.round(alt.choice.confidence * 100)}%</span>
        </div>
        <p class="pipeline-why">${escapeHtml(alt.choice.reason)}</p>
        <pre class="pipeline-prompt">${escapeHtml(alt.synthesis.prompt)}</pre>
        <p class="pipeline-note">
          temperature ${alt.synthesis.config.temperature ?? '—'} · ${escapeHtml(alt.synthesis.config.max_tokens)}
        </p>
        ${altWarnings.length ? `<ul class="pipeline-warnings">${altWarnings.map((w) => `<li>${escapeHtml(w)}</li>`).join('')}</ul>` : ''}
      </div>`;
    })
    .join('');

  const uniqueWarnings = [...new Set(synthesis.warnings)];
  const warnings = uniqueWarnings.length
    ? `<ul class="pipeline-warnings">${uniqueWarnings.map((w) => `<li>${escapeHtml(w)}</li>`).join('')}</ul>`
    : '';

  return `
    <div class="pipeline-card">
      <p class="pipeline-goal">${escapeHtml(brief.goal)}</p>
      <div class="pipeline-chips">${chips}</div>
      <p class="pipeline-note"><b>Формат:</b> ${escapeHtml(brief.output_format)}</p>
      ${brief.assumptions.length ? `<p class="pipeline-note">Допущения: ${brief.assumptions.map(escapeHtml).join('; ')}</p>` : ''}

      <div class="pipeline-technique">
        <div class="pipeline-technique-head">
          <span class="pipeline-technique-name">${escapeHtml(choice.name)}</span>
          <span class="pipeline-technique-key">${escapeHtml(choice.key)}</span>
          <span class="pipeline-confidence">уверенность ${confidence}%</span>
        </div>
        <div class="pipeline-bar"><span style="width: ${confidence}%"></span></div>
        <p class="pipeline-why"><b>Почему:</b> ${escapeHtml(choice.reason)}</p>
        <p class="pipeline-why"><b>Почему не дешевле:</b> ${escapeHtml(choice.whyNotCheaper)}</p>
      </div>

      <div class="pipeline-prompt-wrap">
        <div class="pipeline-prompt-bar">
          <span>Промпт</span>
          <button class="pipeline-copy" type="button" data-copy>Копировать</button>
        </div>
        <pre class="pipeline-prompt">${escapeHtml(synthesis.prompt)}</pre>
      </div>

      <div class="pipeline-config">
        <div class="pipeline-tile">
          <span class="pipeline-tile-label">temperature</span>
          <span class="pipeline-tile-value">${cfg.temperature ?? '—'}</span>
        </div>
        <div class="pipeline-tile">
          <span class="pipeline-tile-label">top_p</span>
          <span class="pipeline-tile-value">${cfg.top_p ?? '—'}</span>
        </div>
        <div class="pipeline-tile">
          <span class="pipeline-tile-label">max_tokens</span>
          <span class="pipeline-tile-value">${escapeHtml(shortTokens(cfg.max_tokens))}</span>
        </div>
      </div>
      <p class="pipeline-note">${escapeHtml(cfg.rationale)}</p>
      ${warnings}
      <p class="pipeline-footer">отсеяно до выбора: ${result.rejected.length} техник</p>
      ${alternativeCards}
    </div>`;
}

