import type { LLM, TokenUsage } from './types.ts';

export type Provider = 'gemini' | 'openai' | 'ollama' | 'anthropic' | 'xai';
export const PROVIDERS: readonly Provider[] = ['gemini', 'openai', 'ollama', 'anthropic', 'xai'];

export interface LLMOptions {
  provider: Provider;
  model: string;
  apiKey?: string;
  baseUrl?: string;
  /** Limit per HTTP request; 120 s by default. Retries are counted separately. */
  timeoutMs?: number;
  /** External cancellation (the Stop button, closing the window). */
  signal?: AbortSignal;
}

export const DEFAULT_TIMEOUT_MS = 120_000;

/** The provider's environment key: one source of truth for the CLI, eval and MCP. */
export function apiKeyEnv(provider: Provider): string | undefined {
  return {
    gemini: 'GEMINI_API_KEY',
    openai: 'OPENAI_API_KEY',
    anthropic: 'ANTHROPIC_API_KEY',
    xai: 'XAI_API_KEY',
    // Optional: needed only for the direct ollama.com cloud API (OLLAMA_HOST=https://ollama.com).
    ollama: 'OLLAMA_API_KEY',
  }[provider];
}

/** Only Ollama works without a key: the local daemon proxies `:cloud` models itself. */
export const keyRequired = (provider: Provider): boolean => provider !== 'ollama';

export const isLocalHost = (url: string): boolean => {
  try {
    return ['localhost', '127.0.0.1', '[::1]', '::1'].includes(new URL(url).hostname);
  } catch {
    return false;
  }
};

/** The direct ollama.com API does not know the local daemon's `:cloud`/`-cloud` suffix: `glm-5.3:cloud` → `glm-5.3`. */
export function ollamaCloudModel(model: string): string {
  return model.replace(/[:-]cloud$/i, '');
}

/** An LLM from environment variables: the provider's key; for Ollama, OLLAMA_HOST and the optional OLLAMA_API_KEY. */
export function createLLMFromEnv(provider: Provider, model: string, env: Record<string, string | undefined>, extra: Partial<LLMOptions> = {}): LLM {
  const keyName = apiKeyEnv(provider);
  const apiKey = keyName ? env[keyName] : undefined;
  if (keyRequired(provider) && !apiKey) throw new Error(`${keyName} is set neither in the environment nor in .env.local`);
  let baseUrl = extra.baseUrl;
  if (!baseUrl && provider === 'ollama' && env.OLLAMA_HOST) {
    baseUrl = /^https?:\/\//.test(env.OLLAMA_HOST) ? env.OLLAMA_HOST : `http://${env.OLLAMA_HOST}`;
  }
  return createLLM({ provider, model, apiKey, ...extra, baseUrl });
}

export class LLMTimeoutError extends Error {
  constructor(ms: number) {
    super(`LLM request timed out after ${Math.round(ms / 1000)} s`);
    this.name = 'LLMTimeoutError';
  }
}

/** Retries on network failures, timeouts and 429/5xx: cloud models drop connections now and then. */
async function postJson(
  url: string,
  body: unknown,
  headers: Record<string, string>,
  opts: { timeoutMs: number; signal?: AbortSignal; attempts?: number },
): Promise<unknown> {
  const attempts = opts.attempts ?? 3;
  let lastError: unknown;

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    if (opts.signal?.aborted) throw opts.signal.reason ?? new Error('Aborted');
    let fatal = false;
    const timeout = AbortSignal.timeout(opts.timeoutMs);
    const signal = opts.signal ? AbortSignal.any([opts.signal, timeout]) : timeout;
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'content-type': 'application/json', ...headers },
        body: JSON.stringify(body),
        signal,
      });
      const text = await res.text();
      if (res.ok) return JSON.parse(text) as unknown;

      const retryable = res.status === 429 || res.status >= 500;
      lastError = new Error(`LLM ${res.status}: ${text.slice(0, 300)}`);
      if (!retryable) {
        fatal = true;
        throw lastError;
      }
    } catch (e) {
      // Cancelled by the user: out immediately, no retries.
      if (opts.signal?.aborted) throw opts.signal.reason ?? e;
      // 4xx (except 429) and broken JSON are pointless to retry
      if (fatal || e instanceof SyntaxError) throw lastError instanceof Error ? lastError : e;
      lastError = timeout.aborted ? new LLMTimeoutError(opts.timeoutMs) : e;
    }

    if (attempt < attempts) {
      await new Promise((r) => setTimeout(r, 800 * 2 ** (attempt - 1)));
    }
  }

  throw lastError instanceof Error ? lastError : new Error(String(lastError));
}

function report(cb: ((u: TokenUsage) => void) | undefined, input: unknown, output: unknown): void {
  if (!cb) return;
  const i = Number(input);
  const o = Number(output);
  cb({ inputTokens: Number.isFinite(i) ? i : 0, outputTokens: Number.isFinite(o) ? o : 0 });
}

/** An SDK-free adapter: fetch only, so the pipeline pulls in no dependencies. */
export function createLLM(opts: LLMOptions): LLM {
  const { provider, model, apiKey } = opts;
  const http = { timeoutMs: opts.timeoutMs ?? DEFAULT_TIMEOUT_MS, signal: opts.signal };

  if (provider === 'gemini') {
    if (!apiKey) throw new Error('An API key is required for gemini');
    const base = opts.baseUrl || 'https://generativelanguage.googleapis.com';
    return async (prompt, o = {}) => {
      // The key goes in a header, not the query: URLs end up in proxy logs and traces.
      const data = (await postJson(
        `${base}/v1beta/models/${encodeURIComponent(model)}:generateContent`,
        {
          contents: [{ parts: [{ text: prompt }] }],
          generationConfig: {
            temperature: o.temperature ?? 0.2,
            ...(o.maxTokens ? { maxOutputTokens: o.maxTokens } : {}),
            ...(o.json ? { responseMimeType: 'application/json' } : {}),
          },
        },
        { 'x-goog-api-key': apiKey },
        http,
      )) as {
        candidates?: { content?: { parts?: { text?: string }[] } }[];
        usageMetadata?: { promptTokenCount?: number; candidatesTokenCount?: number };
      };
      report(o.onUsage, data.usageMetadata?.promptTokenCount, data.usageMetadata?.candidatesTokenCount);
      const out = data.candidates?.[0]?.content?.parts?.map((p) => p.text ?? '').join('') ?? '';
      if (!out) throw new Error('gemini returned an empty response');
      return out;
    };
  }

  if (provider === 'openai' || provider === 'xai') {
    if (!apiKey && !(provider === 'openai' && opts.baseUrl && isLocalHost(opts.baseUrl))) {
      throw new Error(`An API key is required for ${provider}`);
    }
    // xAI is compatible with the chat/completions format; only the address differs.
    const base = (opts.baseUrl || (provider === 'xai' ? 'https://api.x.ai' : 'https://api.openai.com')).replace(/\/+$/, '');
    const apiRoot = base.endsWith('/v1') ? base : `${base}/v1`;
    return async (prompt, o = {}) => {
      const data = (await postJson(
        `${apiRoot}/chat/completions`,
        {
          model,
          messages: [{ role: 'user', content: prompt }],
          temperature: o.temperature ?? 0.2,
          ...(o.maxTokens ? { max_tokens: o.maxTokens } : {}),
          ...(o.json ? { response_format: { type: 'json_object' } } : {}),
        },
        apiKey ? { authorization: `Bearer ${apiKey}` } : {},
        http,
      )) as {
        choices?: { message?: { content?: string } }[];
        usage?: { prompt_tokens?: number; completion_tokens?: number };
      };
      report(o.onUsage, data.usage?.prompt_tokens, data.usage?.completion_tokens);
      const out = data.choices?.[0]?.message?.content ?? '';
      if (!out) throw new Error(`${provider} returned an empty response`);
      return out;
    };
  }

  if (provider === 'anthropic') {
    if (!apiKey) throw new Error('An API key is required for anthropic');
    const base = opts.baseUrl || 'https://api.anthropic.com';
    return async (prompt, o = {}) => {
      // Current Claude models reject temperature/top_p, so they are not sent;
      // JSON is requested by the prompt (every JSON stage already has the schema in its text).
      const data = (await postJson(
        `${base}/v1/messages`,
        {
          model,
          max_tokens: o.maxTokens ?? 16000,
          messages: [{ role: 'user', content: prompt }],
        },
        { 'x-api-key': apiKey, 'anthropic-version': '2023-06-01' },
        http,
      )) as {
        content?: { type?: string; text?: string }[];
        stop_reason?: string;
        usage?: { input_tokens?: number; output_tokens?: number };
      };
      report(o.onUsage, data.usage?.input_tokens, data.usage?.output_tokens);
      if (data.stop_reason === 'refusal') throw new Error('anthropic declined the request (stop_reason: refusal)');
      const out = (data.content ?? []).filter((b) => b.type === 'text').map((b) => b.text ?? '').join('');
      if (!out) throw new Error('anthropic returned an empty response');
      return out;
    };
  }

  const base = (opts.baseUrl || 'http://localhost:11434').replace(/\/+$/, '');
  // The cloud API (ollama.com) gets the key and no :cloud suffix; the local daemon never gets the key.
  const remote = !isLocalHost(base);
  const ollamaHeaders: Record<string, string> = remote && apiKey ? { authorization: `Bearer ${apiKey}` } : {};
  const ollamaModel = remote && /(^|\.)ollama\.com$/.test(new URL(base).hostname) ? ollamaCloudModel(model) : model;
  return async (prompt, o = {}) => {
    const data = (await postJson(
      `${base}/api/generate`,
      {
        model: ollamaModel,
        prompt,
        stream: false,
        ...(o.json ? { format: 'json' } : {}),
        options: {
          temperature: o.temperature ?? 0.2,
          ...(o.maxTokens ? { num_predict: o.maxTokens } : {}),
        },
      },
      ollamaHeaders,
      http,
    )) as { response?: string; prompt_eval_count?: number; eval_count?: number };
    report(o.onUsage, data.prompt_eval_count, data.eval_count);
    const out = data.response ?? '';
    if (!out) throw new Error('ollama returned an empty response');
    return out;
  };
}

/** A counting wrapper: sums tokens and calls across all stages of one run. */
export function meterLLM(llm: LLM): { llm: LLM; usage: () => TokenUsage & { calls: number } } {
  const total = { inputTokens: 0, outputTokens: 0, calls: 0 };
  const metered: LLM = (prompt, o = {}) => {
    total.calls += 1;
    return llm(prompt, {
      ...o,
      onUsage: (u) => {
        total.inputTokens += u.inputTokens;
        total.outputTokens += u.outputTokens;
        o.onUsage?.(u);
      },
    });
  };
  return { llm: metered, usage: () => ({ ...total }) };
}
