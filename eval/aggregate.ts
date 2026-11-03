import type { Judgement } from './judge.ts';
import { crossCheck, formatCrossCheck } from './crosscheck.ts';
import type { CrossCheck } from './crosscheck.ts';

export interface Expect {
  task_type: string;
  any_of: string[];
  forbidden: string[];
  must_mention: string[];
  budget_calls: number | null;
}

export interface EvalTask {
  id: string;
  title: string;
  thoughts: string;
  expect: Expect;
}

export type RunRecord =
  | {
      ok: true;
      taskId: string;
      repeat: number;
      techniqueKey: string;
      confidence: number;
      prompt: string;
      warnings: string[];
      judgement: Judgement;
      /** Оценка второго судьи другой модели; сравнивается с первой. */
      judgement2?: Judgement;
    }
  | { ok: false; taskId: string; repeat: number; error: string };

export interface TaskSummary {
  taskId: string;
  runs: number;
  failures: number;
  techniques: Record<string, number>;
  majority: string | null;
  /** Доля прогонов, где выбрана самая частая техника: 1.0 — выбор не дрейфует. */
  stability: number;
  meanScore: number;
  /** Доля прогонов, где выбрана техника из ожидаемого списка. */
  expectedHit: number;
  /** Доля прогонов, где выбрана запрещённая техника. */
  forbiddenHit: number;
  /** Доля прогонов, где промпт содержит ожидаемую лексику. */
  mentionHit: number;
}

export interface Report {
  runs: number;
  failures: number;
  overall: {
    meanScore: number;
    stability: number;
    expectedHit: number;
    forbiddenHit: number;
    mentionHit: number;
  };
  tasks: TaskSummary[];
  techniques: { key: string; runs: number; meanScore: number }[];
  /** Есть только если прогон запускался со вторым судьёй. */
  crossCheck: CrossCheck | null;
  /** Оценки по каждому судье отдельно: одиночный судья оказался ненадёжным. */
  panel: { runs: number; primaryMean: number; secondaryMean: number; panelMean: number } | null;
}

const mean = (xs: number[]): number =>
  xs.length ? Number((xs.reduce((a, b) => a + b, 0) / xs.length).toFixed(2)) : 0;

export function aggregate(records: RunRecord[], tasks: EvalTask[]): Report {
  const byTask = new Map<string, RunRecord[]>();
  for (const r of records) {
    const list = byTask.get(r.taskId) ?? [];
    list.push(r);
    byTask.set(r.taskId, list);
  }

  const summaries: TaskSummary[] = [];
  for (const task of tasks) {
    const runs = byTask.get(task.id) ?? [];
    if (runs.length === 0) continue;

    const okRuns = runs.filter((r): r is Extract<RunRecord, { ok: true }> => r.ok);
    const counts: Record<string, number> = {};
    for (const r of okRuns) counts[r.techniqueKey] = (counts[r.techniqueKey] ?? 0) + 1;

    const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);
    const majority = sorted[0]?.[0] ?? null;
    const majorityCount = sorted[0]?.[1] ?? 0;
    const denom = okRuns.length || 1;

    summaries.push({
      taskId: task.id,
      runs: runs.length,
      failures: runs.length - okRuns.length,
      techniques: counts,
      majority,
      stability: Number((majorityCount / denom).toFixed(2)),
      meanScore: mean(okRuns.map((r) => r.judgement.total)),
      expectedHit: Number(
        (okRuns.filter((r) => task.expect.any_of.includes(r.techniqueKey)).length / denom).toFixed(2),
      ),
      forbiddenHit: Number(
        (okRuns.filter((r) => task.expect.forbidden.includes(r.techniqueKey)).length / denom).toFixed(2),
      ),
      mentionHit: Number(
        (okRuns.filter((r) =>
          task.expect.must_mention.some((m) => r.prompt.toLowerCase().includes(m.toLowerCase())),
        ).length / denom).toFixed(2),
      ),
    });
  }

  const okAll = records.filter((r): r is Extract<RunRecord, { ok: true }> => r.ok);

  const pairs = okAll
    .filter((r): r is Extract<RunRecord, { ok: true }> & { judgement2: Judgement } => Boolean(r.judgement2))
    .map((r) => ({ primary: r.judgement, secondary: r.judgement2 }));
  const techStats = new Map<string, number[]>();
  for (const r of okAll) {
    const list = techStats.get(r.techniqueKey) ?? [];
    list.push(r.judgement.total);
    techStats.set(r.techniqueKey, list);
  }

  return {
    runs: records.length,
    failures: records.length - okAll.length,
    overall: {
      meanScore: mean(okAll.map((r) => r.judgement.total)),
      stability: mean(summaries.map((s) => s.stability)),
      expectedHit: mean(summaries.map((s) => s.expectedHit)),
      forbiddenHit: mean(summaries.map((s) => s.forbiddenHit)),
      mentionHit: mean(summaries.map((s) => s.mentionHit)),
    },
    tasks: summaries,
    techniques: [...techStats.entries()]
      .map(([key, scores]) => ({ key, runs: scores.length, meanScore: mean(scores) }))
      .sort((a, b) => b.meanScore - a.meanScore || b.runs - a.runs),
    crossCheck: crossCheck(pairs),
    panel: pairs.length
      ? {
          runs: pairs.length,
          primaryMean: mean(pairs.map((p) => p.primary.total)),
          secondaryMean: mean(pairs.map((p) => p.secondary.total)),
          panelMean: mean(pairs.map((p) => (p.primary.total + p.secondary.total) / 2)),
        }
      : null,
  };
}

export function formatReport(report: Report): string {
  const pct = (x: number) => `${Math.round(x * 100)}%`;
  const lines = [
    `Прогонов: ${report.runs}, ошибок: ${report.failures}`,
    `Средний балл: ${report.overall.meanScore} | стабильность выбора: ${pct(report.overall.stability)} | попадание в ожидаемые: ${pct(report.overall.expectedHit)}`,
    `Запрещённые техники: ${pct(report.overall.forbiddenHit)} | ожидаемая лексика в промпте: ${pct(report.overall.mentionHit)}`,
    '',
    'По задачам:',
    ...report.tasks.map(
      (t) =>
        `  ${t.taskId.padEnd(22)} балл ${t.meanScore.toFixed(2)} | стабильность ${pct(t.stability)} | ожидаемо ${pct(t.expectedHit)} | запрещено ${pct(t.forbiddenHit)} | ${Object.entries(t.techniques).map(([k, c]) => `${k}×${c}`).join(', ')}`,
    ),
    '',
    'По техникам:',
    ...report.techniques.map((t) => `  ${t.key.padEnd(28)} ${t.meanScore.toFixed(2)} (${t.runs})`),
  ];
  if (report.panel) {
    lines.push(
      '',
      `Панель судей (${report.panel.runs}): первый ${report.panel.primaryMean} | второй ${report.panel.secondaryMean} | среднее ${report.panel.panelMean}`,
      'Одиночный балл сравнивать между прогонами нельзя — только панельное среднее.',
    );
  }
  if (report.crossCheck) lines.push(formatCrossCheck(report.crossCheck));
  return lines.join('\n');
}
