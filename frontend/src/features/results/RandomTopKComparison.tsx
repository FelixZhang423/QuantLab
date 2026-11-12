import { Descriptions, Divider, Tooltip } from "antd";

export function RandomTopKComparison({ summary }: { summary: Record<string, number | null> }) {
  if (!summary.random_topk_runs) return null;

  const percent = (value: number | null | undefined) =>
    value == null ? "—" : `${(value * 100).toFixed(2)}%`;
  const difference = summary.total_return != null && summary.random_topk_median != null
    ? `${((summary.total_return - summary.random_topk_median) * 100).toFixed(2)} 个百分点`
    : "—";
  return (
    <>
      <Divider orientation="left">随机 TopK 对照（{summary.random_topk_runs} 次）</Divider>
      <Descriptions size="small" column={2} items={[
        { key: "low", label: <Tooltip title="随机回测累计收益的第 10 百分位，反映分布的较低端。"><span tabIndex={0}>随机累计收益 P10</span></Tooltip>, children: percent(summary.random_topk_p10) },
        { key: "median", label: <Tooltip title="随机回测累计收益的第 50 百分位。"><span tabIndex={0}>随机累计收益中位数</span></Tooltip>, children: percent(summary.random_topk_median) },
        { key: "high", label: <Tooltip title="随机回测累计收益的第 90 百分位，反映分布的较高端。"><span tabIndex={0}>随机累计收益 P90</span></Tooltip>, children: percent(summary.random_topk_p90) },
        { key: "strategy", label: <Tooltip title="策略期末净值减去 1，已计入交易费用和滑点。"><span tabIndex={0}>策略累计收益</span></Tooltip>, children: percent(summary.total_return) },
        { key: "difference", label: <Tooltip title="策略累计收益减去随机累计收益中位数，以百分点表示。"><span tabIndex={0}>策略较随机中位数</span></Tooltip>, children: difference },
        { key: "win", label: <Tooltip title="累计收益严格低于策略的随机回测次数除以总次数。"><span tabIndex={0}>策略跑赢随机的比例</span></Tooltip>, children: percent(summary.random_topk_win_fraction) },
      ]} />
    </>
  );
}
