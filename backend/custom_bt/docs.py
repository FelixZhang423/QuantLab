from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable, List

from custom_bt.operator_registry import get_operator


CATEGORY_CN = {
    "arithmetic": "数学运算",
    "cross_section": "横截面",
    "group": "分组",
    "logic": "逻辑判断",
    "time_series": "时间序列",
    "transformational": "信号转换",
    "vector": "向量",
    "custom": "自定义",
}


FIELD_ALIASES = {
    "date": "timestamps",
    "volume": "vol",
}


COMPUTED_FIELD_DOCS = {
    "vwap": {"source": "computed", "description": "成交均价，系统导入时按 amount / volume 自动计算"},
}


OPERATOR_CN_DESCRIPTIONS = {
    "abs": "取绝对值，去掉正负号，常用于只关心偏离程度的场景。",
    "add": "逐元素相加，支持多个输入；可用 filter=true 把缺失值当 0。",
    "densify": "把稀疏分类标签重新编码成连续整数，常用于分组或分箱前处理。",
    "divide": "逐元素相除，分母为 0 时输出缺失值。",
    "inverse": "取倒数 1/x，适合把越小越好的指标反向成越大越好。",
    "log": "自然对数变换，用于压缩成交额、市值等正值长尾字段。",
    "max": "逐元素取多个输入中的最大值。",
    "min": "逐元素取多个输入中的最小值。",
    "multiply": "逐元素相乘，常用于信号加权或条件门控。",
    "power": "幂运算 x^y，用于放大或压缩数值差异。",
    "reverse": "信号反向，等价于 -x。",
    "sign": "取符号，正数为 1，负数为 -1，0 为 0。",
    "signed_power": "保留正负号的幂变换，适合 zscore、变化率等有方向的信号。",
    "sqrt": "平方根变换，只对非负值有效，用于温和压缩极端正值。",
    "subtract": "从左到右逐元素相减，常用于构造差值或 spread。",
    "normalize": "每天横截面去均值；可选除以标准差并限制极端值。",
    "quantile": "先做横截面排名，再映射到 gaussian、uniform 或 cauchy 分布。",
    "rank": "每天在股票池内做横截面百分位排名，输出 0 到 1 之间的相对名次。",
    "scale": "每天横截面缩放，使绝对值之和等于指定规模。",
    "winsorize": "按横截面均值和标准差裁剪极端值，降低异常点影响。",
    "zscore": "每天横截面标准化，表示距离当日均值多少个标准差。",
    "group_backfill": "缺失值先用同日同组均值填补，再按股票时间序列向前填充。",
    "group_mean": "按日期和分组计算加权均值，可用于行业均值、板块均值等参照。",
    "group_neutralize": "减去同日同组均值，去掉行业或分组整体影响。",
    "group_rank": "在同日同组内部排名，适合同一行业内比较。",
    "group_scale": "在同日同组内部缩放，使组内信号强度可比。",
    "group_zscore": "在同日同组内部做 zscore，衡量相对同组均值的偏离。",
    "and_": "逐元素逻辑与；页面兼容写法 and(x, y)。",
    "equal": "逐元素判断是否相等。",
    "greater": "逐元素判断 x 是否大于 y。",
    "greater_equal": "逐元素判断 x 是否大于等于 y。",
    "if_else": "条件选择；条件为真取第二个输入，否则取第三个输入。",
    "is_nan": "判断输入是否为缺失值。",
    "less": "逐元素判断 x 是否小于 y。",
    "less_equal": "逐元素判断 x 是否小于等于 y。",
    "not_": "逐元素逻辑非；页面兼容写法 not(x)。",
    "not_equal": "逐元素判断是否不相等。",
    "or_": "逐元素逻辑或；页面兼容写法 or(x, y)。",
    "where": "条件选择，cond 为真取 a，否则取 b。",
    "days_from_last_change": "按股票计算当前值距离上一次变化已经过了多少天。",
    "delay": "按股票取 n 个交易日前的值。",
    "delta": "当前值减去 n 个交易日前的值。",
    "hump": "限制信号每天变化幅度，用于降低信号跳变和换手。",
    "kth_element": "取滚动窗口内倒数第 k 个有效值。",
    "last_diff_value": "取当前值之前最近一个不同的历史值。",
    "ts_arg_max": "滚动窗口内最大值距离当前有多少天。",
    "ts_arg_min": "滚动窗口内最小值距离当前有多少天。",
    "ts_av_diff": "当前值减去滚动均值。",
    "ts_backfill": "按股票用最近有效值向前填补缺失，最多填 n 天。",
    "ts_corr": "按股票计算两个序列的滚动相关系数。",
    "ts_count_nans": "按股票统计滚动窗口内缺失值数量。",
    "ts_covariance": "按股票计算两个序列的滚动协方差。",
    "ts_decay_linear": "按股票做线性衰减加权均值，越新的数据权重越大。",
    "ts_delay": "delay 的 Brain 风格别名，按股票取 n 天前的值。",
    "ts_delta": "delta 的 Brain 风格别名，当前值减 n 天前的值。",
    "ts_max": "按股票计算滚动最大值。",
    "ts_mean": "按股票计算滚动均值。",
    "ts_min": "按股票计算滚动最小值。",
    "ts_product": "按股票计算滚动乘积。",
    "ts_quantile": "按股票做滚动排名，再映射到指定分布。",
    "ts_rank": "按股票计算当前值在过去 n 天窗口内的百分位排名。",
    "ts_regression": "按股票做滚动线性回归，当前实现返回 y 对 x 的斜率。",
    "ts_scale": "按股票用滚动最小值和最大值做 0 到 1 缩放。",
    "ts_std": "按股票计算滚动标准差。",
    "ts_std_dev": "ts_std 的 Brain 风格别名，按股票计算滚动标准差。",
    "ts_step": "按股票生成从 0 开始的时间序号。",
    "ts_sum": "按股票计算滚动求和。",
    "ts_zscore": "按股票计算滚动 zscore，衡量相对自身历史均值的偏离。",
    "bucket": "把连续数值按 range 参数切成分箱标签。",
    "trade_when": "按股票实现交易开关；满足条件时更新信号，退出条件触发时清空。",
    "vec_avg": "向量均值兼容算子；当前日频单值面板中等价于原值。",
    "vec_sum": "向量求和兼容算子；当前日频单值面板中等价于原值。",
}


OPERATOR_EXAMPLES = {
    "abs": "abs(close - open)",
    "add": "add(rank(close), rank(volume))",
    "densify": "densify(industry)",
    "divide": "divide(close, open)",
    "inverse": "inverse(TurnoverRate)",
    "log": "log(amount)",
    "max": "max(close, open)",
    "min": "min(close, open)",
    "multiply": "multiply(rank(close), rank(volume))",
    "power": "power(rank(close), 2)",
    "reverse": "reverse(rank(close))",
    "sign": "sign(delta(close, 1))",
    "signed_power": "signed_power(zscore(close), 2)",
    "sqrt": "sqrt(abs(close - open))",
    "subtract": "subtract(close, open)",
    "normalize": "normalize(close)",
    "quantile": "quantile(rank(close), driver='gaussian')",
    "rank": "rank(close)",
    "scale": "scale(rank(close), scale=1)",
    "winsorize": "winsorize(close, std=4)",
    "zscore": "zscore(close)",
    "group_backfill": "group_backfill(close, industry, 5)",
    "group_mean": "group_mean(close, volume, industry)",
    "group_neutralize": "group_neutralize(rank(close), industry)",
    "group_rank": "group_rank(close, industry)",
    "group_scale": "group_scale(rank(close), industry)",
    "group_zscore": "group_zscore(close, industry)",
    "and_": "and(greater(close, open), less(TurnoverRate, 0.05))",
    "equal": "equal(if_flat, 1)",
    "greater": "greater(close, open)",
    "greater_equal": "greater_equal(close, ma20)",
    "if_else": "if_else(greater(close, open), rank(close), reverse(rank(close)))",
    "is_nan": "is_nan(close)",
    "less": "less(close, ma20)",
    "less_equal": "less_equal(TurnoverRate, 0.05)",
    "not_": "not(is_nan(close))",
    "not_equal": "not_equal(Ifsuspend, 1)",
    "or_": "or(equal(if_up, 1), equal(if_down, 1))",
    "where": "where(greater(close, open), close, open)",
    "days_from_last_change": "days_from_last_change(if_up)",
    "delay": "delay(close, 5)",
    "delta": "delta(close, 5)",
    "hump": "hump(rank(close), 0.01)",
    "kth_element": "kth_element(close, 20, 3)",
    "last_diff_value": "last_diff_value(close, 20)",
    "ts_arg_max": "ts_arg_max(close, 20)",
    "ts_arg_min": "ts_arg_min(close, 20)",
    "ts_av_diff": "ts_av_diff(close, 20)",
    "ts_backfill": "ts_backfill(close, 5)",
    "ts_corr": "ts_corr(close, volume, 20)",
    "ts_count_nans": "ts_count_nans(close, 20)",
    "ts_covariance": "ts_covariance(close, volume, 20)",
    "ts_decay_linear": "ts_decay_linear(close, 10)",
    "ts_wma": "ts_wma(close, 10)",
    "ts_ema": "ts_ema(close, 10)",
    "ts_delay": "ts_delay(close, 5)",
    "ts_delta": "ts_delta(close, 5)",
    "ts_max": "ts_max(close, 20)",
    "ts_mean": "ts_mean(close, 20)",
    "ts_var": "ts_var(close, 20)",
    "ts_median": "ts_median(close, 20)",
    "ts_mad": "ts_mad(close, 20)",
    "ts_min": "ts_min(close, 20)",
    "ts_product": "ts_product(1 + ChangePCT, 5)",
    "ts_quantile": "ts_quantile(close, 20, driver='gaussian')",
    "ts_rank": "ts_rank(close, 20)",
    "ts_regression": "ts_regression(close, volume, 20)",
    "ts_scale": "ts_scale(close, 20)",
    "ts_std": "ts_std(close, 20)",
    "ts_std_dev": "ts_std_dev(close, 20)",
    "ts_step": "ts_step(close)",
    "ts_sum": "ts_sum(volume, 20)",
    "ts_zscore": "ts_zscore(close, 20)",
    "bucket": "bucket(rank(close), range='0,1,0.1')",
    "trade_when": "trade_when(greater(volume, ts_mean(volume, 20)), rank(close), less(volume, 1))",
    "vec_avg": "vec_avg(close)",
    "vec_sum": "vec_sum(volume)",
}


def parse_field_markdown(path: str | Path) -> Dict[str, Dict[str, str]]:
    path = Path(path)
    if not path.exists():
        return {}
    docs: Dict[str, Dict[str, str]] = {}
    source = ""
    source_re = re.compile(r"^##\s+来源：`([^`]+)`")
    row_re = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*(.*?)\s*\|$")
    for line in path.read_text(encoding="utf-8").splitlines():
        source_match = source_re.match(line.strip())
        if source_match:
            source = source_match.group(1)
            continue
        row_match = row_re.match(line.strip())
        if not row_match:
            continue
        field, description = row_match.groups()
        docs[field] = {"source": source, "description": description.strip()}
    return docs


def enrich_fields(fields: Iterable[Dict[str, str]], doc_path: str | Path) -> List[Dict[str, str]]:
    docs = parse_field_markdown(doc_path)
    docs.update(COMPUTED_FIELD_DOCS)
    enriched = []
    for item in fields:
        name = item["name"]
        doc_key = name if name in docs else FIELD_ALIASES.get(name, name)
        doc = docs.get(doc_key, {})
        enriched.append(
            {
                "name": name,
                "dtype": item.get("dtype", ""),
                "source": doc.get("source", ""),
                "description": doc.get("description", "暂无字段说明"),
            }
        )
    return enriched


def enrich_operators(operators: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    enriched = []
    for item in operators:
        category = item.get("category", "")
        name = item["name"]
        try:
            definition = get_operator(name)
        except KeyError:
            definition = None
        enriched.append(
            {
                "name": name,
                "category": category,
                "category_cn": CATEGORY_CN.get(category, category),
                "canonical_name": definition.canonical_name if definition else name,
                "description_cn": OPERATOR_CN_DESCRIPTIONS.get(
                    name,
                    definition.description if definition else item.get("description", ""),
                ),
                "example": OPERATOR_EXAMPLES.get(
                    name,
                    definition.example if definition else f"{name}(close)",
                ),
                "generation_enabled": bool(definition and definition.generation_enabled),
                "manual_enabled": bool(definition.manual_enabled) if definition else True,
            }
        )
    return enriched
