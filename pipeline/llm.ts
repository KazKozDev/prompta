import type { LLM } from './types.ts';

export type Provider = 'gemini' | 'openai' | 'ollama';

export interface LLMOptions {
  provider: Provider;
  model: string;
  apiKey?: string;
  baseUrl?: string;
}

/** Ретраи на сетевые сбои и 429/5xx: облачные модели периодически рвут соединение. */
async function postJson(
  url: string,
  body: unknown,
  headers: Record<string, string> = {},
  attempts = 3,
): Promise<unknown> {
  let lastError: unknown;

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    let fatal = false;
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'content-type': 'application/json', ...headers },
        body: JSON.stringify(body),
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
      // 4xx (кроме 429) и битый JSON повторять бессмысленно
      if (fatal || e instanceof SyntaxError) throw lastError instanceof Error ? lastError : e;
      lastError = e;
    }

    if (attempt < attempts) {
      await new Promise((r) => setTimeout(r, 800 * 2 ** (attempt - 1)));
    }
  }

  throw lastError instanceof Error ? lastError : new Error(String(lastError));
}

/** Адаптер без SDK: только fetch, чтобы пайплайн не тянул зависимости. */
export function createLLM(opts: LLMOptions): LLM {
  const { provider, model, apiKey } = opts;
  const base = opts.baseUrl ?? (provider === 'ollama' ? 'http://localhost:11434' : '');

  if (provider === 'gemini') {
    if (!apiKey) throw new Error('An API key is required for gemini');
    return async (prompt, o = {}) => {
      const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`;
      const data = (await postJson(url, {
        contents: [{ parts: [{ text: prompt }] }],
        generationConfig: {
          temperature: o.temperature ?? 0.2,
          ...(o.maxTokens ? { maxOutputTokens: o.maxTokens } : {}),
          ...(o.json ? { responseMimeType: 'application/json' } : {}),
        },
      })) as { candidates?: { content?: { parts?: { text?: string }[] } }[] };
      const out = data.candidates?.[0]?.content?.parts?.map((p) => p.text ?? '').join('') ?? '';
      if (!out) throw new Error('gemini returned an empty response');
      return out;
    };
  }

  if (provider === 'openai') {
    if (!apiKey) throw new Error('An API key is required for openai');
    return async (prompt, o = {}) => {
      const data = (await postJson(
        `${base || 'https://api.openai.com'}/v1/chat/completions`,
        {
          model,
          messages: [{ role: 'user', content: prompt }],
          temperature: o.temperature ?? 0.2,
          ...(o.maxTokens ? { max_tokens: o.maxTokens } : {}),
          ...(o.json ? { response_format: { type: 'json_object' } } : {}),
        },
        { authorization: `Bearer ${apiKey}` },
      )) as { choices?: { message?: { content?: string } }[] };
      const out = data.choices?.[0]?.message?.content ?? '';
      if (!out) throw new Error('openai returned an empty response');
      return out;
    };
  }

  return async (prompt, o = {}) => {
    const data = (await postJson(`${base}/api/generate`, {
      model,
      prompt,
      stream: false,
      ...(o.json ? { format: 'json' } : {}),
      options: {
        temperature: o.temperature ?? 0.2,
        ...(o.maxTokens ? { num_predict: o.maxTokens } : {}),
      },
    })) as { response?: string };
    const out = data.response ?? '';
    if (!out) throw new Error('ollama returned an empty response');
    return out;
  };
}
