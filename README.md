# 生成因子＋回测系统

该系统是一个独立的股票**因子生成与回测平台**（不依赖 Qlib）。目前系统实现了从原始日频数据出发，把大规模日频数据变成可复用的股票级 Parquet 缓存 → 用特定股票池约束研究对象 → 通过 PPO 强化学习算法自动搜索可解释表达式生成单因子，之后做单因子有效性检测以进行生成阶段筛选 → 用统一 TopK 回测引擎检验合格因子的交易表现 → 最后通过 mutual IC 去重 + 权重优化把单因子升级为组合因子。

## 核心流程

```
原始 CSV ──► 主缓存(master) ──► 股票池(pool) ──► PPO 因子生成
                                                        │
          结果沉淀 ◄── 因子组合 ◄── 合格因子批量回测 ◄──┘
```

完整的七步数据流：

1. **构建主缓存**：读取原始 CSV，标准化字段后按股票保存为 Parquet，并写入 `meta.json`；
2. **创建股票池**：在主缓存上按流动性、覆盖率、上市天数等规则筛出命名股票池，生成 `pool_id`；
3. **准备生成运行时**：根据 `pool_id` 导出池内面板，切分 train / valid / test 三份缓存；
4. **PPO 因子生成**：在可用字段与操作符空间里搜索表达式，用 IC / RankIC / ICIR / 覆盖率筛出合格因子；
5. **批量回测合格因子**：只回测 `accepted_factors.jsonl` 里通过生成阶段筛选的表达式；
6. **因子组合**：mutual IC 去重 + 权重优化 + 多规模组合回测；
7. **结果沉淀与查看**：所有回测产物进入统一结果中心，可在 Streamlit 中查看、下载、备注。

## 系统架构

系统按职责分为七层：

| 层级 | 核心职责 | 主要模块 |
|---|---|---|
| 数据层 | 读取原始日频 CSV，标准化，按股票落 Parquet | `custom_bt.data` |
| 股票池层 | 按成交额/覆盖率/上市天数等规则生成命名股票池 | `custom_bt.pools` |
| 表达式层 | 本地表达式算子、Brain/AlphaGen 风格表达式转换与校验 | `custom_bt.expressions`、`custom_bt.factor_adapter` |
| 生成层 | 池内面板转 PPO 训练数据，调用 single_factor 生成候选因子 | `custom_bt.factor_generation` + `single_factor` |
| 回测层 | 对手动/合格/组合因子执行 TopK 日频回测 | `custom_bt.engine`、`custom_bt.factor_backtest` |
| 组合层 | mutual IC 去重、权重优化、多规模组合回测 | `custom_bt.factor_composition` |
| 平台层 | CLI、Streamlit 工作台、后台任务、结果中心 | `custom_bt.cli`、`platform_jobs`、`app`、`results` |

### 三个子项目的关系

- **`custom_backtester/`** 是主平台"大脑"，但它**不自己实现 PPO**——`factor_generation.py` 通过 `sys.path` 定位到根目录后 `from single_factor...` 调用生成核心；
- **`single_factor/`** 是独立可部署的 PPO 生成器，内置 vendored 的 AlphaGen 原语，自带 `runtime.json` 和 `run_server.ps1` 守护脚本，脱离主平台也能单独跑；
- **`research_pipeline/`** 是另一套独立的研究流水线（因子分类、表达式引擎、选股、评估、导出），与主平台无关；
- **`custom_bt/ai_research/`** 是用 DeepSeek LLM 驱动的量化研究 agent（`提示词合集/` 里的提示词为其服务）；
- **`quantops/`** 是把 80 个算子（Alpha101 / BRAIN 风格表达式原语）与表达式引擎抽出来的**独立算子库**，只依赖 numpy + pandas、可 `pip install -e` 单独使用；主平台的 `custom_bt/expressions.py` 已改为转发它，**算子的唯一实现就在 `quantops/`**，详见 [quantops/README.md](quantops/README.md)。

### 核心设计原则

- **大文件只导入一次**：约 20GB 的原始 CSV 只在 `prepare-master` 时读取一次，之后全程走缓存；
- **身份锁**：生成、回测、组合必须绑定同一 `master_store`、`pool_id`、`source_signature`；
- **先生成合格因子，再做回测与组合**。

## 目录结构

```
生成因子＋回测系统/
├── custom_backtester/              # 主平台
│   ├── custom_bt/                  #   核心包（data/pools/expressions/engine/factor_* 等）
│   │   └── ai_research/            #   LLM 量化研究 agent（DeepSeek 驱动）
│   ├── app/                        #   Streamlit 工作台（streamlit_app.py + run_streamlit.py）
│   ├── configs/                    #   平台 / 股票池 / 生成 / 回测配置（yaml）
│   ├── tests/                      #   pytest 单元测试
│   ├── data_cache/                 #   数据缓存（master 已入库；stock_daily/sample/pools/factor_runtime 不入库）
│   ├── factor_runs/                #   PPO 生成结果（不入库）
│   └── outputs/                    #   回测 / 组合结果（不入库）
├── quantops/                       # 独立算子库：80 个算子 + 表达式引擎（numpy + pandas，可单独安装）
├── single_factor/                  # 独立 PPO 生成器（含 _vendor/alphagen 原语）
├── research_pipeline/              # 独立研究流水线（research_system/）
├── research_data/                  # 研究数据产物（快照不入库）
├── docs/                           # 设计文档（Word）
├── 提示词合集/                     # LLM agent 提示词模板
├── v_stock_daily_full_字段说明.md
├── README.md
└── .gitignore
```

详细架构见 [docs/生成因子与回测系统整体逻辑说明书.docx](docs/生成因子与回测系统整体逻辑说明书.docx)。

## 环境要求

- Python 3.11（或 3.8）
- conda 环境 `alphagen`
- 仅跑手动回测只需 `custom_backtester` 依赖；跑 PPO 生成还需 `single_factor` 的 torch / stable-baselines3 等

```powershell
conda create -n alphagen python=3.11 -y
conda activate alphagen

# 平台 + 网页工作台
pip install numpy pandas "pyarrow>=12.0" pyyaml matplotlib streamlit plotly certifi "pytest>=7.0"

# PPO 生成（强化学习）
pip install "gymnasium>=0.28" "stable-baselines3>=2.0" "sb3-contrib>=2.0"

# torch（默认 CPU；GPU 请改用 https://download.pytorch.org/whl/cu121）
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

三个子模块各自的依赖见 `custom_backtester/requirements.txt`、`single_factor/requirements.txt`、`research_pipeline/requirements.txt`。

## 快速开始

### 网页工作台

```powershell
cd custom_backtester
python app\run_streamlit.py
```

浏览器打开 http://localhost:8501 。左侧边栏配置路径与全局回测参数；主区 11 个页签：

| 页签 | 作用 |
|---|---|
| 平台任务 | 提交主缓存导入，查看数据规模与字段 |
| 回测 | 手动输入 alpha 表达式回测（可全量或选池） |
| 数据字段 / 股票列表 / 操作符 | 查看字段、股票、算子 |
| 股票池 | 创建 / 查看命名股票池 |
| 因子生成 | 选池 + 字段 + split + PPO 参数，提交生成，查看 accepted factors |
| 因子回测 | 选 factor_run，批量回测合格因子，下载汇总 |
| 因子组合 | 选池 + 单因子运行，设阈值 / mutual IC / 规模，提交组合 |
| 后台任务 | 监控 queued/running/finished/failed 状态与进度 |
| 已保存结果 | 查看 / 下载 manual / factor / composite 回测结果 |

所有耗时操作（导入/生成/回测/组合）都在后台进程执行，页面不会被阻塞。

### 命令行主流程

```powershell
cd custom_backtester

# ① 构建主缓存（需源 CSV 就位，路径见 configs/platform.yaml 的 source_csv）
python -m custom_bt.cli prepare-master --config configs/platform.yaml

# ② 创建股票池
python -m custom_bt.cli create-pool --config configs/pools/liquid_500.yaml

# ③ PPO 生成因子
python -m custom_bt.cli generate-factors --pool <pool_id> --config configs/factor_generation.yaml

# ④ 合格因子批量回测
python -m custom_bt.cli backtest-factors --pool <pool_id> --factor-run <run_id> --config configs/default.yaml

# ⑤ 因子组合
python -m custom_bt.cli compose-factors --pool <pool_id> --factor-run <run_id> --config configs/default.yaml --sweep-sizes 10,20,30
```

### 只用算子库 `quantops`

不跑回测、只想用那 80 个算子时（任意 Python 项目都行，只依赖 numpy + pandas）：

```powershell
py -3 -m pip install -e quantops            # 可选：装成真包。不装时 custom_backtester 会自动把库目录加进 sys.path

py -3 -m quantops list --category time_series
py -3 -c "import quantops as qo; print(qo.describe('ts_mean'))"
```

用法（函数式 / `series.qo.xxx()` 方法式 / 表达式字符串三选一）见 [quantops/README.md](quantops/README.md)。

### 独立 PPO 生成器（服务器守护，自动重启）

```powershell
# 在项目根目录（包含 single_factor 的那一层）
python -m single_factor.cli run --config single_factor/runtime.json
# 或守护脚本（断线自动重启，复用 run_state.json 与 checkpoint）
powershell -ExecutionPolicy Bypass -File .\single_factor\run_server.ps1
```

## CLI 命令

| 命令 | 作用 |
|---|---|
| `prepare-master` | 构建主缓存（读源 CSV） |
| `create-pool` | 创建股票池 |
| `generate-factors` | PPO 因子生成 |
| `backtest-factors` | 合格因子批量回测 |
| `compose-factors` | 因子组合 |
| `backtest` | 手动表达式回测 |
| `fields` / `operators` / `runs` / `stock-list` | 查看字段 / 算子 / 结果 / 股票列表 |
| `prepare` / `update` | 旧式缓存导入与增量更新 |
| `migrate-results` | 历史结果目录迁移 |
| `ai-research` | LLM 量化研究 agent（需 DeepSeek API Key） |

## 配置说明

| 配置文件 | 作用 |
|---|---|
| `configs/platform.yaml` | 主数据源 `source_csv`、`master_store`、`factor_fields`、分隔符、chunksize |
| `configs/pools/liquid_500.yaml` | 股票池名称、筛选窗口、top_n、覆盖率、上市天数、停牌过滤 |
| `configs/factor_generation.yaml` | PPO 可用字段、train/valid/test split、target_horizon、质量阈值、生成预算 |
| `configs/default.yaml` | 回测 BacktestConfig（区间、TopK、成本、滑点、单票权重、涨跌停过滤） |

> **注意**：`backtest-factors` / `compose-factors` 会从 `--config` 读取 `master_store`、`pools_root`、`backtest`。若 `default.yaml` 缺少前两个键会报 `KeyError`，需补上：
>
> ```yaml
> master_store: "../data_cache/master"
> pools_root: "../data_cache/pools"
> ```

## 数据说明

- **源数据**：约 20GB 的日频面板 CSV（tab 分隔，`.csv` 后缀）。必需列 `code/timestamps/open/close/high/low/vol/amount`，字段说明见 [v_stock_daily_full_字段说明.md](v_stock_daily_full_字段说明.md)（共 91 字段）。
- **主缓存 `data_cache/master`**：按股票拆分的 Parquet + `meta.json`（含 `source_signature`），**已纳入 Git**（约 811MB，5432 只股票）。
- **不入库的生成产物**（见 `.gitignore`）：`stock_daily`（旧缓存）、`pools`（股票池）、`factor_runtime`（PPO 运行时缓存）、`factor_runs`（历史因子）、`outputs`（回测/组合结果）、`single_factor` 的 `data/cache/run`。
- **敏感配置**：`.env.local`、`config.local.yaml` 不入库，模板见 `.env.example` / `config.example.yaml`。

### 身份锁（source_signature / pool_id）

`source_signature` 由源 CSV 的路径、大小、mtime、字段列表、分隔符哈希得到；`pool_id` 由名称 + manifest（含签名）哈希得到。因此：

- 换路径/换机器重建主缓存后，`pool_id` 会改变，旧 `factor_runs` 与新池子不匹配，需重新 `create-pool` + `generate-factors`；
- 迁移时若 master / pools / factor_runs 一起拷贝且签名一致，则无需重建，可直接回测 / 组合。

## 已知注意点

- "数据字段"页签默认显示旧缓存 `stock_daily` 的 91 个全量字段；而因子生成/回测实际使用 master 的约 40 个精选字段（`platform.yaml` 的 `factor_fields`），页签里看到的字段未必都能用于因子表达式。
- 网页版路径由侧边栏配置、直接传参给后台任务；命令行版路径从 `--config` 读取，两者取路径方式不同。

## 附录：environment.yml

```yaml
name: alphagen
channels:
  - conda-forge
  - defaults
dependencies:
  - python=3.11
  - pip
  - pip:
      - numpy
      - pandas
      - pyarrow>=12.0
      - pyyaml
      - matplotlib
      - streamlit
      - plotly
      - certifi
      - gymnasium>=0.28
      - stable-baselines3>=2.0
      - sb3-contrib>=2.0
      - torch
      - pytest>=7.0
```
