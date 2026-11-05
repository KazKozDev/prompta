import test from 'node:test';
import assert from 'node:assert/strict';
import { createLLM } from './llm.ts';

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
