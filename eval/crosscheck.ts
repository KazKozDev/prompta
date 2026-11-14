import { CRITERIA } from './judge.ts';
import type { Criterion, Judgement } from './judge.ts';

export interface JudgeDelta {
  /** b.total − a.total: positive means the second judge is kinder. */
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
  /** Mean bias per criterion (second minus first): where the judges disagree systematically. */
  biasPerCriterion: Record<Criterion, number>;
  /** Correlation of total scores: close to 1 — the judges rank alike. */
  pearson: number;
  /** Whether to trust a single judge's numbers. */
  verdict: 'trust' | 'recheck' | 'do not trust';
  /** Criteria where the gap exceeds 0.5 points — the most likely place for bias. */
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
  // Both series are constant: the judges do not differ, which is perfect agreement, not zero.
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

  // A systematic bias on a criterion is a red flag even when the verdicts agree:
  // the judges may both say "revise" but disagree on what exactly is wrong.
  const verdict: CrossCheck['verdict'] =
    verdictAgreement < 0.6 || meanAbsDelta > 1
      ? 'do not trust'
      : contestedCriteria.length > 0 || verdictAgreement < 0.8 || meanAbsDelta > 0.5
        ? 'recheck'
        : 'trust';

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
    `Two-judge crosscheck (${cc.runs} runs): ${cc.verdict.toUpperCase()}`,
    `  score gap: mean ${cc.meanAbsDelta}, max ${cc.maxAbsDelta}`,
    `  verdict agreement: ${pct(cc.verdictAgreement)} | total correlation: ${cc.pearson}`,
    `  bias per criterion (second minus first): ${CRITERIA.map((c) => `${c} ${cc.biasPerCriterion[c] > 0 ? '+' : ''}${cc.biasPerCriterion[c]}`).join(', ')}`,
  ];
  if (cc.contestedCriteria.length) {
    lines.push(`  contested criteria: ${cc.contestedCriteria.join(', ')} — the judges disagree systematically here`);
  }
  return lines.join('\n');
}
