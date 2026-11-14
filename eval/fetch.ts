import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

/** Calibration fixture: labelled examples from Hugging Face.
 *  Source: sy-volkov/russian-sentiment-analysis-dataset (3 classes: G/B/N).
 *  Downloaded once into eval/data/sentiment-ru.json, so the runtime stays offline.
 */

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const OUT = join(root, 'eval', 'data', 'sentiment-ru.json');
const DATASET = 'sy-volkov/russian-sentiment-analysis-dataset';
const PER_CLASS = 12;
const SCAN = 400;

const CLASS_TO_LABEL: Record<string, 'positive' | 'negative' | 'neutral'> = {
  G: 'positive',
  B: 'negative',
  N: 'neutral',
};

interface Row {
  row: { processed_text?: string; text?: string; Class?: string; label?: number };
}

/** HF returns at most 100 rows per request: page through. */
async function fetchRows(offset: number, limit: number): Promise<Row[]> {
  const out: Row[] = [];
  for (let o = offset; o < offset + limit; o += 100) {
    const size = Math.min(100, offset + limit - o);
    const url = `https://datasets-server.huggingface.co/rows?dataset=${encodeURIComponent(DATASET)}&config=default&split=train&offset=${o}&length=${size}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HF ${res.status}: ${await res.text()}`);
    const data = (await res.json()) as { rows?: Row[] };
    out.push(...(data.rows ?? []));
    if ((data.rows ?? []).length < size) break;
  }
  return out;
}

async function main() {
  const rows = await fetchRows(0, SCAN);
  const buckets: Record<string, { text: string; label: string }[]> = { positive: [], negative: [], neutral: [] };
  const seen = new Set<string>();

  for (const { row } of rows) {
    const text = (row.processed_text ?? row.text ?? '').trim();
    const cls = (row.Class ?? '').toString().toUpperCase();
    const label = CLASS_TO_LABEL[cls];
    if (!label || text.length < 25 || text.length > 400) continue;
    if (seen.has(text)) continue;
    seen.add(text);
    if (buckets[label].length < PER_CLASS) buckets[label].push({ text, label });
  }

  const examples = (['positive', 'negative', 'neutral'] as const).flatMap((label) =>
    buckets[label].map((e, i) => ({ id: `${label}-${i + 1}`, text: e.text, label })),
  );

  for (const label of Object.keys(buckets)) {
    if (buckets[label].length < PER_CLASS) console.warn(`few examples of class ${label}: ${buckets[label].length}`);
  }

  mkdirSync(dirname(OUT), { recursive: true });
  writeFileSync(
    OUT,
    JSON.stringify(
      {
        source: `https://huggingface.co/datasets/${DATASET}`,
        license: 'see the dataset card',
        task: 'sentiment classification: positive | negative | neutral',
        fetched: new Date().toISOString().slice(0, 10),
        examples,
      },
      null,
      2,
    ) + '\n',
    'utf8',
  );
  console.log(`wrote ${examples.length} examples → ${OUT}`);
}

main().catch((e) => {
  console.error('error:', e instanceof Error ? e.message : e);
  process.exit(1);
});
