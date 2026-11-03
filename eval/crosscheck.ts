import { CRITERIA } from './judge.ts';
import type { Criterion, Judgement } from './judge.ts';

export interface JudgeDelta {
  /** b.total − a.total: положительное значит второй судья добрее. */
  totalDelta: number;
  absDelta: number;
  verdictAgreement: boolean;
  perCriterion: Record<Criterion, number>;
}

export interface CrossCheck {
  runs: number;
  meanAbsDelta: number;
  maxAbsDelta: number;
  verdictAgreement: number;
  /** Средний перекос по критерию (второй минус первый): где судьи расходятся системно. */
  biasPerCriterion: Record<Criterion, number>;
  /** Корреляция итоговых баллов: близко к 1 — судьи ранжируют одинаково. */
  pearson: number;
  /** Доверять ли цифрам одного судьи. */
  verdict: 'доверять' | 'перепроверить' | 'не доверять';
  /** Критерии, где расхождение больше 0.5 балла — самое вероятное место предвзятости. */
  contestedCriteria: Criterion[];
}

const round2 = (x: number) => Number(x.toFixed(2));

export function compareJudgements(a: Judgement, b: Judgement): JudgeDelta {
  const perCriterion = {} as Record<Criterion, number>;
  for (const c of CRITERIA) perCriterion[c] = b.scores[c].score - a.scores[c].score;
  return {
    totalDelta: round2(b.total - a.total),
    absDelta: round2(Math.abs(b.total - a.total)),
    verdictAgreement: a.verdict === b.verdict,
    perCriterion,
  };
}

function pearson(xs: number[], ys: number[]): number {
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
  // Обе серии постоянны — судьи не различаются, это идеальное согласие, а не ноль.
  if (dx === 0 && dy === 0) return 1;
  if (dx === 0 || dy === 0) return 0;
  return round2(num / Math.sqrt(dx * dy));
}

export function crossCheck(pairs: { primary: Judgement; secondary: Judgement }[]): CrossCheck | null {
  if (pairs.length === 0) return null;

  const deltas = pairs.map((p) => compareJudgements(p.primary, p.secondary));
  const meanAbsDelta = round2(deltas.reduce((s, d) => s + d.absDelta, 0) / deltas.length);
  const maxAbsDelta = round2(Math.max(...deltas.map((d) => d.absDelta)));
  const verdictAgreement = round2(
    deltas.filter((d) => d.verdictAgreement).length / deltas.length,
  );

  const biasPerCriterion = {} as Record<Criterion, number>;
  for (const c of CRITERIA) {
    biasPerCriterion[c] = round2(
      pairs.reduce((s, p) => s + (p.secondary.scores[c].score - p.primary.scores[c].score), 0) / pairs.length,
    );
  }

  const contestedCriteria = CRITERIA.filter((c) => Math.abs(biasPerCriterion[c]) > 0.5);

  // Систематический перекос по критерию — красный флаг даже при совпавших вердиктах:
  // судьи могут одинаково ставить «revise», но расходиться в том, что именно плохо.
  const verdict: CrossCheck['verdict'] =
    verdictAgreement < 0.6 || meanAbsDelta > 1
      ? 'не доверять'
      : contestedCriteria.length > 0 || verdictAgreement < 0.8 || meanAbsDelta > 0.5
        ? 'перепроверить'
        : 'доверять';

  return {
    runs: pairs.length,
    meanAbsDelta,
    maxAbsDelta,
    verdictAgreement,
    biasPerCriterion,
    pearson: pearson(
      pairs.map((p) => p.primary.total),
      pairs.map((p) => p.secondary.total),
    ),
    verdict,
    contestedCriteria,
  };
}

export function formatCrossCheck(cc: CrossCheck): string {
  const pct = (x: number) => `${Math.round(x * 100)}%`;
  const lines = [
    '',
    `Сверка двух судей (${cc.runs} прогонов): ${cc.verdict.toUpperCase()}`,
    `  расхождение баллов: среднее ${cc.meanAbsDelta}, максимум ${cc.maxAbsDelta}`,
    `  совпадение вердиктов: ${pct(cc.verdictAgreement)} | корреляция итогов: ${cc.pearson}`,
    `  перекос по критериям (второй минус первый): ${CRITERIA.map((c) => `${c} ${cc.biasPerCriterion[c] > 0 ? '+' : ''}${cc.biasPerCriterion[c]}`).join(', ')}`,
  ];
  if (cc.contestedCriteria.length) {
    lines.push(`  спорные критерии: ${cc.contestedCriteria.join(', ')} — здесь судьи расходятся системно`);
  }
  return lines.join('\n');
}
