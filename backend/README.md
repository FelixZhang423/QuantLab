# QuantLab 后端

公司 ClickHouse 是行情、股票维度、财务、估值及衍生字段的唯一生产来源。生成、回测和组合读取不可变 Parquet 快照；本地训练缓存由快照派生，不再导入原始 CSV 或维护本地主缓存。

## 启动

```powershell
python -m pip install -r requirements.txt
python -m api
```

首次取数需要公司网络与 ClickHouse 配置，参考 `configs/clickhouse.env.example`。凭据从环境变量或本地忽略文件加载，不写入 manifest。

## 工作流

```powershell
python -m cli create-pool --config configs/pools/liquid_500.yaml
python -m cli generate-factors --pool <pool_id> --config configs/factor_generation.yaml
python -m cli confirm-factors --factor-run <run_id> --config configs/factor_generation.yaml
python -m cli backtest-factors --pool <pool_id> --factor-run <run_id> --config configs/default.yaml
python -m cli compose-factors --pool <pool_id> --factor-run <run_id> --config configs/default.yaml --weight-method equal
```

默认运行期根是仓库 `var/`，可用 `QL_VAR_ROOT` 覆盖。不可变快照在 `data_cache/snapshots/<snapshot_id>/`，包含 `panel.parquet`、`manifest.json`、`checksums.json`。相同请求复用快照，刷新建立新 ID；已发布面板不覆盖。任务和结果清单记录快照引用，派生 memmap 按快照版本隔离。

财务按 InfoPublDate、衍生按披露日期 as-of 合并；估值按交易日合并。缺字段、旧 local 池、不兼容的日期范围须报出明确错误，不能回退本地文件。旧结果继续可查看，重新运行前需在 ClickHouse 上重新建池、生成并绑定快照。旧磁盘文件不会自动删除。

详见 [仓库说明](../README.md) 与 [Web API](docs/web_api.md)。

## 7. 表达式例子

20 日动量：

```text
close / delay(close, 20) - 1
```

换手率反转：

```text
-rank(TurnoverRate)
```

均线偏离：

```text
close / ts_mean(close, 20) - 1
```

组合表达式可以写在 `configs\default.yaml`：

```yaml
alphas:
  - name: momentum_20
    expr: "close / delay(close, 20) - 1"
    weight: 1.0
  - name: turnover_reversal
    expr: "-rank(TurnoverRate)"
    weight: 0.5
```

## 8. 拓展算子

打开 `quantops/quantops/operators.py` 新增实现，并在 `quantops/quantops/registry.py` 确认 canonical 名称；也可以在任意项目里直接注册：

```python
from quantops import register_operator

def _neg(x):
    return -x

register_operator("neg", _neg, category="custom", description="Negative value.")
```

注册后：

- 命令行 `python -m cli operators` 能看到
- 网页 Operators 页面能看到
- 表达式里可以直接用，例如 `neg(rank(close))`

## 9. 回测规则

第一版规则：

- 多头 TopK
- `T` 日算 alpha
- `T+1` 日开盘成交
- 按 alpha 从高到低选前 `top_k`
- 等权持仓，并受 `max_weight_per_stock` 限制
- 跳过停牌股票
- 可配置是否跳过涨停买入、跌停卖出
- 成本 = 买入费率 / 卖出费率 + 滑点 + 最低手续费

这套逻辑目前不做空、不融资、不用 Qlib。

## MySQL 集中存储（股票池 / 因子 / 回测）

股票池以 MySQL 为主存储：`GET /api/pools` / `GET /api/pools/{pool_id}` 优先读 MySQL，
连不上或未配置时回退本地 `var/data_cache/pools`；建池成功后自动写入 MySQL，重复同步幂等。
删除池用 `DELETE /api/pools/{pool_id}?confirm=true`，会同时清理 MySQL 四张池表与本地池目录。
因子运行与回测结果仍以本地文件（`var/factor_runs`、`var/outputs/saved_backtests`）为准，MySQL 只做集中存档。

连接配置（环境变量优先，其次本地文件）：

```powershell
# 长期配置：复制模板后填写；mysql.local.env 已被 **/*.local.env 忽略
copy configs\mysql.env.example configs\mysql.local.env

# 或当次会话临时指定
$env:QL_MYSQL_HOST = "127.0.0.1"
$env:QL_MYSQL_PORT = "3306"
$env:QL_MYSQL_USER = "quantlab"
$env:QL_MYSQL_PASSWORD = "<密码>"
$env:QL_MYSQL_DATABASE = "QuantLab"
```

安装驱动（已加入 `requirements.txt`）：

```powershell
py -3 -m pip install PyMySQL
```

表结构：

| 分组 | 表 |
| --- | --- |
| 股票池 | `pools`、`pool_codes`、`pool_candidates`、`pool_stats` |
| 因子 | `factor_runs`、`factors` |
| 回测 | `backtests`、`backtest_components`、`backtest_daily`、`backtest_annual`、`backtest_trades`、`backtest_positions` |
| 批量因子回测 | `factor_backtest_runs`（批次汇总，主键 `backtest_id`） |

常用命令（在 `backend` 目录）：

```powershell
py -3 -m repositories.mysql_store schema   # 幂等建表
py -3 -m repositories.mysql_store check    # 连接自检 + 各表行数
py -3 -m cli mysql-sync       # 把现有本地结果补录到 MySQL
```

说明：MySQL 未配置或连不上时，股票池接口自动回退本地文件，建池/回测也不受影响；密码不会进入日志、响应或 manifest。

## Web API（React 前端用）

`frontend/` 下的 React 前端通过 `/api/*` 读取真实数据。HTTP 路由在 `api/routers/`，业务编排在 `services/`，数据访问在 `repositories/`；`api/main.py` 只负责装配 app 和注册路由。
在 `backend` 目录启动：

```powershell
python -m api
```

默认监听 `127.0.0.1:8000`，可用环境变量 `QL_API_HOST` / `QL_API_PORT` 覆盖。
本机若 `python` 是 Windows 商店占位程序（退出码 49），改用 `py -3 -m api`。

日志除了照旧打在控制台，还会同时落盘到 `var/outputs/logs/`（`api_<日期>.log` 应用/错误日志、
`api_access_<日期>.log` 每请求一行），关窗后依然可查。`QL_API_LOG=0` 关闭落盘，
`QL_API_LOG_DIR=D:\logs` 换目录，详见 `docs/web_api.md` §5.1。

**数据总览 / 数据字段 / 股票列表 / 股票池候选查公司 ClickHouse（HTTP 只读，实时）**，需要在公司网络下并配置凭据：
环境变量 `QL_CH_PASSWORD`（以及可选的 `QL_CH_HOST` / `QL_CH_PORT` / `QL_CH_USER`）优先，其次读本地文件
`configs/clickhouse.local.env`（已 gitignore，格式见同目录模板与 `.env.example`，不要提交）。
没配凭据时所有依赖公司库的端点返回 503 并带中文原因，其余端点不受影响。

端点：

- `GET /api/data/master` 实时数据源概况（行数、股票数、日期区间、可用字段数、查询时间）
- `GET /api/data/fields` 实时字段清单（库表结构 + 中文说明 + 能否进回测面板）
- `GET /api/data/stocks` 实时股票清单（全市场逐股聚合 + 简称/行业/上市信息）
- `GET /api/universe/options` 股票池筛选分布（行业/市场/板块/库内原始编码）
- `GET /api/universe/stocks` 股票池候选预览（条件筛选 + 服务端分页；候选不再与本地缓存取交集）
- `GET /api/universe/codes` 当前筛选下全部匹配代码（预览表格跨页全选/反选）
- `POST /api/pools` 按筛选结果建池（可传 `selected_codes` 只建勾选股票；202 + job_id，后台子进程执行；选样统计直接查公司库）
- `GET /api/jobs/{job_id}` 建池任务状态（queued / running / finished / failed）
- `GET /api/operators` 表达式算子（operator_registry + 中文说明/示例）
- `GET /api/pools`、`GET /api/pools/{pool_id}` 股票池清单与明细（含池内代码与筛选来源）
- `DELETE /api/pools/{pool_id}?confirm=true` 删除股票池（同步清理本地目录 + MySQL 记录；因子运行/历史回测不级联删除）
- `GET /api/factor-runs`、`GET /api/factor-runs/{run_id}` 因子运行与合格因子清单（`factor_id` 可直接用于提交）
- `POST /api/factor-generations` 提交 PPO 因子生成（202 + job_id；后台子进程，进度轮询）
- `POST /api/factor-backtests` 提交批量因子回测（可传 `factor_ids` 只回测勾选因子；202 + job_id）
- `GET /api/factor-backtests`、`GET /api/factor-backtests/{backtest_id}` 批次列表与汇总/失败明细（每行带 `run_key`）
- `GET /api/factor-backtests/{backtest_id}/files/{file_name}` 下载批次汇总/失败 CSV
- `POST /api/factor-compositions` 提交因子组合（等权 1/N、多规模回测；202 + job_id）
- `GET /api/factor-compositions`、`GET /api/factor-compositions/{composition_id}` 组合历史与指定规模指标/权重
- `GET /api/factor-compositions/{composition_id}/screen` 最新一期 TopK 选股清单（次日可买状态 + 单因子贡献）
- `POST /api/manual-backtests` 按股票池 + Alpha 表达式提交手动回测（202 + job_id；从不可变快照读取面板，拒绝旧 local 池）
- `GET /api/results`、`GET /api/results/{run_name}` 已保存回测结果（净值/年度指标/文件清单；手动回测 `run_key = manual/<job_id>/<run_name>`）
- `GET /api/results/detail?run_key=...`、`GET /api/results/file?run_key=...` 按相对路径打开/下载任意层级结果（嵌套因子结果用这个）
- `GET /api/results/{run_name}/files/{file_name}` 下载旧扁平结果文件（按 manifest 白名单）

边界：股票池候选与建池选样直接读 ClickHouse，研究面板通过不可变快照读取。逻辑来源签名标识公司库，快照 ID 和校验和固定实际数据版本。旧本地缓存池只可查看历史结果，不能继续执行。行业取 `dim.stock_main_info_fd.FirstIndustryName`，市场/板块由代码前缀推导。

前端开发时由 vite 把 `/api` 代理到该地址（见 `frontend/vite.config.ts`，可用 `QL_API_TARGET` 覆盖）。
建池、因子生成、批量因子回测、因子组合与手动回测的 POST 均已接入；结果详情页只读真实结果（`/api/results` + `/api/results/detail`，
兼容手动 `config.backtest` 与因子扁平 `config`）。因子组合固定为等权 1/N；结果目录包含
`composition_manifest.json`、各规模 `factor_weights.json` 与 `latest_screen.json/.csv`。

已接入的真实数据清单（各端点的实测值）与前后端技术栈详见 [docs/web_api.md](docs/web_api.md)。


调仓频率、因子方向、拆分费用和页面真实指标口径见 [因子回测说明](docs/factor_backtest.md)。


两阶段门槛、测试确认与切分隔离见 [因子确认说明](docs/factor_confirmation.md)。

## 本地账号登录

使用现有 MySQL 配置。首次在 backend 目录用部署账号创建应用用户，命令会创建两张认证表并交互读取密码。部署账号需要建表权限，运行 API 的账号需要认证表的读写权限。

```powershell
python -m cli.create_user admin --name "管理员" --role admin
python -m cli.create_user researcher --name "研究员"
```

本地通过 HTTP 和 Vite 代理开发时，启动 API 前设置 `$env:QL_AUTH_SECURE_COOKIE="0"`。生产环境使用 HTTPS，由同一站点反向代理 `/api`，保留默认的 Secure Cookie。修改数据的请求须带 `X-QuantLab-Request: 1`。登录尝试按连接来源 IP 在单个 API 进程内限流。

当前研究数据和任务由已登录用户共享。管理员可在「用户与权限」创建、启用、停用研究员和重置密码，并在「审计日志」查看账号事件。首次认证操作会创建审计表 ql_auth_audit，因此升级后运行账号需要该表的建表和读写权限。改密、重置密码和停用账号会撤销受影响账号的旧会话。
