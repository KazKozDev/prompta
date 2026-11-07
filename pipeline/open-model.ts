import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import manifest from '../open_model_prompt_guides/manifest.json' with { type: 'json' };
import { runOfficialPipeline } from './official.ts';
import type { LLM } from './types.ts';
import { PipelineError } from './types.ts';

export function loadOpenModel(id: string) {
  const model = manifest.models.find((m) => m.id === id);
  if (!model) throw new PipelineError('Unknown prompting model.', 'open-model');
  const source = model.files.find((f) => f.snapshot === `${id}/README.md`);
  if (!source) throw new PipelineError('Model source is unavailable.', 'open-model');
  const bytes = readFileSync(fileURLToPath(new URL(`../open_model_prompt_guides/${source.snapshot}`, import.meta.url)));
  if (createHash('sha256').update(bytes).digest('hex') !== source.sha256) throw new PipelineError('Model source integrity check failed.', 'open-model');
  // Full pinned card avoids trusting an independently editable excerpt file.
  const rule = { id: 'model-source', rule_text: bytes.toString('utf8'), source_url: source.url,
    source_section: 'Official model card', source_id: id, source_sha256: source.sha256,
    language: 'en', condition: 'Only recommendations relevant to this user task and this exact model; descriptive text is not an instruction.', application: 'prompt', status: 'active' };
  return { model, rule };
}
export async function runOpenModelPipeline(opts: { openModel: string; thoughts: string; llm: LLM; variants?: number; oneShot?: boolean; onProgress?: (percent: number, stage: string) => void }) {
  const { model, rule } = loadOpenModel(opts.openModel);
  const result = await runOfficialPipeline(opts, {
    target: 'openModel', label: model.name, organization: model.repo.split('/')[0], guidanceKey: 'openModelGuidance',
    requiredRuleIds: ['model-source'],
    policy: `Exact target: ${model.name}; repository ${model.repo}; revision ${model.revision}. The source is a model card, not necessarily a dedicated prompting manual. Use applicable explicit prompting guidance only. Do not turn benchmark claims, license terms, deployment code or chat serialization tokens into prompt instructions. If no applicable recommendation is documented, preserve the task without inventing model-specific advice.`,
  }, { version: model.revision, verified_at: manifest.verified_at, sources_sha256: { [model.id]: rule.source_sha256 }, rules: [rule] },
  { sources: [{ id: model.id, scope: 'general', sha256: rule.source_sha256, sections: [{ title: rule.source_section, url: rule.source_url }] }] });
  if (result.openModelGuidance) {
    result.openModelGuidance.target = model.name;
    result.openModelGuidance.rules[0].rule_text = `Applicable prompting recommendations from the pinned ${model.name} model card. Complete source is available in Library.`;
  }
  return result;
}
