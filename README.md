# 生成因子＋回测系统

独立的股票**因子生成与回测平台**（不依赖 Qlib）。系统从原始日频数据出发，构建可复用的股票级缓存，通过 PPO 自动搜索可解释的因子表达式，再用统一的 TopK 回测引擎验证因子的交易表现，最后通过 mutual IC 去重与权重优化合成组合因子。

## 核心流程

```
原始 CSV ──► 主缓存(master) ──► 股票池(pool) ──► PPO 因子生成
                                                        │
          结果沉淀 ◄── 因子组合 ◄── 合格因子批量回测 ◄──┘
```

## 目录结构

| 目录 | 说明 |
|---|---|
| `custom_backtester/` | 主平台：数据缓存、股票池、表达式系统、TopK 回测引擎、因子生成/回测/组合、Streamlit 工作台、AI 研究 agent |
| `single_factor/` | 独立 PPO 因子生成器（内置 AlphaGen 原语，可单独部署，自带守护脚本） |
| `research_pipeline/` | 独立研究流水线（因子分类、选股、评估、导出） |
| `docs/` | 设计文档 |
| `提示词合集/` | LLM 研究 agent 的提示词模板 |

详细架构见 [docs/生成因子与回测系统整体逻辑说明书.docx](docs/生成因子与回测系统整体逻辑说明书.docx)。

## 环境要求

- Python 3.11（或 3.8）
- conda 环境 `alphagen`

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

## 快速开始

### 网页工作台

```powershell
cd custom_backtester
python app\run_streamlit.py
```

浏览器打开 http://localhost:8501 ，页签覆盖：平台任务、回测、数据字段、股票列表、股票池、因子生成、因子回测、因子组合、操作符、后台任务、已保存结果。

### 命令行主流程

```powershell
cd custom_backtester

# ① 构建主缓存（需 20GB 源 CSV 就位，路径见 configs/platform.yaml 的 source_csv）
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

## CLI 命令

| 命令 | 作用 |
|---|---|
| `prepare-master` | 构建主缓存 |
| `create-pool` | 创建股票池 |
| `generate-factors` | PPO 因子生成 |
| `backtest-factors` | 合格因子批量回测 |
| `compose-factors` | 因子组合 |
| `backtest` | 手动表达式回测 |
| `fields` / `operators` / `runs` | 查看字段 / 算子 / 结果 |
| `prepare` / `update` | 旧式缓存导入与增量更新 |
| `ai-research` | LLM 量化研究 agent（需 DeepSeek API Key） |

## 配置说明

| 配置文件 | 作用 |
|---|---|
| `configs/platform.yaml` | 主数据源、master_store、因子字段 |
| `configs/pools/liquid_500.yaml` | 股票池筛选规则 |
| `configs/factor_generation.yaml` | PPO 字段、split、质量阈值 |
| `configs/default.yaml` | 回测 BacktestConfig（TopK、成本、区间等） |

## 数据说明

- 原始数据是约 20GB 的日频面板 CSV，字段说明见 [v_stock_daily_full_字段说明.md](v_stock_daily_full_字段说明.md)。
- 主缓存、股票池、因子运行、回测结果均为**生成产物，不入库**（见 `.gitignore`）。
- 敏感配置 `.env.local`、`config.local.yaml` 不入库，模板见 `.env.example` / `config.example.yaml`。
