# quantops

80 个 Alpha101 / BRAIN 风格横截面与时序算子 + 表达式引擎，独立成库。

只依赖 **numpy + pandas**，不依赖本仓库任何其它模块 —— 可以在任何 Python 项目里 `import quantops` 直接用。

> 本库是这些算子的**唯一实现**。`custom_backtester/custom_bt/expressions.py` 只是转发（`from quantops.expression import ...`），
> 改算子请改这里，那边会自动跟着变。

## 安装

```bash
# 开发态（可编辑安装，改代码立即生效）
py -3 -m pip install -e D:\1\QuantLab\quantops
```

回测器侧（`custom_backtester/`）**不装也能跑**：`custom_bt/_quantops_boot.py` 会在找不到 `quantops` 时，
把库目录临时加进 `sys.path`。装上之后走的是真正的包（`pip show quantops` 能查到）。

> ⚠️ **别在仓库根 `D:\1\QuantLab\` 下跑 `import quantops` 或 `py -3 -m quantops`**：该目录下正好有个同名目录 `quantops/`
> （本项目目录，不是包），Python 3 会把它当成**命名空间包**解析出一个空模块（表现为 `AttributeError: module 'quantops' has no attribute 'OPERATORS'`；
> CLI 则会给出「当前目录下有个同名文件夹」的中文提示）。到别的目录、或先 `cd quantops` 再跑即可 ——
> `custom_backtester`、Streamlit、`/api` 都不受影响（它们 cd 在自己的目录里，或走 `_quantops_boot.py`）。

## 四种用法

### 1. 函数式：算子吃 `MultiIndex(date, code)` 的 Series

```python
import pandas as pd
import quantops as qo

panel = pd.read_csv("panel.csv")           # 长表：一列 date、一列 code、若干因子列
close = qo.to_series(panel, "close")       # -> Series，index = MultiIndex(date, code)
volume = qo.to_series(panel, "volume")

qo.ts_mean(close, 20)                      # 时序：按 code 分组滚动
qo.rank(close)                             # 横截面：按 date 分组排名
qo.ts_corr(close, volume, 20)
qo.group_neutralize(close, qo.to_series(panel, "industry"))
qo.if_else(qo.greater(close, 10), 1.0, 0.0)
```

`panel` 也可以不是一个 DataFrame，而是任何有 `date` / `code` 列的表（缺列会抛 `ExpressionError`）。
`qo.prepare_panel(panel)` 做的是 `to_series` 内部那套标准化（`date` → datetime、`code` → 6 位字符串、按 date/code 排序），
想自己拿整理好的面板就调它。反向：`qo.to_frame(series, "alpha")` → `DataFrame[date, code, alpha]`。

### 2. 方法式（pandas 访问器）

```python
close.qo.ts_mean(20).qo.rank()
close.qo.delay(1).qo.apply("ts_mean", 20)   # apply 是逃生口
```

`import quantops` 时会自动 `register_series_accessor("qo")`。方法在 import 时按 `OPERATORS` 快照生成，
**之后**用 `register_operator()` 新注册的算子只有 `apply("名字", ...)` 能调到。
给普通（非 `MultiIndex(date, code)`）Series 调 `qo.xxx` 会抛出明确的 `ExpressionError`，不会静默出错。

### 3. 表达式字符串（回测里那套，原样保留）

```python
qo.evaluate("rank(ts_mean(close, 20)) - rank(ts_mean(close, 60))", panel)
# -> DataFrame[date, code, alpha]

qo.evaluate(expr, panel, output_name="momentum")
```

表达式在 AST 白名单沙箱里求值：只允许白名单节点 + 已注册算子和面板字段，
`__import__` / 属性访问等一律抛 `ExpressionError`。字段名直接用面板列名；`and` / `or` / `not` 会自动改写成 `and_` / `or_` / `not_`。

### 4. 类式：`OperatorSet`（一个类装下全部算子）

```python
import quantops as qo

ops = qo.OperatorSet(panel)              # 绑定面板：date / code + 若干字段列

ops.rank(ops.ts_mean("close", 20))       # 80 个算子都是实例方法，字段名直接当参数
ops.eval("rank(ts_mean(close, 20))")     # 表达式字符串 -> DataFrame[date, code, alpha]
ops.to_frame(ops.rank("close"))          # MultiIndex Series -> 面板 DataFrame

ops = qo.OperatorSet()                   # 不绑面板：方法直接吃 Series
ops.ts_mean(close, 20)
```

- 方法与函数式**同一份实现**（按 `OPERATORS` 动态生成），所以 `ops.ts_mean("close", 5)` 与 `qo.ts_mean(close, 5)` 逐值相等；`max` / `min` 这类变参算子照常。
- 字符串参数**只有恰好是面板字段名**时才转成 Series：`ops.bucket("close", "0,1,0.1")`、`ops.ts_quantile("close", 20, "gaussian")` 里的字面量原样传下去。
- 字段名与算子名撞车时算子优先（`ops.rank` 是方法）；取字段用 `ops.field("rank")`，也可以直接 `ops.close`。
- `register_operator()` **之后**注册的算子同样能调到（`ops.<name>(...)` / `ops.apply("<name>", ...)`），不像访问器需要走 `apply`。
- 每个方法都带中文说明和示例（`help(ops.ts_mean)`），`__signature__` 与底层函数一致，IDE 参数提示可用。
- 元数据：`ops.names` / `ops.fields` / `ops.describe("ts_mean")` / `ops.categories()` / `ops.list_operators()`。

## 目录与说明

```python
qo.list_operators()        # [{"name","category","description"}, ...]  80 条，按 (category, name) 排序
qo.describe("ts_mean")     # 单条：分类、中文名、中文说明、示例、是否参与生成/手写
qo.categories()            # 7 个分类及各自算子数
qo.OPERATORS              # 原始注册表 {name: OperatorSpec(name, category, description, func)}
```

7 个分类：`arithmetic`、`cross_section`、`group`、`logic`、`time_series`、`transformational`、`vector`。
每个算子的中文说明与示例在 `quantops/metadata.py`，和 `custom_bt/docs.py`（`/api/operators` 的唯一生产者）由测试锁死一致性。

## CLI

```bash
py -3 -m quantops list                        # 列出全部算子
py -3 -m quantops list --category time_series
py -3 -m quantops list --search corr --json
py -3 -m quantops describe ts_mean
py -3 -m quantops eval "rank(close)" --csv panel.csv --out alpha.csv
```

## 面板约定（重要）

算子只认一种输入形状：**`pd.Series`，index 为 `MultiIndex`，前两级依次是 `date`、`code`**。

- `date`：`datetime64`；`code`：6 位字符串（`"000001"`，不是 `1`）。
- **时序算子**（`ts_*`、`delay`、`delta`、`hump`…）按 `code` 分组、按行序（即日期序）滚动 —— 面板必须先按 `date, code` 排序，否则结果是错的。
- **横截面算子**（`rank`、`zscore`、`scale`…）按 `date` 分组。
- **分组算子**（`group_*`）第二参数是分组列（如 `industry`），同样按 `date` 分组。
- 数值一律走 float64；非数值列不要传进来。
- 用 `qo.to_series` / `qo.prepare_panel` 准备数据最省事，它们把以上都做掉了。

窗口类算子的 `n` 是**行数**（每只股票各算各的），不是自然日。

## 版本与兼容

- 需要 Python ≥ 3.10、pandas ≥ 2.0（在 pandas 3.0 上同样验证通过）。
- numpy 2.x / 3.x 均可。
- 不用 `from quantops import *`：`abs` / `min` / `max` / `rank` / `where` 这些名字会和内建和 pandas 撞。
  统一写 `import quantops as qo`，再 `qo.abs(...)`。

## 开发

```bash
cd D:\1\QuantLab\quantops
py -3 -m pytest -q
```

```
quantops/
  core.py        # 私有 Series 助手（_as_series / _rolling / _rank / _group_* / _ts_* …）
  operators.py   # 80 个算子实现 + OPERATORS 注册表 + register_operator
  registry.py    # 22 个 canonical 定义（arity / alphagen 名 / 是否参与生成）
  expression.py  # AST 白名单 + 表达式求值引擎
  panel.py       # 面板 <-> MultiIndex Series 互转
  metadata.py    # 中文分类 / 说明 / 示例 + catalog() / describe() / categories()
  accessor.py    # pandas 访问器 Series.qo
  opset.py       # 类式入口 OperatorSet（动态方法 + 字段名解析）
  __main__.py    # CLI
```

测试分五块：`test_quantops_expression.py`（从回测器原样移植的精确数值断言）、
`test_public_api.py`（公开接口、面板互转、访问器、依赖守门、独立性）、
`test_golden_values.py`（固定面板上的算子金标准：80 个算子各一个 sha256 摘要 + 12 个代表算子的可读切片）、
`test_cli.py`（`list` / `describe` / `eval` 与同名目录报错文案）、
`test_opset.py`（`OperatorSet` 与函数式逐值一致、字段名/字面量字符串区分、错误提示、动态注册）。
