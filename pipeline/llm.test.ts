import test from 'node:test';
import assert from 'node:assert/strict';
import { createLLM, createLLMFromEnv, LLMTimeoutError, meterLLM, ollamaCloudModel } from './llm.ts';
import type { LLM } from './types.ts';

test('адаптеры провайдеров передают настройки и разбирают ответы', async (t) => {
  for (const provider of ['ollama', 'openai', 'gemini'] as const) {
    await t.test(provider, async () => {
      let body: Record<string, any> = {};
      t.mock.method(globalThis, 'fetch', async (_url: unknown, init: RequestInit) => {
        body = JSON.parse(String(init.body));
        const payload = provider === 'ollama' ? { response: 'ответ' } : provider === 'openai'
          ? { choices: [{ message: { content: 'ответ' } }] }
          : { candidates: [{ content: { parts: [{ text: 'ответ' }] } }] };
        return new Response(JSON.stringify(payload));
      });
      const llm = createLLM({ provider, model: 'synthetic', apiKey: 'synthetic-test-key' });
      assert.equal(await llm('синтетический тест', { temperature: 0, json: true, maxTokens: 128 }), 'ответ');
      if (provider === 'ollama') {
        assert.equal(body.format, 'json'); assert.equal(body.options.num_predict, 128); assert.equal(body.options.temperature, 0);
      } else if (provider === 'openai') {
        assert.equal(body.response_format.type, 'json_object'); assert.equal(body.max_tokens, 128); assert.equal(body.temperature, 0);
      } else {
        assert.equal(body.generationConfig.responseMimeType, 'application/json'); assert.equal(body.generationConfig.maxOutputTokens, 128); assert.equal(body.generationConfig.temperature, 0);
      }
      t.mock.restoreAll();
    });
  }
});

test('ошибка авторизации не повторяется, пустой ответ не принимается', async (t) => {
  let calls = 0;
  t.mock.method(globalThis, 'fetch', async () => { calls++; return new Response('unauthorized', { status: 401 }); });
  const llm = createLLM({ provider: 'ollama', model: 'synthetic' });
  await assert.rejects(llm('тест'), /401/);
  assert.equal(calls, 1);
  t.mock.restoreAll();
  t.mock.method(globalThis, 'fetch', async () => new Response('{}'));
  await assert.rejects(llm('тест'), /empty response/);
});

test('meta: minimal reasoning effort, other OpenAI-compatible addresses send none; thinking out of tokens is named', async (t) => {
  const bodies: Record<string, any>[] = [];
  t.mock.method(globalThis, 'fetch', async (_url: unknown, init: RequestInit) => {
    bodies.push(JSON.parse(String(init.body)));
    return new Response(JSON.stringify({ choices: [{ message: { content: 'ok' } }] }));
  });
  await createLLM({ provider: 'openai', model: 'muse-spark-1.3', apiKey: 'k', baseUrl: 'https://api.meta.ai/v1' })('тест');
  await createLLM({ provider: 'openai', model: 'synthetic', apiKey: 'k' })('тест');
  assert.equal(bodies[0].reasoning_effort, 'minimal');
  assert.equal(bodies[1].reasoning_effort, undefined);
  t.mock.restoreAll();
  t.mock.method(globalThis, 'fetch', async () =>
    new Response(JSON.stringify({ choices: [{ message: { content: '' }, finish_reason: 'length' }] })));
  await assert.rejects(createLLM({ provider: 'openai', model: 'm', apiKey: 'k' })('тест'), /whole token limit thinking/);
});

test('anthropic и xai: адрес, заголовки, без temperature у Claude, учёт токенов', async (t) => {
  const seen: { url: string; headers: Record<string, string>; body: Record<string, any> }[] = [];
  t.mock.method(globalThis, 'fetch', async (url: unknown, init: RequestInit) => {
    seen.push({ url: String(url), headers: init.headers as Record<string, string>, body: JSON.parse(String(init.body)) });
    const payload = String(url).includes('anthropic')
      ? { content: [{ type: 'thinking', thinking: '' }, { type: 'text', text: 'ответ' }], stop_reason: 'end_turn', usage: { input_tokens: 11, output_tokens: 7 } }
      : { choices: [{ message: { content: 'ответ' } }], usage: { prompt_tokens: 5, completion_tokens: 3 } };
    return new Response(JSON.stringify(payload));
  });
  const usage: { inputTokens: number; outputTokens: number }[] = [];
  const claude = createLLM({ provider: 'anthropic', model: 'synthetic', apiKey: 'k' });
  assert.equal(await claude('тест', { temperature: 0, json: true, onUsage: (u) => usage.push(u) }), 'ответ');
  assert.equal(seen[0].url, 'https://api.anthropic.com/v1/messages');
  assert.equal(seen[0].headers['x-api-key'], 'k');
  assert.ok(seen[0].headers['anthropic-version']);
  assert.equal('temperature' in seen[0].body, false, 'текущие модели Claude отклоняют temperature');
  assert.ok(seen[0].body.max_tokens > 0, 'max_tokens обязателен в Messages API');
  const grok = createLLM({ provider: 'xai', model: 'synthetic', apiKey: 'k' });
  await grok('тест', { onUsage: (u) => usage.push(u) });
  assert.equal(seen[1].url, 'https://api.x.ai/v1/chat/completions');
  assert.deepEqual(usage, [{ inputTokens: 11, outputTokens: 7 }, { inputTokens: 5, outputTokens: 3 }]);
});

test('anthropic: отказ модели — ошибка, а не пустой промпт', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ content: [], stop_reason: 'refusal' })));
  await assert.rejects(createLLM({ provider: 'anthropic', model: 's', apiKey: 'k' })('тест'), /refusal/);
});

test('gemini: ключ в заголовке, а не в URL', async (t) => {
  let url = ''; let headers: Record<string, string> = {};
  t.mock.method(globalThis, 'fetch', async (u: unknown, init: RequestInit) => {
    url = String(u); headers = init.headers as Record<string, string>;
    return new Response(JSON.stringify({ candidates: [{ content: { parts: [{ text: 'ok' }] } }] }));
  });
  await createLLM({ provider: 'gemini', model: 'm', apiKey: 'secret-key' })('тест');
  assert.equal(url.includes('secret-key'), false);
  assert.equal(headers['x-goog-api-key'], 'secret-key');
});

test('таймаут обрывает зависший запрос и повторяется; внешняя отмена — без повторов', async (t) => {
  let calls = 0;
  t.mock.method(globalThis, 'fetch', (_u: unknown, init: RequestInit) => {
    calls++;
    return new Promise((_, reject) => init.signal!.addEventListener('abort', () => reject(init.signal!.reason)));
  });
  const llm = createLLM({ provider: 'ollama', model: 's', timeoutMs: 20 });
  await assert.rejects(llm('тест'), LLMTimeoutError);
  assert.equal(calls, 3, 'таймаут — сетевой сбой, повторяется');
  calls = 0;
  const stop = new AbortController();
  const cancellable = createLLM({ provider: 'ollama', model: 's', signal: stop.signal });
  const pending = cancellable('тест');
  stop.abort(new Error('stopped by user'));
  await assert.rejects(pending, /stopped by user/);
  assert.equal(calls, 1);
});

test('meterLLM суммирует вызовы и токены', async () => {
  const fake: LLM = async (_p, o) => { o?.onUsage?.({ inputTokens: 10, outputTokens: 4 }); return 'x'; };
  const m = meterLLM(fake);
  await m.llm('a'); await m.llm('b');
  assert.deepEqual(m.usage(), { inputTokens: 20, outputTokens: 8, calls: 2 });
});

test('облачный API Ollama: ключ в заголовке, без суффикса :cloud; локальному демону ключ не уходит', async (t) => {
  const seen: { url: string; headers: Record<string, string>; model: string }[] = [];
  t.mock.method(globalThis, 'fetch', async (url: unknown, init: RequestInit) => {
    seen.push({ url: String(url), headers: init.headers as Record<string, string>, model: JSON.parse(String(init.body)).model });
    return new Response(JSON.stringify({ response: 'ok', prompt_eval_count: 3, eval_count: 2 }));
  });
  await createLLMFromEnv('ollama', 'glm-5.3:cloud', { OLLAMA_HOST: 'https://ollama.com', OLLAMA_API_KEY: 'k' })('тест');
  assert.equal(seen[0].url, 'https://ollama.com/api/generate');
  assert.equal(seen[0].headers.authorization, 'Bearer k');
  assert.equal(seen[0].model, 'glm-5.3');
  await createLLMFromEnv('ollama', 'glm-5.3:cloud', { OLLAMA_API_KEY: 'k' })('тест');
  assert.equal(seen[1].url, 'http://localhost:11434/api/generate');
  assert.equal(seen[1].headers.authorization, undefined, 'локальный демон проксирует облако сам');
  assert.equal(seen[1].model, 'glm-5.3:cloud');
  assert.equal(ollamaCloudModel('gpt-oss:120b-cloud'), 'gpt-oss:120b');
  assert.throws(() => createLLMFromEnv('anthropic', 'm', {}), /ANTHROPIC_API_KEY/);
});

test('ollama: длинный промпт расширяет окно, и следующие вызовы прогона держат тот же размер', async (t) => {
  const sizes: (number | undefined)[] = [];
  t.mock.method(globalThis, 'fetch', async (_url: unknown, init: RequestInit) => {
    sizes.push(JSON.parse(String(init.body)).options.num_ctx);
    return new Response(JSON.stringify({ response: 'ok' }));
  });
  const llm = createLLM({ provider: 'ollama', model: 'synthetic' });
  await llm('short');
  await llm('x'.repeat(12_000), { maxTokens: 2048 });
  await llm('short again');
  assert.deepEqual(sizes, [undefined, 8192, 8192]);
});
