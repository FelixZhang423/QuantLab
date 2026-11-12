import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import type { EquityPoint, YearlyDatum } from "../features/results/mock";

const equityMetricHelp: Record<string, string> = {
  "策略净值": "当日收盘账户总资产除以初始资金，已计入交易费用和滑点。",
  "回撤": "策略净值相对截至当日的历史最高净值的跌幅，使用右侧百分比轴。",
  "同池等权净值": "在相同股票池和交易规则下，按调仓频率恢复等权后的净值，已计入交易成本。",
  "相对净值": "策略净值除以同池等权净值。高于 1 表示累计表现领先基线。",
};

export function EquityChart({ data, compact = false }: { data: EquityPoint[]; compact?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    const hasBenchmark = data.some((point) => point.benchmark_equity != null);
    chart.setOption({
      animationDuration: 650,
      color: ["#1677ff", "#ff7875", "#13a08e", "#722ed1"],
      tooltip: {
        trigger: "axis",
        backgroundColor: "rgba(15, 23, 42, .94)",
        borderWidth: 0,
        textStyle: { color: "#fff" },
        formatter: (params: Array<{ axisValue: string; marker: string; seriesName: string; value: number }>) =>
          `<b>${params[0].axisValue}</b><br/>${params.map((p) => `${p.marker}${p.seriesName}：${p.value}${p.seriesName === "回撤" ? "%" : ""}`).join("<br/>")}`,
      },
      legend: { tooltip: { show: true, formatter: ({ name }: { name: string }) => equityMetricHelp[name] ?? "" }, data: ["策略净值", "回撤", ...(hasBenchmark ? ["同池等权净值", "相对净值"] : [])], top: 0, right: 8, textStyle: { color: "#64748b" } },
      grid: { left: 48, right: 54, top: 38, bottom: compact ? 28 : 48 },
      xAxis: { type: "category", boundaryGap: false, data: data.map((p) => p.date), axisLabel: { hideOverlap: true } },
      yAxis: [
        // 演示数据净值 ≥ 0.9 时保持原视觉；真实回测净值可能远低于 0.9，按数据自适应下界
        { type: "value", max: (value: { max: number }) => Math.max(1, Math.ceil(value.max * 20) / 20), min: (value: { min: number }) => (value.min < 0.9 ? Math.floor((value.min - 0.05) * 20) / 20 : 0.9), splitLine: { lineStyle: { color: "#eef1f5" } }, axisLabel: { formatter: "{value}" } },
        { type: "value", max: 0, min: (value: { min: number }) => (value.min < -1 ? Math.ceil(value.min * 1.05) : -16), axisLabel: { formatter: "{value}%" }, splitLine: { show: false } },
      ],
      dataZoom: compact ? [] : [{ type: "inside" }, { type: "slider", height: 16, bottom: 4 }],
      series: [
        {
          name: "策略净值", type: "line", smooth: 0.28, showSymbol: false, lineStyle: { width: 2.4 },
          areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: "rgba(22,119,255,.22)" }, { offset: 1, color: "rgba(22,119,255,.02)" }]) },
          data: data.map((p) => p.equity),
        },
        {
          name: "回撤", type: "line", yAxisIndex: 1, showSymbol: false, lineStyle: { width: 1.2, opacity: 0.7 },
          areaStyle: { color: "rgba(255,77,79,.12)" }, data: data.map((p) => p.drawdown),
        },
        ...(hasBenchmark ? [
          { name: "同池等权净值", type: "line", showSymbol: false, data: data.map((p) => p.benchmark_equity ?? null) },
          { name: "相对净值", type: "line", showSymbol: false, lineStyle: { type: "dashed" }, data: data.map((p) => p.relative_equity ?? null) },
        ] : []),
        {
          name: "净值参考线", type: "line", data: [], silent: true, color: "#94a3b8",
          markLine: {
            silent: true,
            symbol: "none",
            lineStyle: { type: "dashed", color: "#94a3b8" },
            label: { show: false },
            data: [{ yAxis: 1 }],
          },
        },
      ],
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(ref.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [compact, data]);
  return <div className={compact ? "chart chart-compact" : "chart"} ref={ref} />;
}

export function YearlyChart({ data }: { data: YearlyDatum[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chart.setOption({
      tooltip: { trigger: "axis", valueFormatter: (value: number) => `${value}%` },
      grid: { left: 44, right: 16, top: 24, bottom: 30 },
      xAxis: { type: "category", data: data.map((p) => p.year) },
      yAxis: { type: "value", axisLabel: { formatter: "{value}%" }, splitLine: { lineStyle: { color: "#eef1f5" } } },
      series: [{
        type: "bar", barMaxWidth: 34, data: data.map((p) => ({
          value: p.returns,
          itemStyle: { color: p.returns >= 0 ? "#f05a5a" : "#27a56a", borderRadius: p.returns >= 0 ? [4, 4, 0, 0] : [0, 0, 4, 4] },
        })),
      }],
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(ref.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [data]);
  return <div className="chart" ref={ref} />;
}
