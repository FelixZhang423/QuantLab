# 执行进度

## 2026-08-11

- 已完成重复主缓存任务保护的实现。
- 验证：60 passed，77 subtests passed；compileall 通过。
- 已停止旧导入进程并删除旧任务记录和残留 staging。
- 当前开始新的全量导入。
- 首次启动因 PowerShell 内联命令将中文源路径编码为 `????` 而失败，未读取数据；改用 ASCII 通配路径自动定位原始 CSV。
- 主缓存完成：job `20260811_012816_50dafc3b`。
- 股票池完成：`liquid_500_864dc25f`，500 只股票。
- 因子生成完成：`liquid_500_864dc25f_af3e199fe8`，54 个合格因子。
- 因子批量回测完成：54 个完成，0 个失败。
- 最终验证：60 passed，77 subtests passed；compileall 通过。
- 组合回测完成：Top10、Top20、Top30、Top40、Top50、Top54 共 6 组，均已生成独立结果和总汇总表。

## 2026-08-11 结果中心与操作符统一收尾

- 因子回测新输出路径为 `outputs/saved_backtests/factor/<pool_id>/<factor_run_id>/`。
- 结果中心现递归读取 `manual`、`factor`、`composite` 三类 manifest，并展示规范表达式、PPO IC/Rank IC/ICIR/Coverage/Score 及回测指标。
- 真实结果迁移刷新：54 个因子幂等跳过，6 个组合更新，失败 0 个。
- 组合组件权重文件已统一为规范操作符。
- 8 个旧手动结果目录已移动到 `outputs/_legacy_archive_20260811/`（可恢复）。

## 2026-08-21 AI Research Agent 可用化

- 已确认 foundation 计划全部完成；当前缺口是 tool plan 仍停留在记录层，没有真正连接本地因子生成/回测/组合工具。
- DeepSeek API key 已保存到本地 `.env.local`，后续运行使用 DeepSeek provider；不在日志或回复中输出密钥。
- 当前实现方向：先 TDD 补 tool executor，再接入 runner/CLI，默认 dry-run 创建耗时 job，显式执行参数才同步运行重任务。
- 已完成 `custom_bt.ai_research.tool_executor.AIToolExecutor`，支持白名单工具：context、表达式校验、记忆写入、候选回测 job、PPO 生成 job、组合 job、保存结果读取。
- 已让本地表达式 `rank(ts_mean(volume,20))` 可进入 `backtest_accepted_factors` 链路。
- 验证：`tests/test_ai_research_agent.py` 25 passed；相关回归 60 passed、1 个 torch/pynvml FutureWarning；`python -m compileall -q custom_bt app` 通过。
- DeepSeek smoke：session `smoke_deepseek_20260821_tools` 生成 2 个候选，2 个校验通过，创建 2 个回测 job；其中 job `20260821_012823_d578e522` 已真实运行完成，1 completed、0 failed。

## 2026-08-21 AI Research Flow 文档整理

- 已开始按当前实现整理 AI 研究全链路说明。
- 已确认核心入口包括 `custom_bt.cli ai-research`、`custom_bt.ai_research.cli run` 和 `AIResearchRunner.run_research_session`。
- 已确认当前链路是 DeepSeek 模型驱动，默认不执行本地工具；传入 `--execute-tools` 才执行工具计划，传入 `--execute-long-jobs` 才同步运行耗时平台 job。
- 已新增说明文档 `docs/ai_research_flow.md`，覆盖 17 个主章节：前置条件、配置、DeepSeek 调用、context snapshot、Research Spec、候选表达式、本地校验、tool plan、工具执行、产物目录、真实 smoke 示例、命令和排障。
- 收尾验证：`python -m pytest tests/test_ai_research_agent.py -q` 25 passed；`python -m compileall -q custom_bt app` 通过；`python -m custom_bt.cli ai-research --help` 通过；文档未匹配真实 key 形态或 TODO/TBD/FIXME。

## 2026-08-21 DeepSeek SSL 证书问题修复

- 用户在 `alphagen` 环境真实调用 DeepSeek 时遇到 `ssl.SSLError: [ASN1: NOT_ENOUGH_DATA] not enough data`。
- 已复现根因：`alphagen` 环境单独执行 `ssl.create_default_context()` 会在读取 Windows 证书库时失败；使用 `certifi.where()` 创建 context 可以成功。
- 已修复 `custom_bt.ai_research.llm_client.DeepSeekChatClient`：默认 HTTPS 调用优先使用显式 CA bundle 或 certifi CA bundle，避免直接依赖 Windows 证书库。
- 已新增可选环境变量 `DEEPSEEK_CA_BUNDLE`，并更新 `.env.example` 和 `docs/ai_research_flow.md` 排障说明。
- 验证：新增回归测试先红后绿；`python -m pytest tests/test_ai_research_agent.py -q` 26 passed；`F:\anaconda3\envs\alphagen\python.exe` 可创建 `create_https_context()` 和 DeepSeek client；`python -m compileall -q custom_bt app` 通过；CLI help 通过。

## 2026-10-10 React 原型接入只读 API（第一步）

- 新增 `api/`（FastAPI 只读层）：`GET /api/health`、`/api/data/master`、`/api/data/fields`、`/api/data/stocks`、`/api/operators`、`/api/pools`（含 `/{pool_id}`）、`/api/results`（含 `/{run_name}`、`/files/{name}`），全部复用 custom_bt 现有函数（list_store_fields / list_store_stocks / enrich_fields / enrich_operators / list_runs），不改动既有业务代码。
- 响应统一做 NaN / Infinity → null 清洗：`outputs/saved_backtests/web_run/summary.json` 里含 NaN，Starlette 序列化 `allow_nan=False` 会直接 500。
- 股票列表优先读 `data_cache/master/stock_list.csv` 缓存，避免每次逐股票扫描 5432 个 parquet。
- 路径安全：pool_id / run_name / 文件名走正则白名单 + 子路径校验；结果文件下载只允许 manifest.files 内的文件（越权与穿越请求实测 404）。
- 启动方式 `py -3 -m api`（本机 `python` 是 Windows 商店占位 stub，退出码 49；README 已注明）。
- 原型侧：新增 `src/api/client.ts`（类型定义 + useApiData），vite 增加 `/api` → `http://127.0.0.1:8000` 代理；数据总览 / 数据字段 / 股票列表 / 操作符 / 股票池 / 结果详情 6 个页面改为真实数据；结果详情页新增「演示任务 / 真实结果」数据源切换（真实文件走 API 下载）；净值图坐标轴改为按数据自适应（真实回测净值可跌破原固定下界 0.9）。
- 验证：`tsc --noEmit` 通过；7 个端点 curl 200；`/api/results/web_run` 严格 JSON 解析通过（1202 个净值点、6 年年度指标、年化=null）；股票整包 5432 只 / 988KB / 60ms；vite 8443 代理 `/api/data/master` 返回真实 meta。
- 待办（第二步）：POST `/api/pools`、POST `/api/backtest`、POST `/api/jobs` + 后台 worker（create_platform_job / run_platform_job 与 Streamlit 共用 outputs/jobs），任务中心改读 jobs/*/status.json；用户与审计页暂留 mock。

## 2026-10-10 展示端点切换 ClickHouse 实时数据（不用缓存文件）

- 需求：数据总览 / 数据字段 / 股票列表三个页面不再读本地 `data_cache/master` 快照（停在 2026-06-16），直接查公司 ClickHouse。
- 新增 `api/live_db.py`（纯 stdlib `urllib.request`，零新增依赖）：只读 HTTP 客户端 + 4 个 key 级 TTL 缓存（`master_stats` 60s / `field_catalog` 300s / `stock_rows` 60s / `dim_names` 300s），key 级锁 + 双检 + single-flight（React StrictMode 双请求只打一次库），启动时后台线程预热。
- 凭据：`QL_CH_PASSWORD` 等 `QL_CH_*` 环境变量优先，其次 `configs/clickhouse.local.env`（按 `utf-8-sig` 读，兼容记事本 BOM）；**密码不写入任何文档、模板或提交文件**，实现与测试全程只用环境变量。仓库根 `.gitignore` 新增 `**/*.local.env`（原有 `.env*` 规则不匹配该文件名，已用 `git check-ignore -v` 验证命中）。
- 三条 SQL 全是模块常量（请求参数绝不拼进 SQL），并加语句前缀白名单（SELECT/WITH/DESCRIBE/SHOW/EXPLAIN）+ 写类关键字黑名单双保险；查询 opener 显式 `ProxyHandler({})` 禁系统代理，连接类失败重试 1 次、超时不重试。
- 失败语义：未配密码 / 认证失败 / 网络不可达 → 503，库端报错 → 502，均为中文 `detail` 且经 `_redact` 脱敏（单测断言错误消息不含密码）；不做静默回退缓存。
- `api/main.py` 三个端点改调 live_db：`n_fields` 与字段页共用同一份 `live_field_catalog()`（66 个行情列除去 `code`/`timestamps` + 4 个 dim 字段 = 70），字段页新增「面板可用 / 仅数据库」标记（与本地 `meta.json` 求交），股票页新增名称列（`dim.stock_main_info_fd.ChiNameAbbr`）；描述优先级为字段说明 md → 库内列注释（70 个里 49 个有）→「暂无字段说明」。总览页保留一行本地缓存窗口小字，说明股票池/回测仍走快照口径。
- 前端：`client.ts` 的 `apiGet` 现在解析非 2xx 响应体里的 `detail`（此前只显示 HTTP 503，后端中文原因到不了 UI）；`DataPages.tsx` 三页文案与标签全部改为实时口径，`LoadGate` 增加 `hint`（说明实时端点需公司网络与 `QL_CH_PASSWORD`，操作符/股票池/回测不依赖数据库）。
- 修复的坑：`SELECT toString(position) AS position … ORDER BY position` 被解析成按字符串别名排序（1, 10, 11, …, 2, 20）→ 列序 SQL 不返回 position，只用它排序；JSONEachRow 把大整数输出成字符串、Decimal 会丢精度 → 数值列全部 SQL 侧 `toString()` + Python `Decimal` 转换。
- 验证（V2–V10）：直连库 SQL 与 API 响应逐字一致——全表 17,368,843 行 / 5,589 只 / 1990-12-19 ~ 2026-10-09；`000001` 8,824 行 1991-04-03 ~ 2026-10-09 最新收 11.59 / 量 107,810,561 / 额 1,259,717,108.28；字段集合与 `system.columns` + dim 双向 diff 为空（`vwap` 不在、4 个 dim 字段在，字段顺序与库一致）；历史点 `000001@2026-06-16 = 10.94 / 94,270,804 / 1,034,554,249.38` 与 parquet 缓存一致；缓存 TTL 命中/失效、单飞、代理绕过、错误脱敏、路径安全均通过。冷查询耗时 2.87s（总览）/ 0.11s（字段）/ 3.63s（全市场逐股）。
- 新增 `tests/test_live_db.py`（18 个用例，假 opener 注入，无网络）与 `pytest.ini`（`testpaths = tests`，绕开驱动器根目录残留 `D:\pyproject.toml` 对 pytest rootdir 的劫持）。
- 已知：全量测试套件有 1 个既有失败 `tests/test_streamlit_app.py::test_saved_runs_table_keeps_topk_arrow_compatible`（`'str' != 'object'`，pandas 3.0 dtype 变化，与本次改动无关，未在本次触碰 custom_bt/app）。
- 文档：`docs/web_api.md`（架构、实测值、新增 2.7 实时数据源、技术栈、启动、坑、验证全节改写）、`README.md`「Web API」段、`原型/README.md` 数据来源说明同步更新。

## 2026-10-14 算子抽成独立库 quantops

- 需求：把 80 个算子 + 表达式引擎从 `custom_bt/expressions.py`（590 行）抽成可复用、可安装的独立 Python 库。**新库是唯一实现，custom_bt 改为转发**（不留两份代码）。
- 新增 `../quantops/`（flat layout）：`pyproject.toml`（name=quantops 0.1.0，deps 只有 numpy>=1.24 + pandas>=2.0，`py -3 -m quantops` CLI 入口）＋ `quantops/` 包 9 个模块 ＋ `tests/` 3 个文件 ＋ `README.md`。
  - `core.py` 私有 Series 助手（~40 个）／`operators.py` 80 个实现 + `OPERATORS` 注册表／`registry.py` 22 个 canonical 定义／`expression.py` AST 白名单 + 求值引擎／`panel.py` 面板互转／`metadata.py` 中文元数据副本／`accessor.py` pandas 访问器 `Series.qo`／`__main__.py` CLI。
  - 公开 API：`evaluate/evaluate_expression`、`list_operators`、`describe`、`categories`、`catalog`、`register_operator`、`ExpressionError`、`OPERATORS`、`to_series/to_frame/prepare_panel/align/available_fields`，外加 80 个算子的扁平导出（`import quantops as qo; qo.ts_mean(s, 20)`）。
- `custom_bt/expressions.py` 590 → 38 行（只转发）、`custom_bt/operator_registry.py` 同样转发（**本地保留 `load_alphagen_operator_classes`**，它指向仓库内 `single_factor/_vendor/alphagen`，是仓库本地耦合）。`custom_bt/docs.py` **未改动**（tests/test_docs.py 锁着）。
- 新增 `custom_bt/_quantops_boot.py`：`find_spec("quantops")` 找不到真包时把 `../quantops` 插到 `sys.path[0]`，所以**不装库也能 `py -3 -m pytest` / `py -3 -m api`**；`pip install -e ../quantops` 之后走真包（`pip show quantops` → 0.1.0）。
- 合并口径保持原样：22 个 canonical 定义里只有 sub/mul/div 不在字面量里，会采用定义文案，其余 19 个保留字面量文案（`OPERATORS["max"].description` 与 `get_operator("max").description` 本就不同）——已在代码里加注释说明「不要当成重复定义顺手清理」。
- **验证（改前改后逐字节对拍）**：一次性 dump 脚本（临时目录，不入库）在改前/改后各跑一遍固定种子面板，输出①算子清单②`list_operators()`③`enrich_operators` 完整 JSON④`available_fields`⑤非法表达式拒绝⑥每个 example 的数值（79/80 条，div 无示例）——**before/after 全部逐字节相同**；后端重启后 `curl /api/operators` JSON 与改前 diff 为空。
- 测试：库自带 **125 passed**（移植的精确数值用例 + 公开接口/面板互转/访问器/依赖守门/「import quantops 不牵连 custom_bt」子进程用例 + 80 个算子的金标准摘要与 12 个代表算子可读切片 + CLI 5 例；金标准另做变异自检——把 ts_mean 换成 ts_sum 立刻红）；后端 **168 passed / 1 既有失败**（`test_streamlit_app.py::test_saved_runs_table_keeps_topk_arrow_compatible`，pandas 3.0 dtype 变化，改前就在，与本轮无关）+ 84 subtests，新增 `tests/test_quantops_metadata_parity.py`（锁 docs.py 与 quantops/metadata.py 的中文元数据一致）与 `tests/test_quantops_boot.py`（mock 掉 find_spec，覆盖「未安装时补 sys.path」这条平时走不到的分支）。
- 坑：仓库根下有个同名目录 `D:\1\QuantLab\quantops`（项目目录，无 `__init__.py`），在**仓库根** cwd 下 `import quantops` 会被 PEP 420 解析成空的命名空间包（`AttributeError: ... has no attribute 'OPERATORS'`），`py -3 -m quantops` 则会先跑起真 `__main__.py` 再在 `from quantops import catalog` 处报 `unknown location`（子模块经 editable finder 找到了、包本体却是空的）。已在 `quantops/quantops/__main__.py` 把这种状态翻译成中文提示（`_import_api()`，先判 `sys.modules['quantops'].__file__ is None`），并写进 `quantops/README.md`；`quantops/tests/test_cli.py` 用临时空目录复现该场景做回归。真实使用路径（`cd custom_backtester` 或任意其它目录）不受影响，`/api`、Streamlit、CLI 全部照常。
- 文档：新增 `quantops/README.md`（三种用法、MultiIndex(date,code) 面板约定、pandas 2/3 兼容、`series.qo` 访问器、分组/时序语义），更新仓库根 `README.md`（子项目关系 + 目录结构 + 「只用算子库」快速开始）、`docs/web_api.md`（§2.4 操作符来源说明 + 启动加可选安装步骤）、`requirements.txt`（注释指向 `py -3 -m pip install -e ../quantops`）。

## 2026-10-15 后端日志落盘（outputs/logs/，不开 tee 也有历史）

- 需求：`py -3 -m api` 的日志只活在当前终端里，窗口一关就没了；希望「不开 tee 也永远有历史日志可查」，顺带把 uvicorn 的访问日志与错误日志分开。
- 新增 `api/logging_setup.py`（不动任何业务代码）：`configure_logging()` 算路径并建目录，`uvicorn_log_config(paths)` 返回「uvicorn 默认配置 + 两个文件 handler」。
  - `outputs/logs/api_<启动日期>.log`：启动信息 / uvicorn 报错 / 应用自己的 `logging.getLogger(...)`，格式 `时间 级别 logger名 消息`（制表符分隔）。
  - `outputs/logs/api_access_<启动日期>.log`：每个请求一行 `时间 客户端地址 请求行 状态码`，与应用日志分开。
  - 开关：`QL_API_LOG=0/false/no/off` 关掉落盘（此时 `uvicorn_log_config(None)` 还回 uvicorn **自带**配置的拷贝，控制台行为与改动前逐字一致）；`QL_API_LOG_DIR` 换目录；默认 `custom_backtester/outputs/logs`。
  - 单文件 10MB 滚动、保留 3 个备份、`delay=True`（没日志不建空文件）、`encoding="utf-8"`。
- `api/__main__.py`：`uvicorn.run(...)` 换成 `uvicorn.Config(..., log_config=...)` + `uvicorn.Server(config).run()`（`uvicorn.run` 不方便传 log_config 之外再补日志）；Config 构造完立刻打两行启动日志，所以启动信息本身也在文件里。
- 根 `.gitignore` **无需改动**：第 32 行 `custom_backtester/outputs/` 已经覆盖 `outputs/logs/`。
- 踩到的坑（都是单测容易漏、真启动才暴露的）：
  1. **访问日志整行被丢弃**：文件 0 字节，stderr 狂刷 `--- Logging error ---` / `KeyError: 'client_addr'`。uvicorn 打访问日志用的是**位置参数** `logger.info('%s - "%s %s HTTP/%s" %d', client_addr, method, path, version, status)`，`client_addr / request_line / status_code` 是 `uvicorn.logging.AccessFormatter` 解析 args 后临时塞进 record 的，**不是 `extra`**。文件 formatter 必须配 `{"()": "uvicorn.logging.AccessFormatter", "use_colors": False}`（文件里不要 ANSI 色）。第一版单测自己塞 `extra=` 掩盖了这个差异 —— 已把用例改成照抄 uvicorn 的原始调用形状，并断言 config 里的 formatter 类名。
  2. **不能 `addHandler`**：`uvicorn.Config.__init__` 会 `dictConfig` 重新配置 `uvicorn / uvicorn.error / uvicorn.access`，对配置里出现的 logger 是**替换** handlers，先 addHandler 再 `uvicorn.run` 会被冲掉 —— 所以必须拿到那份配置改完再传回去。
  3. `dictConfig` 的 `disable_existing_loggers` 默认 **True**，会把启动前已建好的 `api.* / custom_bt.*` logger 静音；配置里显式 `False`。
  4. Windows 控制台代码页不是 UTF-8：启动那两行日志若写中文，终端里是乱码（文件里明明是好的 UTF-8）—— 那两行改为纯 ASCII（单测断言 ASCII-only）；文件里的中文由 UTF-8 encoding 保证（另有用例做中文往返）。
  5. 用 `RotatingFileHandler`（按大小）而不是 `TimedRotatingFileHandler`（按时间）：后者滚动要改名，Windows 上被打开的文件不能改名（PermissionError）。「每天一个文件」由文件名里的日期满足。
  6. **`uvicorn.Config(log_config=None)` ≠ 「用默认配置」**：uvicorn 的 `configure_logging()` 里是 `if self.log_config is not None:`，传 None 就**整个跳过**日志配置 —— uvicorn 的 logger 一个 handler 都没有，启动横幅和访问日志全没了（`QL_API_LOG=0` 真启动时控制台一片空白，只剩 WARNING+ 靠 `logging.lastResort` 漏出来）。关掉落盘时要还回 `uvicorn.config.LOGGING_CONFIG` 的拷贝，单测锁住「不是 None」。
- 测试：新增 `tests/test_api_logging.py`（19 例）：默认路径/日期命名/目录自动创建、`QL_API_LOG` 关闭与「空串算默认开」、`QL_API_LOG_DIR` 与显式参数优先级、`uvicorn_log_config(None)` 返回 uvicorn 默认配置拷贝（**不是 None**）、**不污染 `uvicorn.config.LOGGING_CONFIG`**（deepcopy 断言）、保留 `default/access` formatter 键（uvicorn 会往里写 `use_colors`）、滚动与 UTF-8 参数、路由（访问日志只进访问文件）、`delay=True` 前不建文件、两个文件内容互不串台、时间戳形状、中文 UTF-8 往返、AccessFormatter 形状回归（连 stderr 一起接住才算断言）。用例用快照/还原保护全局 logging 状态，避免污染其余 180+ 用例。
- 验证：`py -3 -m pytest -q` → **187 passed / 1 既有失败**（`test_streamlit_app.py::test_saved_runs_table_keeps_topk_arrow_compatible`，pandas 3.0 dtype，与本次无关）+ 84 subtests（改前 168 passed）。真启动 `QL_API_PORT=8010 py -3 -m api` 打 4 个请求（`/api/health` 200、`/api/operators` 200、`/api/nope` 404、`/api/data/master` 200 实时库 17,384,508 行）：应用日志 7 行、访问日志 4 行，内容与预期逐字一致，控制台输出与改动前一致（依旧全量、无 `Logging error`）。
- 文档：`docs/web_api.md` 新增 §5.1「后端日志落盘」与「已知坑」表里的 AccessFormatter 条目，头部更新时间/相关行同步。

## 2026-10-20 算子类式入口 `OperatorSet`（quantops 第四种用法）

- 需求：写一个类实现这些算子，并封装成库。选择在既有 `quantops` 库里加**类式入口**，而不是另起炉灶复制 80 份实现 —— 库早就是 pip 可安装的，这次只是把入口补齐。
- 新增 `quantops/quantops/opset.py`：`OperatorSet(panel=None)`，可选绑定一张面板。
  - 80 个算子全部是实例方法（按 `OPERATORS` 动态生成，**与函数式同一份实现**）；字段名可直接当参数：`ops.rank(ops.ts_mean("close", 20))`。
  - `ops.eval(expr)` / `ops.to_frame(series)` / `ops.describe(name)` / `ops.categories()` / `ops.list_operators()` / `ops.fields` / `ops.names`。
  - `ops.field("close")` 取字段；`ops.close` 也行；`ops.apply("ts_mean", ...)`、`ops["ts_mean"](...)` 是按名字调用的逃生口。
  - `register_operator()` 之后注册的新算子经 `__getattr__` 现生成方法，`ops.<name>(...)` 直接可用（访问器式做不到这点，只能 `apply`）。
- 关键取舍：**字符串只有恰好是面板字段名时才转 Series**。否则 `bucket(x, "0,1,0.1")` 的区间串、`ts_quantile(x, 20, "gaussian")` 的 driver 会被误当成字段 —— 已用测试锁住这两条与关键字传参。
- 方法的 `__doc__` 是中文说明 + 分类 + 示例（来自 `metadata.py`），`__signature__` 在底层函数签名前补一个 `self`，所以 `help(ops.ts_mean)` 与 IDE 参数提示都可用；`inspect.signature(OperatorSet.ts_mean)` = `(self, x, n)`，绑定后 = `(x, n)`。
- 错误信息带 `difflib` 近邻提示：未知属性给出「不是算子名，也不是面板字段名；相近的算子：…」，未知字段列出可用字段。
- `quantops/__init__.py` 导出 `OperatorSet`（docstring 改为「四种用法」）；依赖守门测试的 stdlib 白名单补了 `difflib` / `inspect`（仍然零第三方依赖）。
- 测试：新增 `quantops/tests/test_opset.py`（23 例）：80 个方法全覆盖、中文文档、签名、与函数式逐值相等、无面板用法、嵌套、变参 `max/min`、`group_mean` 三字段、`bucket` 区间串与 `ts_quantile` driver、字段属性/`dir`、未知属性/字段报错、`eval` 等价与缺面板报错、`apply`/`__getitem__`、动态注册、`to_frame`、元数据、repr。**库自测 148 passed**（125 → 148）。
- 文档：`quantops/README.md` 改为「四种用法」并新增 `### 4. 类式：OperatorSet`；目录树补 `opset.py`，测试说明补 `test_opset.py`。

## 2026-10-20 股票池接入公司数据库真实股票（行业等条件筛选）

- 需求：React「股票池」页的创建表单原是 mock（`setTimeout` + `addTask`），候选池只扫本地 `data_cache/master` 全市场，无法按行业等条件筛选。改为候选来自公司 ClickHouse，支持单级行业 / 市场 / 板块 / 关键词 / 上市天数 / 库内原始编码筛选，并在后台创建真实股票池；已确认口径：目标界面 = React 原型 + 后端 API、行业 = `dim.stock_main_info_fd.Industry` 单级、公司库有但本地缓存没有的股票自动排除并提示。
- 后端数据层（`api/live_db.py`）：
  - `SQL_STOCK_ROWS` 增 `latest_ifsuspend`（仅预览展示，不用于建池过滤）；`SQL_DIM_NAMES` → `SQL_DIM_PROFILES`，带 `Industry / ListedSector / ListedState / ListedDate`（数值/日期统一 `toString` 兜底），缓存 key `dim_profiles`。
  - 新增纯函数 `parse_listed_date` / `exchange_for_code` / `board_for_code` / `filter_universe` / `aggregate_universe`；市场与板块按代码前缀推导（沪/深/北 + 主板/创业板/科创板/北交所），**不使用**本地实测为数据商标识的 `market_code`，也不猜 `ListedSector/ListedState` 的中文含义（只作为原始值高级筛选）。
  - `live_stock_rows` 合并 dim 信息并新增 `industry/sector/listed_state/listed_date/exchange/exchange_label/board/board_label/latest_ifsuspend`；缓存改用 `universe_ttl`（`QL_CH_UNIVERSE_TTL`，默认 **300s**），部署里 `QL_CH_CACHE_TTL=0` 时筛选预览也不会每次重打 3.5s 全市场聚合。
- 建池链路：
  - `custom_bt/pools.py` 的 `create_pool` 末尾追加 `strict_top_n: bool = True`、`provenance: Optional[dict] = None`；`strict_top_n=False` 时 TopN 只作上限（候选不足不再报错）；两者写入 manifest，但不进入 `manifest_base`，**pool_id 与历史口径一致**（单测锁定不同 provenance 得到同一 id）。
  - 新增 `api/job_runner.py`：`spawn_platform_job` 用 `subprocess.Popen([sys.executable, "-m", "custom_bt.cli", "run-platform-job", "--job-dir", ...])` 起后台子进程，日志写 `outputs/jobs/<job_id>/runner.log`，不传任何数据库凭据。
  - `api/main.py`：新增 `GET /api/universe/options`、`GET /api/universe/stocks`（可重复 query + 服务端分页）、`POST /api/pools`（202 + job_id）、`GET /api/jobs/{job_id}`；`_pool_summary` 带出 `provenance`；CORS 允许 POST。
  - 建池前与 `data_cache/master/stocks/*.parquet` 取交集，空匹配/全部不可建池 → 422，缓存未就绪 → 503；池名白名单 `[A-Za-z0-9_.\-一-鿿]+` 且 ≤64 字符防路径穿越；`provenance` 只含来源表/端点/筛选/统计，**不含密码**。
- 前端（`原型/`）：
  - `src/api/client.ts` 新增 `ApiError`（带 status）、`apiPost`、数组感知的 query 构造、`universeOptions/universeStocks/createPool/job`、`useJobPolling`（queued/running 轮询，finished/failed 停止，卸载清理）；`StockInfo`/`PoolInfo` 补行业与 provenance 字段。
  - `PoolsPage` 重写：行业多选（带计数）、市场多选、关键词、高级折叠（板块 + 库内 ListedSector/ListedState 原始值）、300ms 防抖预览、匹配/可建池/自动排除统计与排除示例、仅显示本地可建池开关、服务端分页、真实 POST + 任务状态条 + 完成后自动刷新列表、失败中文原因；抽屉展示筛选来源与匹配/建池/排除数。数据库不可用时表单禁用、已有池列表不受影响。
  - `DataPages.tsx` 的 `LIVE_HINT` 改为：候选与行业筛选依赖公司库，建池后的股票池数据与回测仍读本地主缓存。
- 测试：新增 15 个后端用例（`tests/test_live_db.py` 的代码分类、上市日期、筛选/聚合；`tests/test_pools.py` 的 `strict_top_n` 与 provenance 不改 pool_id；新增 `tests/test_api_routes.py` 10 例，覆盖 options/预览/分页/排除示例/POST payload/422/503/任务状态/路径穿越/job_runner 命令行），并扩展了 `live_stock_rows` 的 dim 合并断言。`py -3 -m pytest -q tests/test_live_db.py tests/test_pools.py tests/test_api_routes.py` → **39 passed**；全量 → **202 passed / 1 failed**，唯一失败是既有 `tests/test_streamlit_app.py::test_saved_runs_table_keeps_topk_arrow_compatible`（pandas 3.0 dtype，改前就在）；中途一次 `test_factor_composition.py` 用例单跑通过、全量重跑未复现，属既有测试顺序敏感。
- 前端验证：`pnpm exec tsc --noEmit` 通过；`pnpm build` 通过（Vite 8，产物在 `dist/`）。
- 离线行为实测（临时移走 gitignored 的 `configs/clickhouse.local.env`，测完恢复；未读取密码）：`/api/health` 200、`/api/pools` 200（已有池正常）、`/api/universe/options` / `/api/universe/stocks` / `POST /api/pools` 均 **503 + 未配置密码中文原因**。
- 待公司网验证（本机网络不可达，SQL 按文档字段设计）：第一步 `DESCRIBE dim.stock_main_info_fd` 核对 `Industry / ListedSector / ListedState / ListedDate`；再对拍行业分布、行业筛选数量、建池任务 finished、manifest `provenance` 与 `codes.txt` 全部存在于本地缓存，并用新池跑一次现有回测链路。若列名不同只改 `SQL_DIM_PROFILES` 与对应测试。
- 文档：`docs/web_api.md`（架构改为 GET+POST、新增 §2.8 候选与建池、缓存 key/TTL、已知坑、Step 6 对拍）、`README.md`「Web API」段、`原型/README.md`、`progress.md` 本条。密码只存在于环境变量 / gitignored 本地文件，未写入任何文档、manifest、响应或日志。

## 2026-10-21 公司库连通后的行业口径核对（股票池）

- 启动项目后公司库已可达：`/api/universe/options` 返回 200，全库 **5591** 只、本地可建池 **5432**、自动排除 **159**。
- `DESCRIBE dim.stock_main_info_fd` 核对列名/类型：`FirstIndustryCode/Name` ~ `FourthIndustryCode/Name` 均存在。**`Industry` 是细分行业编码**（实测 337 个取值，如 `60103483`），不是单级行业，直接用它会让下拉框显示数字编码。
- 修正 `SQL_DIM_PROFILES`：`industry` 改取 `FirstIndustryName`（申万一级，实测 31 类，如「机械设备」「银行」），新增 `industry_code` 保留 `FirstIndustryCode`；`live_stock_rows` 同步带出。`Industry` 列不再使用。243 只 `400xxx` 老三板/退市股一级行业为空，前端显示「未分类」，计入 `missing.industry`。
- 实测分布：机械设备 540 / 电子 496 / 医药生物 481 / 基础化工 411 / 电力设备 375 / 计算机 334 / 汽车 290 …；`missing.industry = 363`（含 243 只无一级行业 + 120 只 dim 无记录/未覆盖）。
- 行业筛选：`GET /api/universe/stocks?industries=银行&master_only=true&limit=5` → `matched_total=42`、`creatable=42`、`excluded=0`；预览返回工商银行/农业银行/招商银行等，行业与上市日期正确。
- 端到端建池：`POST /api/pools` 创建 `smoke_bank_20261021`（银行、TopN=5、2025-01-01~2025-06-30、`overwrite=false`）→ job `20261021_091600_f9fe95d0` 在 2 秒内 `finished`；`pool_id=smoke_bank_20261021_0c847f82`，5 只代码（600036 / 601398 / 601288 / 601166 / 000001）全部存在于 `data_cache/master/stocks`；manifest 含 `strict_top_n=false` 与 `provenance`（来源表/筛选/as_of/匹配与可建池统计），无任何密码字段。
- 测试：`tests/test_live_db.py tests/test_api_routes.py tests/test_pools.py` → **40 passed**；全量 → **202 passed / 2 failed**：既有 `test_streamlit_app.py::test_saved_runs_table_keeps_topk_arrow_compatible`（pandas 3.0 dtype）与 `test_factor_composition.py` 的顺序敏感用例（单跑通过）。前端 `pnpm exec tsc --noEmit` 通过。
- 文档：`docs/web_api.md` §2.8/§7/Step 6、`README.md` 的行业口径改为 `FirstIndustryName`；前端 `UniverseStock` 增加 `industry_code` 类型。

## 2026-10-21 股票池预览支持全选 / 反选 / 部分勾选

- 需求：右侧候选预览表格支持全选、反选、部分勾选，并让勾选结果真正决定建池范围。
- 后端：
  - 新增 `GET /api/universe/codes`（参数同 `/api/universe/stocks`，默认 `master_only=true`），只返回当前筛选下全部可建池代码，供跨页全选/反选；响应含 `total / matched_total / n_creatable / master_ready / as_of / cached / queried_at`。
  - `PoolCreateRequest` 新增 `selected_codes: Optional[List[str]]`；省略 = 全部可建池候选，列表 = 只从勾选代码建池，显式空列表 → 422（避免静默退化成全选）。不在当前筛选/本地缓存的代码忽略并写 `warnings`，全部无效 → 422。
  - `provenance` / `request_summary` 增加 `selection_mode`（`all` / `manual`）与 `selected_total`；`payload.codes` 改为勾选后的可建池集合；TopN 警告文案改为「本次候选 N 只，少于 TopN」。
  - 手动勾选仍只与本地 `data_cache/master` 取交集；公司库依然只读，不新增任何写操作。
- 前端：
  - `PoolsPage` 增加跨页选择状态：筛选变化后拉取 `/api/universe/codes` 并默认全选；工具栏「全选 / 反选 / 清空」作用于全部可建池代码；显示「已选 N / 可建池 M」；本页部分勾选时显示 Tag，表头 checkbox 由 antd 自动呈半选态。
  - 表格增加 `rowSelection`（`preserveSelectedRowKeys` 跨页保留；`creatable=false` 的行禁用勾选），清空后建池按钮禁用；提交时全选省略 `selected_codes`，部分勾选只提交勾中代码。
  - 已有池抽屉的「匹配 / 可建池 / 排除」后追加「手动勾选 N 只 / 按全部可建池候选」；TopN 增加「作为上限」说明。
- 测试：`tests/test_api_routes.py` 新增 codes 端点、手动勾选 payload/告警/422 用例；`tests/test_api_routes.py tests/test_live_db.py tests/test_pools.py` → **43 passed**；`pnpm exec tsc --noEmit` 通过。
- 文档：`docs/web_api.md` 端点表、§2.8 勾选语义与 `selected_codes`；`README.md` 端点列表。

## 2026-10-25 MySQL 集中存档（股票池 / 因子 / 回测）

- 需求：把公司库筛选出的股票池、因子运行与回测结果集中存储到 MySQL `QuantLab` 库。
- 新增 `custom_bt/mysql_store.py`：PyMySQL 连接、幂等建表、`persist_pool` / `persist_factor_run` / `persist_backtest` / `sync_all` / `check_connection`；未配置或连不上只记 warning，不阻断本地流程。
- 新增 13 张表：`pools`、`pool_codes`、`pool_candidates`、`pool_stats`、`factor_runs`、`factors`、`backtests`、`backtest_components`、`backtest_daily`、`backtest_annual`、`backtest_trades`、`backtest_positions`、`ql_schema_meta`。
- 自动同步点：`create_pool` 写完 manifest、`run_factor_generation` 写完 `factor_run.json`、`save_result` 写完回测目录；父表 upsert、子表先删后插，重复同步幂等。
- 配置：环境变量 `QL_MYSQL_*` 优先，其次 gitignored 的 `configs/mysql.local.env`；模板 `configs/mysql.env.example`；`requirements.txt` 增加 `PyMySQL`。
- 补录结果：5 个股票池（923 条成分、2947 条候选、923 条选样统计）、0 个因子运行（本地暂无）、1 个回测（1202 条日度、6 条年度、12503 条交易、34272 条持仓），错误 0；重复同步后行数不变。
- 测试：新增 `tests/test_mysql_store.py`（9 个用例）与 `tests/conftest.py`（测试默认 `QL_MYSQL_ENABLED=0`，避免污染真实库）；全量 **215 passed / 1 failed**，失败仍是既有 `test_streamlit_app.py` pandas 3.0 dtype 用例。
- 修正回测主键：`backtests.run_name` 改为非唯一展示列，新增 `run_key` 主键（结果相对路径，如 `factor/<pool_id>/<run_id>/<factor_id>`），子表同步改用 `run_key`；`save_result` 写入 manifest，因子/组合回测显式带上池与运行前缀，`mysql-sync` 对旧 manifest 也能按输出根目录推导。避免同一因子表达式在不同股票池/因子运行下互相覆盖。
- 表结构版本升到 v2：检测到 v1（`run_name` 主键）时自动重建回测表并提示补录，本地文件不受影响。升级后重跑 `mysql-sync`：1 个回测、1202 条日度、12503 条交易、34272 条持仓全部恢复，`run_key=web_run`。
- 新增 2 个主键消歧用例，`test_mysql_store.py` 11 passed、`test_results.py + test_factor_composition.py + test_mysql_store.py` 29 passed；全量 **217 passed / 1 failed**（仍是上述 Streamlit dtype 用例）。
- 文档：`README.md` 新增「MySQL 集中存储」；`docs/web_api.md` §5.2（`run_key` 口径与 v1→v2 升级说明）。

## 2026-10-25 因子批量回测接入 Web（真实运行 / 进度 / 版本化结果）

- 需求：React「因子回测」页原来提交的是 mock 任务，结果也只读 mock 汇总；改为选择真实因子运行、提交真实后台回测、轮询进度并展示批次结果。
- 后端（`api/main.py`）：
  - 新增 `GET /api/factor-runs?pool_id=` 与 `GET /api/factor-runs/{run_id}`：扫描 `factor_runs/`（`QL_FACTOR_RUNS_ROOT` 可覆盖），返回运行摘要与合格因子；`factor_id` 与回测引擎共用 `factor_id()`，页面勾选 ID 可直接提交。
  - 新增 `POST /api/factor-backtests`（202）：校验参数区间、运行/池/master 数据签名、非空合格因子与选中 ID，日期缺省取 master 区间，越界给 warnings；payload 只含服务端白名单路径，复用 `create_platform_job` / `spawn_platform_job`，spawn 失败把任务标 failed。
  - 新增 `GET /api/factor-backtests`（批次列表）、`GET /api/factor-backtests/{backtest_id}`（汇总行 + 失败明细，行内补 `run_key`）、`GET /api/factor-backtests/{backtest_id}/files/{file_name}`（仅汇总/失败/manifest 白名单）。
  - 结果访问改为 `run_key`：新增静态路由 `GET /api/results/detail?run_key=` 与 `GET /api/results/file?run_key=`（声明在 `/api/results/{run_name}` 之前），`_safe_relative` 拒绝绝对路径、`..`、空段；旧扁平结果继续兼容。
  - `list_runs` 对没有显式 `run_key` 的 manifest 按相对路径补全；`_result_summary` / `_result_detail_payload` 带出 `run_key / factor_run_id / backtest_id`。
- 回测引擎：
  - `backtest_accepted_factors` 新增 `backtest_id / factor_ids / progress_callback`；输出目录为 `factor/<pool>/<run>/<backtest_id>/<factor_id>`，`run_key_prefix` 与每行 `run_key` 同步版本化；选择性回测校验未知 ID、空列表报错。
  - 每处理一个因子回调 `stage / accepted_count / selected_count / processed / completed / failed / current_factor_id`，回调异常只记 warning。
  - 批次 manifest 记录 `backtest_id / job_id / run_key_prefix / 计数 / 参数`；结束后尽力同步 MySQL。
  - `platform_jobs` 为 `backtest_factors` 注入 `backtest_id=job_dir.name` 与进度回调，`status.json.progress` 可被前端轮询。
  - `factor_composition` 的批次汇总查找兼容版本化目录，优先最新批次，回退旧扁平路径。
- MySQL：schema 升到 v3，新增 `factor_backtest_runs`（主键 `backtest_id`，含 job_id / factor_run_id / pool_id / 区间 / TopK / 初始资金 / accepted、selected、completed、failed / output_dir / run_key_prefix / config / manifest / created_at）；`sync_all` 扫描 `factor_backtest_manifest.json`，报告增加 `factor_backtests`。
- 前端（`原型/`）：
  - `client.ts` 增加因子运行/批量回测类型与 `factorRuns / factorRun / createFactorBacktest / factorBacktests / factorBacktest`，结果详情与文件下载改用 `run_key`，新增 `factorBacktestFileUrl`。
  - `FactorBacktestPage` 重写：运行下拉、合格因子表格全选/部分勾选、完整参数表单、提交后轮询进度条、完成后自动选中新批次并刷新；批次下拉、汇总表（年化/夏普/回撤/换手/成本/胜率）、失败 Alert、汇总/失败 CSV 下载，「结果」按钮按 `row.run_key` 跳转结果页。
  - 结果页与页面导航改用 `run_key`；结果详情显示批次 Tag；`ResultSourceSelect` 的 value 改为 `run_key`。
- 测试：新增/扩展 `test_results.py`（嵌套 `run_key`）、`test_factor_backtest.py`（版本化目录、选择性 `factor_ids`、进度序列、未知/空 ID、非法 `backtest_id`）、`test_api_routes.py`（运行列表/详情、提交 payload/spawn、参数与签名校验、spawn 失败、批次列表/详情/下载、嵌套结果详情/下载、路径穿越）、`test_mysql_store.py`（新表与批次 upsert）、`test_platform_jobs.py`（`backtest_factors` 注入 batch id 与进度）。
- 验证：后端 targeted tests 全部通过，全量套件仅保留既有 `test_streamlit_app.py` pandas 3.0 dtype 失败；`py -3 -m compileall -q custom_bt api` 通过；前端 `pnpm exec tsc --noEmit` 与 `pnpm build` 通过。
- 文档：`docs/web_api.md`（架构、端点表、§2.9、MySQL v3、已知坑、Step 7）、`README.md`（端点与表清单）、`progress.md` 本条。公司库仍只读，密码未写入任何文件/响应/日志。
- 联调修复（真实任务跑出来的两个问题）：
  - 批次详情 500：没有失败因子时 `factor_backtest_failures.csv` 只有一个空行，`pd.read_csv` 抛 `pd.errors.EmptyDataError`；`_csv_records` 捕获后返回 `[]`，并新增空失败 CSV 用例。
  - 新批次不自动选中：任务完成瞬间批次列表还没刷新，选择逻辑会先回退到旧批次；`FactorBacktestPage` 增加 `pendingBatchRef`，等列表出现刚提交的 `backtest_id` 后再选中，批次列表同时按当前 `runId` 过滤，手动切换运行时清空 pending。
- 最终验证：后端 targeted **49 passed**；全量 **232 passed / 1 failed / 84 subtests passed**，唯一失败仍是既有 `test_streamlit_app.py::test_saved_runs_table_keeps_topk_arrow_compatible`（pandas 3.0 dtype，与本次改动无关）；前端 `pnpm exec tsc --noEmit` 与 `pnpm build` 通过。
- 真机联调：临时因子运行 + API/React 双路径各提交一次批量回测，进度从 running 推进到 finished，批次汇总 2/2 成功，`run_key` 结果详情与 CSV 下载正常；MySQL `factor_backtest_runs` 与逐因子回测/日度数据均落库；Playwright 截图确认新批次自动选中、表格无换行错位、除 `/favicon.ico` 外无 4xx/5xx。联调数据（临时 `factor_runs/smoke_web_20261025`、版本化结果目录、3 个任务目录、MySQL 中 5 条回测与 3 条批次及子表）已全部清理，计数回到联调前基线（`factor_backtest_runs=0`、`backtests=1`、日度 1202 / 交易 12503 / 持仓 34272），schema 版本 3。

## 2026-10-25 临时联调因子运行（demo）与 factor_runs 根目录对齐

- 背景：本地没有任何因子运行，因子回测页为空；真实 PPO 生成所需的 `gymnasium / stable-baselines3 / sb3-contrib` 未安装，「因子生成」页仍是 mock。
- 按用户选择创建临时联调运行 `factor_runs/demo_liquid_300_20261025`（工作区根目录）：
  - 使用 `liquid_300_43a25f67` 股票池与本地主缓存，9 条人工指定表达式经 `SingleFactorEvaluator` 真实评估（train/valid/test）；验收采用放宽的 demo 阈值（`min_coverage=0.5`、`min_train_ic=0`、不设 valid IC / ICIR 下限）。
  - `factor_run.json` 与每条 accepted 记录均带 `demo: true`；manifest 记录 `quality_mode=demo-relaxed` 与原始指标，明确注明「未经过 PPO 训练，仅用于验证 Web 批量回测链路」。
  - 真实生成阈值下只有 `ts_mean(close,20)` 合格；其余候选在 demo 阈值下入选，因此这批因子不能当作投研结论。
- 根目录口径修正：`configs/factor_generation.yaml` 的 `factor_runs_root` 从 `../factor_runs`（实际解析到 `custom_backtester/factor_runs`）改为 `../../factor_runs`，与 API 的 `WORKSPACE_ROOT/factor_runs`、`mysql_store.sync_all` 默认一致；`docs/web_api.md` §7 对应条目同步更新。
- 验证：`GET /api/factor-runs` 返回 demo 运行与 9 个因子；通过 API 提交 2 个因子（`factor_0001_bfdffacfb5`、`factor_0003_6be8cf6c23`）→ job `20261025_162958_a7594086` 成功 2/2，批次详情含 `run_key` 与回测指标；Playwright 打开页面确认运行下拉、9 条合格因子、已完成批次和结果表均正常，无 4xx/5xx（仅 `/favicon.ico` 404）。
- 测试：`tests/test_factor_generation.py tests/test_api_routes.py` → **26 passed**。
- 说明：该演示批次已写入 MySQL（新增 1 条 `factor_backtest_runs`、2 条 `backtests` 及日度/交易/持仓子表）；不需要时可直接删除 `factor_runs/demo_liquid_300_20261025`、对应批次输出目录及 MySQL 记录。

## 2026-10-25 股票池板块筛选前置与计数

- 板块筛选原本已由后端支持（`boards`，按代码前缀推导），但藏在「高级筛选」折叠里，容易被当成没有。
- 前端 `PoolsPage`：把「板块」移到主筛选区（市场右侧），下拉选项显示各板块数量；「代码 / 名称关键词」单独一行；高级折叠只保留 `ListedSector` / `ListedState` 库内原始编码。
- 实测板块分布：沪市主板 1717、深市主板 1505、创业板 1415、科创板 617、北交所 337、其他 1；`/api/universe/stocks?boards=创业板&master_only=true` → matched 1415 / creatable 1400。
- UI 验证：选择「创业板（1415）」后请求 `boards=创业板`，默认 250 天上市过滤下匹配/可建池 1310，预览行板块均为创业板；`pnpm exec tsc --noEmit` 与 `pnpm build` 通过。
- 口径说明：「板块」是上市板块（沪市主板/深市主板/创业板/科创板/北交所/其他），不使用 `ListedSector` 原始编码；行业仍走 `FirstIndustryName`。

## 2026-10-27 股票池改为 MySQL 主读、本地兜底

- 背景：用户要求股票池候选直接读公司 ClickHouse、建池结果存 MySQL；此前建池已尽力镜像 MySQL，但 API 只读本地文件。
- `GET /api/pools` / `GET /api/pools/{pool_id}`：优先读 MySQL `pools.manifest` + `pool_codes`，未配置、连不上或池只存在于本地时回退 `data_cache/pools/*/manifest.json`；列表会合并本地独有池，响应新增 `storage`（`mysql` / `mysql+local` / `local`）。
- `custom_bt/mysql_store.py` 新增 `fetch_pools` / `fetch_pool`：只读连接（不执行建表），JSON 列兼容 `str` / `bytes` / `dict`；`pool_codes` 为空时用 `pool_candidates` 补 `requested_codes`。
- 建池流程不变：先写本地 manifest（回测需要），成功后 `persist_pool` 写 MySQL；失败只记 warning，本地池仍可展示，之后可用 `mysql-sync` 补录。
- 股票池候选仍由公司 ClickHouse 决定（`/api/universe/*`），与本地主缓存取交集仅用于保证回测数据可用。
- 验证：`tests/test_mysql_store.py tests/test_api_routes.py` → **43 passed**；全量（排除旧 Streamlit 测试）→ **212 passed / 84 subtests**；真实 MySQL 5 个池全部 `storage=mysql`。
