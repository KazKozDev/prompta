/** Ранговые и линейные корреляции — без зависимостей, чтобы тестировалось офлайн. */

const round2 = (x: number) => Number(x.toFixed(2));

export function pearson(xs: number[], ys: number[]): number {
  const n = Math.min(xs.length, ys.length);
  if (n < 2) return 0;
  const mx = xs.slice(0, n).reduce((s, v) => s + v, 0) / n;
  const my = ys.slice(0, n).reduce((s, v) => s + v, 0) / n;
  let num = 0;
  let dx = 0;
  let dy = 0;
  for (let i = 0; i < n; i += 1) {
    const a = xs[i] - mx;
    const b = ys[i] - my;
    num += a * b;
    dx += a * a;
    dy += b * b;
  }
  if (dx === 0 && dy === 0) return 1;
  if (dx === 0 || dy === 0) return 0;
  return round2(num / Math.sqrt(dx * dy));
}

/** Ранги с усреднением при совпадениях (как в scipy). */
export function ranks(xs: number[]): number[] {
  const idx = xs.map((v, i) => ({ v, i })).sort((a, b) => a.v - b.v);
  const out = new Array<number>(xs.length);
  let i = 0;
  while (i < idx.length) {
    let j = i;
    while (j + 1 < idx.length && idx[j + 1].v === idx[i].v) j += 1;
    const avg = (i + j) / 2 + 1;
    for (let k = i; k <= j; k += 1) out[idx[k].i] = avg;
    i = j + 1;
  }
  return out;
}

export function spearman(xs: number[], ys: number[]): number {
  if (Math.min(xs.length, ys.length) < 2) return 0;
  return pearson(ranks(xs), ranks(ys));
}

export interface Correlation {
  pearson: number;
  spearman: number;
  n: number;
  /** Насколько выводу можно верить при таком n. */
  reliability: 'нет данных' | 'пилот' | 'устойчиво';
}

export function correlate(xs: number[], ys: number[]): Correlation {
  const n = Math.min(xs.length, ys.length);
  return {
    pearson: pearson(xs, ys),
    spearman: spearman(xs, ys),
    n,
    reliability: n < 3 ? 'нет данных' : n < 8 ? 'пилот' : 'устойчиво',
  };
}
