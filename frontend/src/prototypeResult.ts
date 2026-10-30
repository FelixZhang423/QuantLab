/**
 * 前端原型的「单因子结果详情」。
 *
 * 原型回测写入 sessionStorage 的批次只有表格指标，没有真实净值与结果文件；
 * 这里把单个因子 + 批次行转换成 ResultDetail 结构，让结果详情页可以复用
 * 真实结果的净值图、年度指标和大模型 8 维评价。净值曲线为确定性模拟，
 * 页面上会标注「前端原型」。
 */
import type { EquityPoint, FactorBacktestRow, ResultDetail, YearlyDatum } from "./api/client";
import type { PrototypeBatchDetail, PrototypeFactor, PrototypeFactorRun } from "./factorPrototype";

const clampNumber = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

function seedFrom(text: string): () => number {
  let state = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    state ^= text.charCodeAt(index);
    state = Math.imul(state, 16777619);
  }
  return () => {
    state += 0x6d2b79f5;
    let value = state;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

function gaussian(random: () => number): number {
  let u = 0;
  let v = 0;
  while (u === 0) u = random();
  while (v === 0) v = random();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

function formatDate(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

function tradingDates(start: string, end: string): string[] {
  const first = new Date(`${start}T00:00:00`);
  const last = new Date(`${end}T00:00:00`);
  if (Number.isNaN(first.getTime()) || Number.isNaN(last.getTime()) || first > last) return [];
  const dates: string[] = [];
  const cursor = new Date(first);
  while (cursor <= last) {
    const weekday = cursor.getDay();
    if (weekday !== 0 && weekday !== 6) dates.push(formatDate(cursor));
    cursor.setDate(cursor.getDate() + 1);
  }
  return dates;
}

/** 生成与批次指标大致一致的确定性净值曲线与年度指标 */
function buildEquity(
  row: FactorBacktestRow,
  start: string,
  end: string,
): { equity: EquityPoint[]; yearly: YearlyDatum[] } {
  const dates = tradingDates(start, end);
  if (dates.length === 0) return { equity: [], yearly: [] };

  const annual = clampNumber(row.backtest_annual_return ?? 0, -0.95, 2);
  const sharpe = row.backtest_sharpe ?? 0;
  const totalReturn = clampNumber(
    row.backtest_total_return ?? annual * (dates.length / 252),
    -0.95,
    5,
  );
  const targetLog = Math.log1p(totalReturn);
  const drawdownTarget = Math.min(0.8, Math.abs(row.backtest_max_drawdown ?? 0.12));
  const random = seedFrom(`${row.factor_id ?? "factor"}|${start}|${end}`);
  const count = dates.length;
  const dailyVol = clampNumber(
    Math.abs(annual) / Math.max(Math.abs(sharpe), 0.8) / Math.sqrt(252),
    0.002,
    0.06,
  );
  const noise = Array.from({ length: count }, () => dailyVol * gaussian(random));
  const noiseMean = noise.reduce((sum, value) => sum + value, 0) / count;
  const drift = targetLog / count;
  const baseLogs: number[] = [];
  let logValue = 0;
  for (const value of noise) {
    logValue += value - noiseMean + drift;
    baseLogs.push(logValue);
  }

  // 中段加一个平滑回撤，使曲线形态与最大回撤指标接近；同时保证终点不变
  const center = 0.4 + random() * 0.25;
  const width = 0.12 + random() * 0.05;
  const depth = drawdownTarget * 0.68;
  const dip = (x: number) => depth * Math.exp(-((x - center) ** 2) / (2 * width ** 2));
  const correction = dip(1) / Math.max(1, count - 1);

  const equity: EquityPoint[] = [];
  let peak = 1;
  for (let index = 0; index < count; index += 1) {
    const x = count <= 1 ? 0 : index / (count - 1);
    const value = Math.exp(baseLogs[index] - dip(x) + correction * index);
    peak = Math.max(peak, value);
    equity.push({
      date: dates[index],
      equity: Number(value.toFixed(4)),
      drawdown: Number((((value / peak) - 1) * 100).toFixed(2)),
    });
  }
  equity[0] = { date: dates[0], equity: 1, drawdown: 0 };

  const yearBuckets = new Map<string, EquityPoint[]>();
  for (const point of equity) {
    const year = point.date.slice(0, 4);
    const bucket = yearBuckets.get(year) ?? [];
    bucket.push(point);
    yearBuckets.set(year, bucket);
  }
  const yearEntries = [...yearBuckets.entries()];
  const yearly: YearlyDatum[] = yearEntries.map(([year, points], index) => {
    const previousPoints = index === 0 ? [] : yearEntries[index - 1][1];
    const previous = index === 0
      ? 1
      : previousPoints[previousPoints.length - 1]?.equity ?? 1;
    const last = points[points.length - 1]?.equity ?? previous;
    return {
      year,
      returns: Number(((last / previous - 1) * 100).toFixed(2)),
      sharpe: Number((row.backtest_sharpe ?? 0).toFixed(2)),
      drawdown: Number(Math.min(...points.map((point) => point.drawdown)).toFixed(2)),
      turnover: Number(((row.backtest_average_turnover ?? 0) * 100).toFixed(2)),
      cost: Number((((row.backtest_total_cost ?? 0) * 100) / Math.max(1, yearEntries.length)).toFixed(2)),
      winRate: Number(((row.backtest_win_rate ?? 0) * 100).toFixed(2)),
    };
  });

  return { equity, yearly };
}

export function buildPrototypeResultDetail(
  run: PrototypeFactorRun,
  factor: PrototypeFactor,
  row: FactorBacktestRow,
  detail: PrototypeBatchDetail,
): ResultDetail {
  const { batch, params } = detail;
  const start = batch.start_date ?? params.start_date;
  const end = batch.end_date ?? params.end_date;
  const factorId = String(row.factor_id ?? factor.factor_id);
  const { equity, yearly } = buildEquity(row, start, end);
  const pct = (value: number | null | undefined) => (
    value == null || !Number.isFinite(value) ? null : Number((value * 100).toFixed(4))
  );
  const summary: Record<string, number | null> = {
    total_return: row.backtest_total_return ?? null,
    annual_return: row.backtest_annual_return ?? null,
    sharpe: row.backtest_sharpe ?? null,
    max_drawdown: row.backtest_max_drawdown ?? null,
    calmar: row.backtest_calmar ?? null,
    win_rate: row.backtest_win_rate ?? null,
    average_turnover: row.backtest_average_turnover ?? null,
    total_cost: row.backtest_total_cost ?? null,
    annual_cost: row.backtest_annual_cost ?? null,
    number_of_trades: row.backtest_number_of_trades ?? null,
    average_holding_count: row.backtest_average_holding_count ?? null,
  };

  return {
    run_name: `${factorId} · 单因子回测`,
    run_key: `prototype/factor/${batch.backtest_id}/${factorId}`,
    created_at: batch.created_at,
    result_type: "factor",
    canonical_expression: factor.expression,
    pool_id: run.pool_id,
    factor_run_id: run.run_id,
    backtest_id: batch.backtest_id,
    data_source: "prototype",
    config: {
      start_date: start,
      end_date: end,
      top_k: batch.top_k ?? params.top_k,
      initial_cash: batch.initial_cash ?? params.initial_cash,
      buy_cost: params.buy_cost,
      sell_cost: params.sell_cost,
      slippage: params.slippage,
      min_cost: params.min_cost,
      max_weight_per_stock: params.max_weight_per_stock,
      factor: {
        expression: factor.expression,
        ic: factor.ic,
        rank_ic: factor.rank_ic,
        icir: factor.icir,
        coverage: factor.coverage,
        score: factor.score,
        accepted: true,
        pool_id: run.pool_id,
        category: factor.category,
        category_reason: factor.category_reason,
      },
      prototype: {
        algorithm: run.algorithm_label,
        fields: run.config.fields,
        operators: run.config.operators,
      },
    },
    summary,
    metrics: {
      annual: pct(row.backtest_annual_return),
      sharpe: row.backtest_sharpe ?? null,
      drawdown: pct(row.backtest_max_drawdown),
      turnover: pct(row.backtest_average_turnover),
      cost: pct(row.backtest_total_cost),
      winRate: pct(row.backtest_win_rate),
    },
    equity,
    yearly,
    files: [],
  };
}
