import { buildZeroShotPrompt } from './zero-shot.ts';
import { isOfficialSourceUrl } from './official.ts';
import { briefAssumptions } from './brief.ts';
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
  const target = result.claudeGuidance ? 'claude' : result.chatgptGuidance ? 'chatgpt' : result.geminiGuidance ? 'gemini' : result.grokGuidance ? 'grok' : undefined;
  const guidance = result.claudeGuidance ?? result.chatgptGuidance ?? result.geminiGuidance ?? result.grokGuidance;
  const targetLabel = target === 'claude' ? 'Claude' : target === 'chatgpt' ? 'ChatGPT' : target === 'grok' ? 'Grok' : 'Gemini';

  const chips = [
    ['type', brief.task_type],
    ['language', brief.language],
    ['stakes', brief.stakes],
  ]
    .map(([label, value]) => `<span class="pipeline-chip">${label}: <b>${escapeHtml(value)}</b></span>`)
    .join('');

  const alternativeCards = (result.alternatives ?? [])
    .map((alt, index) => {
      const altWarnings = [...new Set(alt.synthesis.warnings)];
      return `
      <div class="pipeline-alt">
        <div class="pipeline-alt-head">
          <span class="pipeline-alt-title">Variant ${index + 2}: ${escapeHtml(alt.choice.name)}</span>
          <span class="pipeline-confidence">${guidance ? 'Official sources' : `${Math.round(alt.choice.confidence * 100)}%`}</span>
        </div>
        <p class="pipeline-why">${escapeHtml(alt.choice.reason)}</p>
        <div class="pipeline-prompt-wrap">
          <div class="pipeline-prompt-bar">
            <span>Prompt</span>
            <button class="pipeline-copy" type="button" data-copy>Copy</button>
          </div>
          <pre class="pipeline-prompt">${escapeHtml(alt.synthesis.prompt)}</pre>
        </div>
        <p class="pipeline-note">
          temperature ${alt.synthesis.config.temperature ?? '—'} · ${escapeHtml(alt.synthesis.config.max_tokens)}
        </p>
        ${altWarnings.length ? `<ul class="pipeline-warnings">${altWarnings.map((w) => `<li>${escapeHtml(w)}</li>`).join('')}</ul>` : ''}
      </div>`;
    })
    .join('');

  const sources = guidance && target ? `<details class="pipeline-sources"><summary>${targetLabel} rules · ${escapeHtml(guidance.rule_set_version)} · checked ${escapeHtml(guidance.verified_at)}</summary>
    ${guidance.variants.map((v, index) => `<p class="pipeline-note">Variant ${index + 1} rules: ${v.rule_ids.map(escapeHtml).join(', ')}</p>`).join('')}
    <ul>${guidance.rules.filter((r) => isOfficialSourceUrl(r.source_url, target)).map((r) => `<li><a href="${escapeHtml(r.source_url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(r.id)} · ${escapeHtml(r.source_section)}</a></li>`).join('')}</ul></details>` : '';
  const uniqueWarnings = [...new Set(synthesis.warnings)];
  const warnings = uniqueWarnings.length
    ? `<ul class="pipeline-warnings">${uniqueWarnings.map((w) => `<li>${escapeHtml(w)}</li>`).join('')}</ul>`
    : '';

  return `
    <div class="pipeline-card">
      <p class="pipeline-goal">${escapeHtml(brief.goal)}</p>
      <div class="pipeline-chips">${chips}</div>
      <p class="pipeline-note"><b>Format:</b> ${escapeHtml(brief.output_format)}</p>
      ${briefAssumptions(brief).length ? `<p class="pipeline-note">Assumptions: ${briefAssumptions(brief).map(escapeHtml).join('; ')}</p>` : ''}

      <div class="pipeline-prompt-wrap">
        <div class="pipeline-prompt-bar">
          <span>Zero-shot · baseline prompt</span>
          <button class="pipeline-copy" type="button" data-copy>Copy</button>
        </div>
        <pre class="pipeline-prompt">${escapeHtml(result.zeroShotPrompt ?? buildZeroShotPrompt('', brief))}</pre>
      </div>
      <div class="pipeline-technique">
        <div class="pipeline-technique-head">
          <span class="pipeline-technique-name">${escapeHtml(choice.name)}</span>
          <span class="pipeline-confidence">${guidance ? 'Official sources' : `confidence ${confidence}%`}</span>
        </div>
        ${guidance ? '' : `<div class="pipeline-bar"><span style="width: ${confidence}%"></span></div>`}
        <p class="pipeline-why"><b>Why:</b> ${escapeHtml(choice.reason)}</p>
        <p class="pipeline-why"><b>Why not a cheaper method:</b> ${escapeHtml(choice.whyNotCheaper)}</p>
      </div>

      <div class="pipeline-prompt-wrap">
        <div class="pipeline-prompt-bar">
          <span>Prompt</span>
          <button class="pipeline-copy" type="button" data-copy>Copy</button>
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
      <p class="pipeline-footer">Techniques filtered out: ${result.rejected.length}</p>
      ${alternativeCards}
      ${sources}
    </div>`;
}

