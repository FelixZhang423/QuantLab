# 独立因子研究系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立一个无前端、只消费独立 `research_data` 快照的因子研究流水线，并提供从原系统导出数据的命令。

**Architecture:** 根目录新增 `research_pipeline/` 作为独立 Python 包，新增 `research_data/` 作为版本化数据目录。导出器只通过文件格式读取原系统；研究模块只通过 `research_pipeline.io` 读取快照，不导入原系统包。

**Tech Stack:** Python 3.10+、pandas、numpy、pyarrow、PyYAML、pytest。

---

### Task 1: 建立独立包和数据契约

**Files:**
- Create: `research_pipeline/research_system/__init__.py`
- Create: `research_pipeline/research_system/schema.py`
- Create: `research_pipeline/research_system/io.py`
- Create: `research_pipeline/tests/test_io_schema.py`

- [ ] **Step 1: Write the failing test**

测试 `normalize_market_frame` 能把 `timestamps`/`vol` 标准化为 `date`/`volume`，并让股票代码补齐六位；测试缺失 `(date, code)` 时抛出 `ValueError`。

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest research_pipeline/tests/test_io_schema.py -q`
Expected: FAIL，因为模块尚未存在。

- [ ] **Step 3: Write minimal implementation**

在 `schema.py` 定义 `MARKET_REQUIRED_COLUMNS`、`FACTOR_REQUIRED_COLUMNS`、`BACKTEST_REQUIRED_COLUMNS`、`SNAPSHOT_VERSION`。在 `io.py` 实现 `normalize_code`、`normalize_market_frame`、`validate_unique_keys`、`file_sha256`、`write_json` 和只读取 snapshot 的 `load_snapshot_table`。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest research_pipeline/tests/test_io_schema.py -q`
Expected: PASS。

### Task 2: 实现从原系统到独立快照的导出器

**Files:**
- Create: `research_pipeline/research_system/exporter.py`
- Create: `research_pipeline/tests/test_exporter.py`
- Create: `research_data/README.md`
- Create: `research_pipeline/config.example.yaml`

- [ ] **Step 1: Write the failing test**

构造临时 panel、pool manifest/codes、factor run JSONL 和回测 summary，断言 `export_snapshot` 生成 `market.parquet`、`universe.csv`、`factor_catalog.parquet`、`factor_metrics.parquet`、`backtest_metrics.parquet`、`manifest.json`，且每个文件有行数和 SHA-256。

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest research_pipeline/tests/test_exporter.py -q`
Expected: FAIL，因为导出器尚未存在。

- [ ] **Step 3: Write minimal implementation**

实现 `ExportSources` 数据类和 `export_snapshot(sources, output_root, snapshot_id=None, overwrite=False)`。导出器只使用 `pathlib`、`json`、`pandas`、`hashlib`，扫描 `factor_run.json`/`accepted_factors.jsonl` 和 `factor_backtest_summary.csv`；缺失可选目录导出空表并在 manifest 写 warning，缺失行情或股票池必需文件则失败。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest research_pipeline/tests/test_exporter.py -q`
Expected: PASS。

### Task 3: 市场状态、未来收益和条件评价

**Files:**
- Create: `research_pipeline/research_system/features.py`
- Create: `research_pipeline/research_system/evaluation.py`
- Create: `research_pipeline/tests/test_research_metrics.py`

- [ ] **Step 1: Write the failing test**

用 3 只股票的合成价格和因子值断言 `make_forward_return` 按代码向前移动，`market_state_features` 输出波动率和上涨比例，`conditional_ic` 在指定状态下只使用有效日期并返回样本数。

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest research_pipeline/tests/test_research_metrics.py -q`
Expected: FAIL，因为研究模块尚未存在。

- [ ] **Step 3: Write minimal implementation**

实现只依赖独立长表的纯函数：

```python
make_forward_return(market, horizon=20, price_col="close") -> DataFrame
market_state_features(market) -> DataFrame
daily_ic(factor_values, target) -> DataFrame
conditional_ic(factor_values, target, states) -> DataFrame
```

缺失值不填成收益 0；横截面样本少于 3 时指标为空；ICIR 使用日 IC 的均值除以样本标准差，标准差为 0 时为空。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest research_pipeline/tests/test_research_metrics.py -q`
Expected: PASS。

### Task 4: 选择和组合基线

**Files:**
- Create: `research_pipeline/research_system/selection.py`
- Create: `research_pipeline/tests/test_selection.py`

- [ ] **Step 1: Write the failing test**

断言选择器先按状态和类别聚合得分，再在类别内按 `rank_ic` 排序；高度相关的候选因子被记录为 rejection；最终权重归一化且选择日志可审计。

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest research_pipeline/tests/test_selection.py -q`
Expected: FAIL，因为选择器尚未存在。

- [ ] **Step 3: Write minimal implementation**

实现 `score_categories`、`select_factors`、`equal_weight_portfolio`。第一版使用可解释的加权分数和相关性阈值，不引入训练型 MoE 或黑盒权重优化；每条淘汰记录包含 `factor_id`、`reason` 和触发指标。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest research_pipeline/tests/test_selection.py -q`
Expected: PASS。

### Task 5: CLI、配置和文档

**Files:**
- Create: `research_pipeline/research_system/cli.py`
- Create: `research_pipeline/research_system/__main__.py`
- Modify: `research_pipeline/config.example.yaml`
- Modify: `research_data/README.md`

- [ ] **Step 1: Write the failing test**

断言 `python -m research_system --help` 能显示 `export` 和 `validate`，并且 validate 对无效快照返回非零退出码。

- [ ] **Step 2: Run test to verify it fails**

Run: `$env:PYTHONPATH='research_pipeline'; python -m research_system --help`
Expected: FAIL，因为 CLI 尚未存在。

- [ ] **Step 3: Write minimal implementation**

实现 `export` 和 `validate` 两个命令；`export` 从 YAML 加载路径，`validate` 检查 manifest、必需文件、列和哈希。命令入口不导入 `custom_bt` 或 `single_factor`。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest research_pipeline/tests -q`
Expected: PASS。

### Task 6: 真实数据导出与全量验证

**Files:**
- Create: `research_data/snapshots/<generated_snapshot>/...`
- Modify: `task_plan.md`
- Modify: `findings.md`
- Modify: `progress.md`

- [ ] **Step 1: Run the real export**

Run: `$env:PYTHONPATH='research_pipeline'; python -m research_system export --config research_pipeline/config.local.yaml`
Expected: 生成一个新的快照，不修改原系统文件。

- [ ] **Step 2: Validate the real snapshot**

Run: `$env:PYTHONPATH='research_pipeline'; python -m research_system validate --data-root research_data`
Expected: 输出 `valid=true`，并报告行情行数、股票数、因子数和日期范围。

- [ ] **Step 3: Run the complete test suite**

Run: `python -m pytest research_pipeline/tests -q`
Expected: 所有测试通过。

