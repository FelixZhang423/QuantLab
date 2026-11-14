import { useEffect, useRef, useState } from "react";
import { Alert, Button, Descriptions, Drawer, Empty, Select, Space, Spin, Table, Tag, Typography } from "antd";
import * as echarts from "echarts";
import { apiGet, useApiData, withQuery } from "../../shared/api/base";
import type { StockInfo } from "./api";

const fields = [
  ["open", "开盘"], ["high", "最高"], ["low", "最低"], ["close", "收盘"],
  ["previous_close", "昨收"], ["volume", "成交量"], ["amount", "成交额"],
  ["change_pct", "涨跌幅"], ["range_pct", "振幅"], ["turnover_pct", "换手率"],
] as const;
type Daily = { date: string; suspended: number | null } & Record<(typeof fields)[number][0], number | null>;

function StockChart({ rows }: { rows: Daily[] }) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!host.current) return;
    const chart = echarts.init(host.current);
    const dates = rows.map((row) => row.date);
    chart.setOption({
      animation: false,
      tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
      axisPointer: { link: [{ xAxisIndex: [0, 1] }] },
      grid: [
        { left: 68, right: 25, top: 16, height: "55%" },
        { left: 68, right: 25, top: "64%", height: "20%" },
      ],
      xAxis: [
        { type: "category", data: dates, axisLabel: { show: false } },
        { type: "category", data: dates, gridIndex: 1 },
      ],
      yAxis: [{ scale: true }, { gridIndex: 1, splitNumber: 2 }],
      dataZoom: [{ type: "inside", xAxisIndex: [0, 1] }, { type: "slider", xAxisIndex: [0, 1], bottom: 5 }],
      series: [
        { name: "日 K 线", type: "candlestick", itemStyle: {
          color: "#cf1322", borderColor: "#cf1322", color0: "#389e0d", borderColor0: "#389e0d",
        }, data: rows.map((row) => {
          const prices = [row.open, row.close, row.low, row.high];
          return row.suspended === 1 || prices.some((price) => price == null) ? "-" : prices;
        }) },
        { name: "成交量", type: "bar", xAxisIndex: 1, yAxisIndex: 1, itemStyle: { color: "#597ef7" },
          data: rows.map((row) => row.volume) },
      ],
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(host.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [rows]);
  return <div ref={host} style={{ height: 380 }} role="img" aria-label="日 K 线和成交量图，数值也可在下方历史行情表查看" />;
}

export function StockDetail({ stock, onClose }: { stock: StockInfo; onClose: () => void }) {
  const [days, setDays] = useState(60);
  const history = useApiData(() => apiGet<{ rows: Daily[] }>(withQuery(
    `/api/data/stocks/${encodeURIComponent(stock.code)}/history`, { days, end: stock.latest_date?.slice(0, 10) },
  )), [stock.code, stock.latest_date, days]);
  const rows = history.data?.rows ?? [];
  return <Drawer open title={`${stock.name ?? "股票详情"} · ${stock.code}`} onClose={onClose} width="min(1040px, 100vw)"
    extra={<Space>
      <Select aria-label="行情区间" value={days} onChange={setDays}
        options={[20, 60, 120, 250].map((value) => ({ value, label: `近 ${value} 个交易日` }))} />
      <Button onClick={history.reload} loading={history.loading}>刷新</Button>
    </Space>}>
    <Space direction="vertical" size="middle" className="full-width">
      <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 3 }} items={[
        { key: "market", label: "市场 / 板块", children: [stock.exchange, stock.board].filter(Boolean).join(" / ") || "—" },
        { key: "industry", label: "行业", children: stock.industry ?? "—" },
        { key: "date", label: "最近行情日", children: stock.latest_date || "—" },
      ]} />
      {history.error ? <Alert type="error" showIcon message="行情加载失败" description={history.error} />
        : history.loading ? <Spin />
        : rows.length === 0 ? <Empty description="该股票暂无历史行情" />
        : <>
          <Typography.Text type="secondary">价格沿用公司库口径。停牌日和价格缺失日不绘制 K 线。</Typography.Text>
          <StockChart rows={rows} />
          <Table size="small" rowKey="date" dataSource={[...rows].reverse()} scroll={{ x: 960 }}
            pagination={{ pageSize: 10, hideOnSinglePage: true }} columns={[
              { title: "交易日", dataIndex: "date", fixed: "left", width: 110 },
              ...fields.map(([key, title]) => ({
                title, dataIndex: key, align: "right" as const,
                render: (value: number | null) => value == null ? "—"
                  : `${value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}${key.endsWith("_pct") ? "%" : ""}`,
              })),
              { title: "交易状态", dataIndex: "suspended", render: (value: number | null) =>
                value === 1 ? <Tag color="orange">停牌</Tag> : value === 0 ? "正常" : "—" },
            ]} />
        </>}
    </Space>
  </Drawer>;
}
