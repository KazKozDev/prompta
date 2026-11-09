import test from 'node:test';
import assert from 'node:assert/strict';
import { settleWithLimit } from './limit.ts';

test('settleWithLimit keeps order, caps parallelism, and isolates failures', async () => {
  let running = 0;
  let peak = 0;
  const results = await settleWithLimit([1, 2, 3, 4, 5, 6, 7], 3, async (n) => {
    running += 1;
    peak = Math.max(peak, running);
    await new Promise((r) => setTimeout(r, 5 * (8 - n)));
    running -= 1;
    if (n === 4) throw new Error('boom');
    return n * 10;
  });
  assert.equal(peak, 3);
  assert.deepEqual(results.map((r) => (r.status === 'fulfilled' ? r.value : (r.reason as Error).message)), [10, 20, 30, 'boom', 50, 60, 70]);
  assert.deepEqual(await settleWithLimit([], 4, async () => 1), []);
});
