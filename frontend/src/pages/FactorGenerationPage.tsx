import { useEffect, useMemo, useState } from "react";
import {
  Alert, Button, Card, Col, Descriptions, Divider, Empty, Flex, Input, Progress, Row, Select,
  Skeleton, Space, Statistic, Table, Tag, Tooltip, Typography,
} from "antd";
import type { TableColumnsType } from "antd";
import {
  BarChartOutlined, ExperimentOutlined, PlayCircleOutlined, ReloadOutlined, SearchOutlined,
} from "@ant-design/icons";
import { api, useApiData } from "../api/client";
import {
  CATEGORY_META, CATEGORY_ORDER, OPERATOR_FAMILY_LABELS,
  buildGenerationInsight, buildOperatorCategoryMap, classifyExpression, countFactorCategories,
  factorDataSourceLabel, formatFraction, formatNumber, metricNumber,
  type FactorCategoryKey, type FactorView,
} from "../factorInsights";
import { FactorCategoryChips } from "../components/FactorCategoryChips";
import type { PageNav } from "./DataPages";

const { Text, Paragraph } = Typography;

function manifestString(manifest: Record<string, unknown>, key: string): string | null {
  const value = manifest[key];
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

function manifestRecord(manifest: Record<string, unknown>, key: string): Record<string, unknown> {
  const value = manifest[key];
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

export function FactorGenerationPage({ navigate }: { navigate: PageNav }) {
  const runsApi = useApiData(api.factorRuns);
  const operatorsApi = useApiData(api.operators);
  const runs = useMemo(() => runsApi.data?.runs ?? [], [runsApi.data]);

  const [runId, setRunId] = useState<string | undefined>();
  const [categoryFilter, setCategoryFilter] = useState<FactorCategoryKey | "all">("all");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  useEffect(() => {
    if (runs.length === 0) {
      setRunId(undefined);
      return;
    }
    if (!runId || !runs.some((run) => run.run_id === runId)) setRunId(runs[0].run_id);
  }, [runs, runId]);

  const runDetailApi = useApiData(
    () => (runId ? api.factorRun(runId) : Promise.resolve(null)),
    [runId],
  );
  const runDetail = runDetailApi.data?.run_id === runId ? runDetailApi.data : null;

  const operatorMap = useMemo(
    () => buildOperatorCategoryMap(operatorsApi.data?.operators ?? []),
    [operatorsApi.data],
  );
  const factorViews = useMemo<FactorView[]>(
    () => (runDetail?.accepted_factors ?? []).map((factor) => ({
      ...factor,
      ...classifyExpression(factor.expression, operatorMap),
    })),
    [runDetail, operatorMap],
  );
  const counts = useMemo(() => countFactorCategories(factorViews), [factorViews]);

  useEffect(() => {
    setCategoryFilter("all");
    setSearch("");
    setPage(1);
  }, [runId]);
  useEffect(() => {
    setPage(1);
  }, [categoryFilter, search, pageSize]);

  const filteredFactors = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    return factorViews.filter((factor) => {
      if (categoryFilter !== "all" && factor.category !== categoryFilter) return false;
      if (!keyword) return true;
      const haystack = [
        factor.factor_id, factor.expression, factor.canonical_expression ?? "",
        factor.tags.join(" "), CATEGORY_META[factor.category].label,
        OPERATOR_FAMILY_LABELS[factor.operatorFamily],
      ].join(" ").toLowerCase();
      return haystack.includes(keyword);
    });
  }, [factorViews, categoryFilter, search]);

  const bestIcir = useMemo(
    () => factorViews.reduce<number | null>((best, factor) => {
      const value = metricNumber(factor.icir);
      return value == null ? best : best == null ? value : Math.max(best, value);
    }, null),
    [factorViews],
  );
  const bestScore = useMemo(
    () => factorViews.reduce<number | null>((best, factor) => {
      const value = metricNumber(factor.score);
      return value == null ? best : best == null ? value : Math.max(best, value);
    }, null),
    [factorViews],
  );
  const summary = useMemo(
    () => buildGenerationInsight(runDetail, factorViews),
    [runDetail, factorViews],
  );

  const manifest = runDetail?.manifest ?? {};
  const quality = manifestRecord(manifest, "quality");
  const qualityParts = [
    metricNumber(quality.min_coverage) != null ? `覆盖率 ≥ ${formatFraction(quality.min_coverage, 1)}` : null,
    metricNumber(quality.min_train_ic) != null ? `训练 IC ≥ ${formatNumber(quality.min_train_ic, 3)}` : null,
    metricNumber(quality.min_valid_ic) != null ? `验证 IC ≥ ${formatNumber(quality.min_valid_ic, 3)}` : null,
    metricNumber(quality.min_icir) != null ? `ICIR ≥ ${formatNumber(quality.min_icir, 2)}` : null,
  ].filter(Boolean).join("；");
  const demoNote = manifestString(manifest, "demo_note");
  const qualityMode = manifestString(manifest, "quality_mode");
  const cli = `py -3 -m custom_bt.cli generate-factors --pool ${runDetail?.pool_id ?? "<pool_id>"} --config configs/factor_generation.yaml`;

  const columns: TableColumnsType<FactorView> = [
    {
      title: "因子 ID", dataIndex: "factor_id", width: 190,
      render: (value: string) => <Text code style={{ whiteSpace: "nowrap" }}>{value}</Text>,
    },
    {
      title: "表达式", dataIndex: "expression", ellipsis: true,
      render: (value: string) => (
        <Tooltip title={value}><Text code>{value}</Text></Tooltip>
      ),
    },
    {
      title: "类别", key: "category", width: 164,
      sorter: (a, b) => CATEGORY_META[a.category].label.localeCompare(CATEGORY_META[b.category].label, "zh-CN"),
      render: (_, row) => (
        <Space size={4} wrap>
          <Tooltip title={CATEGORY_META[row.category].description}>
            <Tag color={CATEGORY_META[row.category].color}>{CATEGORY_META[row.category].label}</Tag>
          </Tooltip>
          <Tag>{OPERATOR_FAMILY_LABELS[row.operatorFamily]}</Tag>
        </Space>
      ),
    },
    {
      title: "标签", dataIndex: "tags", width: 136,
      render: (tags: string[]) => (
        tags.length > 0
          ? <Space size={4} wrap>{tags.map((tag) => <Tag key={tag}>{tag}</Tag>)}</Space>
          : <Text type="secondary">—</Text>
      ),
    },
    {
      title: "IC", dataIndex: "ic", align: "right", width: 82,
      sorter: (a, b) => (metricNumber(a.ic) ?? -Infinity) - (metricNumber(b.ic) ?? -Infinity),
      render: (value) => formatNumber(value, 4),
    },
    {
      title: "RankIC", dataIndex: "rank_ic", align: "right", width: 88,
      sorter: (a, b) => (metricNumber(a.rank_ic) ?? -Infinity) - (metricNumber(b.rank_ic) ?? -Infinity),
      render: (value) => formatNumber(value, 4),
    },
    {
      title: "ICIR", dataIndex: "icir", align: "right", width: 78,
      sorter: (a, b) => (metricNumber(a.icir) ?? -Infinity) - (metricNumber(b.icir) ?? -Infinity),
      render: (value) => formatNumber(value),
    },
    {
      title: "覆盖率", dataIndex: "coverage", align: "right", width: 88,
      sorter: (a, b) => (metricNumber(a.coverage) ?? -Infinity) - (metricNumber(b.coverage) ?? -Infinity),
      render: (value) => formatFraction(value, 1),
    },
    {
      title: "Score", dataIndex: "score", align: "right", width: 80,
      sorter: (a, b) => (metricNumber(a.score) ?? -Infinity) - (metricNumber(b.score) ?? -Infinity),
      render: (value) => formatNumber(value),
    },
    {
      title: "操作", key: "action", width: 108, align: "right",
      render: (_, row) => (
        <Button
          type="link" size="small" icon={<PlayCircleOutlined />}
          onClick={() => navigate("factor_backtest", undefined, undefined, {
            runId: runDetail?.run_id,
            category: row.category,
          })}
        >
          回测同类
        </Button>
      ),
    },
  ];

  return (
    <Space direction="vertical" size={16} className="page-stack">
      <Card className="filter-card">
        <Flex justify="space-between" gap={16} wrap align="center">
          <Space wrap>
            <Text strong><ExperimentOutlined /> 因子运行</Text>
            <Select
              value={runId}
              onChange={setRunId}
              className="factor-run-select"
              loading={runsApi.loading}
              showSearch optionFilterProp="label"
              placeholder={runsApi.error ? "因子运行目录不可读" : "选择已生成的因子运行"}
              options={runs.map((run) => ({
                value: run.run_id,
                label: `${run.run_id} · ${run.pool_id ?? "未知池"} · ${run.accepted_count} 个合格因子`,
              }))}
            />
            <Button
              size="small" icon={<ReloadOutlined />} loading={runsApi.loading}
              onClick={() => { runsApi.reload(); operatorsApi.reload(); runDetailApi.reload(); }}
            >
              刷新
            </Button>
            {runDetail && <Tag color="blue">{factorViews.length} 个合格因子</Tag>}
            {manifest.demo === true && <Tag color="warning">联调运行</Tag>}
          </Space>
          {runDetail && (
            <Button
              type="primary" icon={<PlayCircleOutlined />}
              onClick={() => navigate("factor_backtest", undefined, undefined, {
                runId: runDetail.run_id,
                category: categoryFilter === "all" ? undefined : categoryFilter,
              })}
            >
              去回测{categoryFilter === "all" ? "全部因子" : "当前类别"}
            </Button>
          )}
        </Flex>
      </Card>

      {runsApi.error && (
        <Alert
          type="error" showIcon message="无法读取因子运行列表" description={runsApi.error}
          action={<Button size="small" icon={<ReloadOutlined />} onClick={runsApi.reload}>重试</Button>}
        />
      )}
      {!runsApi.loading && !runsApi.error && runs.length === 0 && (
        <Card>
          <Empty description="factor_runs 下还没有已完成的因子生成运行">
            <Space direction="vertical" size={8} align="center">
              <Text type="secondary">在 backend 目录执行 CLI 生成后，本页会自动读取真实结果。</Text>
              <Paragraph className="factor-cli" copyable={{ text: "py -3 -m custom_bt.cli generate-factors --pool <pool_id> --config configs/factor_generation.yaml" }}>
                <Text code>py -3 -m custom_bt.cli generate-factors --pool &lt;pool_id&gt; --config configs/factor_generation.yaml</Text>
              </Paragraph>
            </Space>
          </Empty>
        </Card>
      )}

      {runId && runDetailApi.error && (
        <Alert
          type="error" showIcon message="因子运行详情加载失败" description={runDetailApi.error}
          action={<Button size="small" icon={<ReloadOutlined />} onClick={runDetailApi.reload}>重试</Button>}
        />
      )}
      {runId && runDetailApi.loading && !runDetail && (
        <Card><Skeleton active paragraph={{ rows: 8 }} /></Card>
      )}

      {runDetail && (
        <>
          <Row gutter={12}>
            <Col span={6}>
              <Card className="metric-card metric-blue">
                <Statistic title="合格因子" value={factorViews.length} suffix="个" />
              </Card>
            </Col>
            <Col span={6}>
              <Card className="metric-card metric-violet">
                <Statistic title="覆盖类别" value={CATEGORY_ORDER.filter((key) => counts[key] > 0).length} suffix="类" />
              </Card>
            </Col>
            <Col span={6}>
              <Card className="metric-card metric-green">
                <Statistic title="最佳 ICIR" value={bestIcir == null ? "—" : bestIcir.toFixed(2)} />
              </Card>
            </Col>
            <Col span={6}>
              <Card className="metric-card metric-cyan">
                <Statistic title="最佳 Score" value={bestScore == null ? "—" : bestScore.toFixed(2)} />
              </Card>
            </Col>
          </Row>

          <Row gutter={16}>
            <Col span={16}>
              <Card
                size="small"
                className="factor-summary-card data-card"
                title={<Space><BarChartOutlined />生成小结<Tag color="blue">自动生成</Tag></Space>}
              >
                <Paragraph className="factor-summary-text">{summary}</Paragraph>
                <Space size={6} wrap>
                  {CATEGORY_ORDER.filter((key) => counts[key] > 0).map((key) => (
                    <Tag key={key} color={CATEGORY_META[key].color}>
                      {CATEGORY_META[key].label} {counts[key]}
                    </Tag>
                  ))}
                  <Text type="secondary">共 {factorViews.length} 个合格因子</Text>
                </Space>
              </Card>
            </Col>
            <Col span={8}>
              <Card
                size="small" title="类别分布" className="data-card"
                extra={<Text type="secondary">{factorViews.length} 个</Text>}
              >
                <Space direction="vertical" size={8} className="full-width">
                  {CATEGORY_ORDER.filter((key) => counts[key] > 0).map((key) => (
                    <div
                      key={key} className="factor-category-meter"
                      onClick={() => setCategoryFilter(key)}
                      title={`只看${CATEGORY_META[key].label}类因子`}
                    >
                      <Flex justify="space-between">
                        <Text>{CATEGORY_META[key].label}</Text>
                        <Text strong>{counts[key]}</Text>
                      </Flex>
                      <Progress
                        percent={Math.round((counts[key] / Math.max(1, factorViews.length)) * 100)}
                        showInfo={false} strokeColor={CATEGORY_META[key].stroke} size="small"
                      />
                    </div>
                  ))}
                  {factorViews.length === 0 && (
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无合格因子" />
                  )}
                </Space>
              </Card>
            </Col>
          </Row>

          <Card
            title={<Space><ExperimentOutlined />合格因子清单</Space>}
            extra={<Text type="secondary">当前筛选 {filteredFactors.length} / {factorViews.length}</Text>}
            className="data-card"
          >
            <Flex justify="space-between" align="center" gap={12} wrap className="factor-toolbar">
              <FactorCategoryChips counts={counts} value={categoryFilter} onChange={setCategoryFilter} />
              <Input
                allowClear value={search}
                onChange={(event) => setSearch(event.target.value)}
                prefix={<SearchOutlined />}
                placeholder="搜索因子 ID / 表达式 / 标签"
                style={{ width: 260 }}
              />
            </Flex>
            <Divider style={{ margin: "10px 0 12px" }} />
            <Table
              rowKey="factor_id" size="middle" columns={columns}
              dataSource={filteredFactors} loading={runDetailApi.loading}
              scroll={{ x: 1120 }}
              locale={{ emptyText: factorViews.length === 0 ? "该运行没有合格因子" : "没有符合当前筛选条件的因子" }}
              pagination={{
                current: page, pageSize, total: filteredFactors.length,
                showSizeChanger: true, pageSizeOptions: [10, 20, 50],
                showTotal: (total) => `共 ${total} 个`,
                onChange: (nextPage, nextSize) => {
                  setPage(nextPage);
                  setPageSize(nextSize);
                },
              }}
            />
          </Card>

          <Row gutter={16}>
            <Col span={16}>
              <Card size="small" title="运行信息" className="data-card">
                <Descriptions column={3} size="small" bordered items={[
                  { key: "pool", label: "股票池", children: runDetail.pool_id ?? "—" },
                  { key: "runtime", label: "Runtime", children: <Text code>{runDetail.runtime_id ?? "—"}</Text> },
                  { key: "source", label: "数据源", children: factorDataSourceLabel(runDetail.data_source) },
                  {
                    key: "created", label: "生成时间",
                    children: runDetail.created_at ? String(runDetail.created_at).replace("T", " ") : "—",
                  },
                  { key: "attempts", label: "尝试次数", children: runDetail.attempts ?? "—" },
                  {
                    key: "target", label: "目标状态",
                    children: runDetail.target_reached
                      ? <Tag color="success">已达成</Tag>
                      : runDetail.attempts_exhausted
                        ? <Tag color="warning">尝试耗尽</Tag>
                        : <Tag>未达成</Tag>,
                  },
                  { key: "quality", label: "质量阈值", children: qualityParts || "—" },
                ]} />
                {(qualityMode || manifest.demo === true) && (
                  <Alert
                    className="factor-demo-note"
                    type={manifest.demo === true ? "warning" : "info"}
                    showIcon
                    message={manifest.demo === true ? "联调运行（非 PPO 训练）" : `质量模式：${qualityMode}`}
                    description={demoNote ?? undefined}
                  />
                )}
              </Card>
            </Col>
            <Col span={8}>
              <Card size="small" title="发起新的生成" className="data-card">
                <Alert
                  type="info" showIcon
                  message="Web 端暂未开放生成提交"
                  description="本页展示 factor_runs 中已完成的真实运行；新的 PPO 生成请在 backend 目录用 CLI 发起。"
                />
                <Paragraph className="factor-cli" copyable={{ text: cli }}>
                  <Text code>{cli}</Text>
                </Paragraph>
              </Card>
            </Col>
          </Row>
        </>
      )}
    </Space>
  );
}
