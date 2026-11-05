export type YearlyDatum = { year: string; returns: number; sharpe: number; drawdown: number; turnover: number; cost: number; winRate: number };

export const yearlyData: YearlyDatum[] = [
  { year: "2021", returns: 8.42, sharpe: 1.08, drawdown: -6.2, turnover: 29.4, cost: 0.48, winRate: 52.1 },
  { year: "2022", returns: -3.76, sharpe: -0.32, drawdown: -12.6, turnover: 36.8, cost: 0.65, winRate: 48.9 },
  { year: "2023", returns: 22.91, sharpe: 1.72, drawdown: -8.4, turnover: 33.5, cost: 0.59, winRate: 56.4 },
  { year: "2024", returns: 16.78, sharpe: 1.31, drawdown: -9.1, turnover: 35.2, cost: 0.63, winRate: 54.6 },
  { year: "2025", returns: 24.35, sharpe: 1.84, drawdown: -7.3, turnover: 34.1, cost: 0.61, winRate: 57.2 },
  { year: "2026", returns: 11.23, sharpe: 1.45, drawdown: -5.8, turnover: 32.6, cost: 0.57, winRate: 55.1 },
];

export type EquityPoint = { date: string; equity: number; drawdown: number };

export function makeEquityData(seed = 0): EquityPoint[] {
  const points: EquityPoint[] = [];
  const phase = (seed % 13) * 0.47;
  const drift = 0.0009 + (seed % 4) * 0.0002;
  const shockA = 62 + (seed % 20);
  const shockB = 168 + (seed % 15);
  let equity = 1;
  let peak = 1;
  for (let i = 0; i < 250; i += 1) {
    const shock = (i > shockA && i < shockA + 24 ? -0.0028 : 0) + (i > shockB && i < shockB + 18 ? -0.0038 : 0);
    const daily = drift + Math.sin(i * 0.31 + phase) * 0.0018 + Math.cos(i * 0.13 + phase * 0.7) * 0.0011 + shock;
    equity *= 1 + daily;
    peak = Math.max(peak, equity);
    const date = new Date(2025, 5, 17 + i);
    points.push({
      date: `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`,
      equity: Number(equity.toFixed(4)),
      drawdown: Number((((equity / peak) - 1) * 100).toFixed(2)),
    });
  }
  return points;
}

export const equityData = makeEquityData();
