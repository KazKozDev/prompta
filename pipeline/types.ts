import type { OfficialGuidance } from './official.ts';
/** Контракты пайплайна «поток мыслей → промпт».
 *
 *  Все модули пайплайна — чистые функции: LLM передаётся как зависимость,
 *  поэтому логика тестируется без сети и без UI.
 */

export type Kind = 'technique' | 'setting' | 'prompt_type' | 'risk' | 'procedure';
export type Status = 'ready' | 'procedure' | 'index-only';
export type Execution =
  | 'single_call'
  | 'multi_step'
  | 'n_calls_vote'
  | 'tool_loop'
  | 'optimizer_loop'
  | 'postprocess'
  | 'none';
export type Modality = 'text' | 'image' | 'audio' | 'video';
export type Stakes = 'low' | 'medium' | 'high';

export interface TechniqueConfig {
  temperature: number | null;
  top_p: number | null;
  max_tokens_hint?: string;
  rationale: string;
}

export interface Technique {
  key: string;
  name: string;
  kind: Kind;
  category: string;
  /** Для каких типов задач техника уместна. Пусто — ограничений нет. */
  task_types?: string[];
  execution: Execution;
  when_to_use: string;
  when_not: string | null;
  cost_calls: number | string;
  config: TechniqueConfig;
  template: string | null;
  /** Шаги выполнения для процедурных техник (KNN, RL-оптимизаторы, ансамбли). */
  procedure?: string[] | null;
  example: string;
  source_ref: string;
  source_docs: string[];
  related: string[];
  status: Status;
}

export interface Catalog {
  version: string;
  techniques: Technique[];
}

/** A question to the user and what is assumed while it stays unanswered. */
export interface BriefQuestion {
  question: string;
  /** The assumption used until the user answers; not repeated in `assumptions`. */
  default?: string;
}

/** Разбор входного потока мыслей. Всё, что модель домыслила, — в `assumptions`. */
export const CAPABILITIES = ['web', 'files', 'code', 'integrations'] as const;
export type Capability = typeof CAPABILITIES[number];
export type ExecutionCapabilities = Partial<Record<Capability, 'available' | 'unavailable' | 'unknown'>>;

export interface TaskBrief {
  /** Short model-written topic for the result and history. */
  topic?: string;
  verify_current_facts?: boolean;
  require_evidence?: boolean;
  requires_tools?: boolean;
  required_capabilities?: Capability[];
  validate_output?: boolean;
  goal: string;
  task_type: string;
  input: string;
  output_format: string;
  constraints: string[];
  language: string;
  modality: Modality;
  stakes: Stakes;
  assumptions: string[];
  /** Up to 3 questions whose answers would change the result materially; empty when nothing important is missing. */
  questions?: BriefQuestion[];
  /** Сколько вызовов LLM пользователь готов потратить. null — не ограничено. */
  budget_calls: number | null;
}

export interface TechniqueChoice {
  key: string;
  name: string;
  reason: string;
  confidence: number;
  /** Почему не более дешёвая техника — обязательный ответ на главный вопрос. */
  whyNotCheaper: string;
  /** Модель выбрала не самую дешёвую и не объяснила — выбор принят, но помечен. */
  cheapestOverride?: boolean;
}

export interface PromptConfig {
  temperature: number | null;
  top_p: number | null;
  max_tokens: string;
  rationale: string;
}

export interface Synthesis {
  techniqueKey: string;
  prompt: string;
  config: PromptConfig;
  /** Плейсхолдеры, которые нечем было заполнить. Пусто = промпт готов. */
  missing: string[];
  warnings: string[];
}

export interface PipelineTrace {
  step: string;
  ms: number;
  prompt?: string;
  raw?: string;
}

export interface PipelineResult {
  /** Additional standalone baseline, preceding all selected variants. */
  zeroShotPrompt?: string;
  claudeGuidance?: OfficialGuidance;
  chatgptGuidance?: OfficialGuidance;
  geminiGuidance?: OfficialGuidance;
  grokGuidance?: OfficialGuidance;
  hermesGuidance?: OfficialGuidance;
  openModelGuidance?: OfficialGuidance;
  brief: TaskBrief;
  choice: TechniqueChoice;
  synthesis: Synthesis;
  /** Дополнительные варианты техник с их промптами (если запрошено больше одного). */
  alternatives?: { choice: TechniqueChoice; synthesis: Synthesis }[];
  /** Техники, которые выбыли до выбора: почему. */
  rejected: { key: string; reason: string }[];
  trace: PipelineTrace[];
  /** Расход за весь прогон: все стадии и повторы разбора. Нули — провайдер не сообщил usage. */
  usage?: TokenUsage & { calls: number };
  /** Отпечаток внутренних промптов пайплайна: связывает результат и балл eval с версией промптов. */
  promptVersion?: string;
}

export interface TokenUsage {
  inputTokens: number;
  outputTokens: number;
}

export interface LLMCallOptions {
  temperature?: number;
  json?: boolean;
  maxTokens?: number;
  /** Адаптер сообщает расход токенов, если провайдер его вернул. */
  onUsage?: (usage: TokenUsage) => void;
}

export type LLM = (prompt: string, opts?: LLMCallOptions) => Promise<string>;

export class PipelineError extends Error {
  readonly step: string;

  constructor(message: string, step: string) {
    super(`[${step}] ${message}`);
    this.name = 'PipelineError';
    this.step = step;
  }
}
