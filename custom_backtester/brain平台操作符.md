# WorldQuant BRAIN 可用 Operators 说明
API 来源：`https://api.worldquantbrain.com/operators`
可用 operator 数量：`66`
原始 API 快照：`outputs/brain_operators_api_20260525_230032.json`

说明：本文档来自当前账号 API 返回结果。平台 operator、scope、definition 和 description 可能变化；实际可用性以当次 API 和 simulation 报错为准。

## 分类速查

| 分类 | 数量 | 使用提醒 |
| --- | ---: | --- |
| `Arithmetic` | 15 | 基础数值变换。常用于方向调整、极值压缩、比例构造、异常值处理前后的形状控制。 |
| `Cross Sectional` | 6 | 横截面算子。每天在同一 universe 内对股票做排序、标准化、分位数或去极值。 |
| `Group` | 6 | 分组算子。按行业、子行业、国家等 group 做相对比较、填充、标准化或中性化。 |
| `Logical` | 11 | 条件与布尔逻辑。常用于分段信号、过滤交易、处理缺失值或只在特定状态下持仓。 |
| `Time Series` | 24 | 时间序列算子。沿着单只股票自己的历史做 rolling / delay / delta / regression 等处理。 |
| `Transformational` | 2 | 信号形状转换。常用于排序、标准化、压缩尾部、把原始字段变成更稳定的 alpha 输入。 |
| `Vector` | 2 | 向量字段算子。用于把一天内多个事件/记录聚合成 matrix 值，后续才能接普通算子。 |

## Operator 索引

- **Arithmetic**：`abs`, `add`, `densify`, `divide`, `inverse`, `log`, `max`, `min`, `multiply`, `power`, `reverse`, `sign`, `signed_power`, `sqrt`, `subtract`
- **Cross Sectional**：`normalize`, `quantile`, `rank`, `scale`, `winsorize`, `zscore`
- **Group**：`group_backfill`, `group_mean`, `group_neutralize`, `group_rank`, `group_scale`, `group_zscore`
- **Logical**：`and`, `equal`, `greater`, `greater_equal`, `if_else`, `is_nan`, `less`, `less_equal`, `not`, `not_equal`, `or`
- **Time Series**：`days_from_last_change`, `hump`, `kth_element`, `last_diff_value`, `ts_arg_max`, `ts_arg_min`, `ts_av_diff`, `ts_backfill`, `ts_corr`, `ts_count_nans`, `ts_covariance`, `ts_decay_linear`, `ts_delay`, `ts_delta`, `ts_mean`, `ts_product`, `ts_quantile`, `ts_rank`, `ts_regression`, `ts_scale`, `ts_std_dev`, `ts_step`, `ts_sum`, `ts_zscore`
- **Transformational**：`bucket`, `trade_when`
- **Vector**：`vec_avg`, `vec_sum`

## 逐个说明

## Arithmetic

基础数值变换。常用于方向调整、极值压缩、比例构造、异常值处理前后的形状控制。

### `abs`

- **语法/定义**：`abs(x)`
- **Scope**：`REGULAR`
- **平台说明**：Returns the absolute value of a number, removing any negative sign.
- **中文解读**：取绝对值。适合只关心偏离程度、不关心正负方向的场景，例如异常波动、极端估值或偏离均值的程度。
- **例子**：`abs(x)`
- **注意**：先在简单表达式里单独测试该算子，再放入复杂 Alpha。
- **注意**：关注输出范围、NaN 行为、极端值和对 turnover 的影响。
- **API 其他字段**：`level`=ALL

### `add`

- **语法/定义**：`add(x, y, filter = false), x + y`
- **Scope**：`REGULAR`
- **平台说明**：Adds two or more inputs element wise. Set filter=true to treat NaNs as 0 before summing.
- **中文解读**：加法。常用于平移阈值、组合两个同向信号，或给分母加入小常数做保护。
- **例子**：`add(x, y)`
- **注意**：先在简单表达式里单独测试该算子，再放入复杂 Alpha。
- **注意**：关注输出范围、NaN 行为、极端值和对 turnover 的影响。
- **API 其他字段**：`level`=ALL

### `densify`

- **语法/定义**：`densify(x)`
- **Scope**：`REGULAR`
- **平台说明**：Converts a grouping field of many buckets into lesser number of only available buckets so as to make working with grouping fields computationally efficient
- **中文解读**：把离散/稀疏取值重新映射为紧密整数标签，常用于 group 或 bucket 前处理。
- **例子**：`densify(x)`
- **注意**：先在简单表达式里单独测试该算子，再放入复杂 Alpha。
- **注意**：关注输出范围、NaN 行为、极端值和对 turnover 的影响。
- **API 其他字段**：`level`=ALL

### `divide`

- **语法/定义**：`divide(x, y), x / y`
- **Scope**：`REGULAR`
- **平台说明**：x / y
- **中文解读**：除法。常用于构造比例、效率、强度归一化。实战中要防止分母为 0 或过小。
- **例子**：`divide(x, y)`
- **注意**：先在简单表达式里单独测试该算子，再放入复杂 Alpha。
- **注意**：关注输出范围、NaN 行为、极端值和对 turnover 的影响。
- **API 其他字段**：`level`=ALL

### `inverse`

- **语法/定义**：`inverse(x)`
- **Scope**：`REGULAR`
- **平台说明**：1 / x
- **中文解读**：取倒数。适合把越小越好的量转成越大越好，但要小心 0 和极小值。
- **例子**：`inverse(x)`
- **注意**：先在简单表达式里单独测试该算子，再放入复杂 Alpha。
- **注意**：关注输出范围、NaN 行为、极端值和对 turnover 的影响。
- **API 其他字段**：`level`=ALL

### `log`

- **语法/定义**：`log(x)`
- **Scope**：`REGULAR`
- **平台说明**：Calculates the natural logarithm of the input value. Commonly used to transform data that has positive values.
- **中文解读**：对数压缩。适合市值、成交量、规模类右偏分布字段，但输入需要为正。
- **例子**：`log(x)`
- **注意**：先在简单表达式里单独测试该算子，再放入复杂 Alpha。
- **注意**：关注输出范围、NaN 行为、极端值和对 turnover 的影响。
- **API 其他字段**：`level`=ALL

### `max`

- **语法/定义**：`max(x, y, ..)`
- **Scope**：`REGULAR`
- **平台说明**：Maximum value of all inputs. At least 2 inputs are required
- **中文解读**：取较大值。可用于截断下界或选择较强信号。
- **例子**：`max(x, y, ..)`
- **注意**：先在简单表达式里单独测试该算子，再放入复杂 Alpha。
- **注意**：关注输出范围、NaN 行为、极端值和对 turnover 的影响。
- **API 其他字段**：`level`=ALL

### `min`

- **语法/定义**：`min(x, y ..)`
- **Scope**：`REGULAR`
- **平台说明**：Minimum value of all inputs. At least 2 inputs are required
- **中文解读**：取较小值。可用于截断上界或保守组合。
- **例子**：`min(x, y ..)`
- **注意**：先在简单表达式里单独测试该算子，再放入复杂 Alpha。
- **注意**：关注输出范围、NaN 行为、极端值和对 turnover 的影响。
- **API 其他字段**：`level`=ALL

### `multiply`

- **语法/定义**：`multiply(x ,y, ... , filter=false), x * y`
- **Scope**：`REGULAR`
- **平台说明**：Multiplies two or more inputs element wise. Set filter=true to treat NaNs as 0 before multiplication
- **中文解读**：乘法。常用于信号加权、条件门控，或把两个逻辑同时成立的强度合成。
- **例子**：`multiply(x, y)`
- **注意**：先在简单表达式里单独测试该算子，再放入复杂 Alpha。
- **注意**：关注输出范围、NaN 行为、极端值和对 turnover 的影响。
- **API 其他字段**：`level`=ALL

### `power`

- **语法/定义**：`power(x, y)`
- **Scope**：`REGULAR`
- **平台说明**：x ^ y
- **中文解读**：幂变换。用于放大或压缩数值差距，但负数输入可能受限制。
- **例子**：`power(x, y)`
- **注意**：先在简单表达式里单独测试该算子，再放入复杂 Alpha。
- **注意**：关注输出范围、NaN 行为、极端值和对 turnover 的影响。
- **API 其他字段**：`level`=ALL

### `reverse`

- **语法/定义**：`reverse(x)`
- **Scope**：`REGULAR`
- **平台说明**： - x
- **中文解读**：反向信号，等价于改变多空方向。负 Sharpe 时常先试它。
- **例子**：`reverse(x)`
- **注意**：先在简单表达式里单独测试该算子，再放入复杂 Alpha。
- **注意**：关注输出范围、NaN 行为、极端值和对 turnover 的影响。
- **API 其他字段**：`level`=ALL

### `sign`

- **语法/定义**：`sign(x)`
- **Scope**：`REGULAR`
- **平台说明**：Returns the sign of a number: +1 for positive, -1 for negative, and 0 for zero. If the input is NaN, returns NaN.

Input: Value of 7 instruments at day t: (2, -3, 5, 6, 3, NaN, -10)
Output: (1, -1, 1, 1, 1, NaN, -1)
- **中文解读**：基础数值变换。常用于方向调整、极值压缩、比例构造、异常值处理前后的形状控制。
- **例子**：`sign(x)`
- **注意**：先在简单表达式里单独测试该算子，再放入复杂 Alpha。
- **注意**：关注输出范围、NaN 行为、极端值和对 turnover 的影响。
- **API 其他字段**：`level`=ALL

### `signed_power`

- **语法/定义**：`signed_power(x, y)`
- **Scope**：`REGULAR`
- **平台说明**：x raised to the power of y such that final result preserves sign of x
- **中文解读**：保留正负号的幂变换。适合 zscore、surprise 等正负方向都有意义的信号。
- **例子**：`signed_power(x, y)`
- **注意**：先在简单表达式里单独测试该算子，再放入复杂 Alpha。
- **注意**：关注输出范围、NaN 行为、极端值和对 turnover 的影响。
- **API 其他字段**：`level`=ALL

### `sqrt`

- **语法/定义**：`sqrt(x)`
- **Scope**：`REGULAR`
- **平台说明**：Returns the non negative square root of x. Equivalent to power(x, 0.5); for signed roots use signed_power(x, 0.5).
- **中文解读**：平方根压缩。比 log 温和，适合压缩极端正值。
- **例子**：`sqrt(x)`
- **注意**：先在简单表达式里单独测试该算子，再放入复杂 Alpha。
- **注意**：关注输出范围、NaN 行为、极端值和对 turnover 的影响。
- **API 其他字段**：`level`=ALL

### `subtract`

- **语法/定义**：`subtract(x, y, filter=false), x - y`
- **Scope**：`REGULAR`
- **平台说明**：Subtracts inputs left to right: x ? y ? … Supports two or more inputs. Set filter=true to treat NaNs as 0 before subtraction.
- **中文解读**：减法。常用于构造差值、spread、相对变化，例如短期指标减长期指标。
- **例子**：`subtract(x, y)`
- **注意**：先在简单表达式里单独测试该算子，再放入复杂 Alpha。
- **注意**：关注输出范围、NaN 行为、极端值和对 turnover 的影响。
- **API 其他字段**：`level`=ALL

## Cross Sectional

横截面算子。每天在同一 universe 内对股票做排序、标准化、分位数或去极值。

### `normalize`

- **语法/定义**：`normalize(x, useStd = false, limit = 0.0)`
- **Scope**：`REGULAR`
- **平台说明**：Centers a daily cross section by subtracting the market mean; optionally divide by the cross sectional standard deviation and clamp the result to [?limit, +limit]. NaNs are ignored in mean/std.
- **中文解读**：横截面去均值/标准化。适合消除整体水平影响，保留相对强弱。
- **例子**：`normalize(field)`
- **注意**：这类算子常用于把原始字段变成更稳健的横截面信号。
- **注意**：通常先处理极端值和 NaN，再做 rank/zscore，结果更稳定。
- **API 其他字段**：`level`=ALL

### `quantile`

- **语法/定义**：`quantile(x, driver = gaussian, sigma = 1.0)`
- **Scope**：`REGULAR`
- **平台说明**：Ranks and shifts a vector of Alpha values, then applies a chosen statistical distribution (gaussian, cauchy, or uniform) to reduce outliers. The sigma parameter controls the scale of the output.
- **中文解读**：把横截面排序映射到指定分布/分位形状。适合做稳健的尾部控制。
- **例子**：`quantile(field)`
- **注意**：这类算子常用于把原始字段变成更稳健的横截面信号。
- **注意**：通常先处理极端值和 NaN，再做 rank/zscore，结果更稳定。
- **API 其他字段**：`level`=ALL

### `rank`

- **语法/定义**：`rank(x, rate=2)`
- **Scope**：`REGULAR`
- **平台说明**：Ranks the values of the input x among all instruments, returning numbers evenly spaced between 0.0 and 1.0. Useful for normalizing data and reducing the impact of outliers.
- **中文解读**：横截面排序。最常用的稳健化工具之一，把原始量纲变成相对名次。
- **例子**：`rank(field)`
- **注意**：这类算子常用于把原始字段变成更稳健的横截面信号。
- **注意**：通常先处理极端值和 NaN，再做 rank/zscore，结果更稳定。
- **API 其他字段**：`level`=ALL

### `scale`

- **语法/定义**：`scale(x, scale=1, longscale=1, shortscale=1)`
- **Scope**：`REGULAR`
- **平台说明**：Scales the input so that the sum of absolute values across all instruments equals a specified book size. Allows separate scaling for long and short positions using optional parameters.
- **中文解读**：按总绝对值或目标规模缩放信号。常用于控制权重强度。
- **例子**：`scale(field)`
- **注意**：这类算子常用于把原始字段变成更稳健的横截面信号。
- **注意**：通常先处理极端值和 NaN，再做 rank/zscore，结果更稳定。
- **API 其他字段**：`level`=ALL

### `winsorize`

- **语法/定义**：`winsorize(x, std=4)`
- **Scope**：`REGULAR`
- **平台说明**：Winsorize limits values in a data to within a specified number of standard deviations from the mean, reducing the impact of extreme outliers.
- **中文解读**：按标准差裁剪极端值。适合先处理数据错误或少数极端点，再 rank/zscore。
- **例子**：`winsorize(field)`
- **注意**：这类算子常用于把原始字段变成更稳健的横截面信号。
- **注意**：通常先处理极端值和 NaN，再做 rank/zscore，结果更稳定。
- **API 其他字段**：`level`=ALL

### `zscore`

- **语法/定义**：`zscore(x)`
- **Scope**：`REGULAR`
- **平台说明**：Z-score is a numerical measurement that describes a value's relationship to the mean of a group of values. Z-score is measured in terms of standard deviations from the mean
- **中文解读**：横截面 z-score。衡量当天相对 universe 均值偏离多少个标准差。
- **例子**：`zscore(field)`
- **注意**：这类算子常用于把原始字段变成更稳健的横截面信号。
- **注意**：通常先处理极端值和 NaN，再做 rank/zscore，结果更稳定。
- **API 其他字段**：`level`=ALL

## Group

分组算子。按行业、子行业、国家等 group 做相对比较、填充、标准化或中性化。

### `group_backfill`

- **语法/定义**：`group_backfill(x, group, d, std = 4.0)`
- **Scope**：`REGULAR`
- **平台说明**：Fills missing (NaN) values for instruments within the same group by calculating a winsorized mean of all non-NaN values over the past d days. The winsorized mean is computed by trimming extreme values based on a specified standard deviation multiplier (std, default 4.0).
- **中文解读**：用同组信息填补缺失。适合字段覆盖不全但同组可提供基准的情况。
- **例子**：`group_backfill(rank(close), industry)`
- **注意**：group 字段要与 region/universe 匹配，常见有 industry、subindustry、sector、country。
- **注意**：组太小会导致结果不稳定，组内覆盖不足时先检查 Long/Short Count。
- **API 其他字段**：`level`=ALL

### `group_mean`

- **语法/定义**：`group_mean(x, weight, group)`
- **Scope**：`REGULAR`
- **平台说明**：Calculates the harmonic mean of a data field within each specified group.
- **中文解读**：组内均值。常用于填补缺失、构造行业基准或相对差。
- **例子**：`group_mean(rank(close), industry)`
- **注意**：group 字段要与 region/universe 匹配，常见有 industry、subindustry、sector、country。
- **注意**：组太小会导致结果不稳定，组内覆盖不足时先检查 Long/Short Count。
- **API 其他字段**：`level`=ALL

### `group_neutralize`

- **语法/定义**：`group_neutralize(x, group)`
- **Scope**：`REGULAR`
- **平台说明**：Neutralizes Alpha values within each specified group by subtracting the group mean from each value. Groups can be industry, sector, country, or any custom grouping.
- **中文解读**：组内中性化。剔除行业/国家等组暴露，保留组内相对信号。
- **例子**：`group_neutralize(rank(close), industry)`
- **注意**：group 字段要与 region/universe 匹配，常见有 industry、subindustry、sector、country。
- **注意**：组太小会导致结果不稳定，组内覆盖不足时先检查 Long/Short Count。
- **API 其他字段**：`level`=ALL

### `group_rank`

- **语法/定义**：`group_rank(x, group)`
- **Scope**：`REGULAR`
- **平台说明**：Ranks each element within its group based on the input field, assigning a value between 0.0 and 1.0. This helps compare items within the same group, such as stocks in the same industry.
- **中文解读**：组内排序。常用于行业内相对强弱，减少行业暴露。
- **例子**：`group_rank(rank(close), industry)`
- **注意**：group 字段要与 region/universe 匹配，常见有 industry、subindustry、sector、country。
- **注意**：组太小会导致结果不稳定，组内覆盖不足时先检查 Long/Short Count。
- **API 其他字段**：`level`=ALL

### `group_scale`

- **语法/定义**：`group_scale(x, group)`
- **Scope**：`REGULAR`
- **平台说明**：Normalizes values within each group to a range between 0 and 1, making data comparable across different groups.
- **中文解读**：组内缩放。控制每个 group 的权重强度。
- **例子**：`group_scale(rank(close), industry)`
- **注意**：group 字段要与 region/universe 匹配，常见有 industry、subindustry、sector、country。
- **注意**：组太小会导致结果不稳定，组内覆盖不足时先检查 Long/Short Count。
- **API 其他字段**：`level`=ALL

### `group_zscore`

- **语法/定义**：`group_zscore(x, group)`
- **Scope**：`REGULAR`
- **平台说明**：Calculates the Z-score of each value within its group, showing how far each value is from the group mean in terms of standard deviations. Useful for comparing values relative to their group.
- **中文解读**：组内 z-score。衡量相对同组均值的偏离。
- **例子**：`group_zscore(rank(close), industry)`
- **注意**：group 字段要与 region/universe 匹配，常见有 industry、subindustry、sector、country。
- **注意**：组太小会导致结果不稳定，组内覆盖不足时先检查 Long/Short Count。
- **API 其他字段**：`level`=ALL

## Logical

条件与布尔逻辑。常用于分段信号、过滤交易、处理缺失值或只在特定状态下持仓。

### `and`

- **语法/定义**：`and(input1, input2)`
- **Scope**：`REGULAR`
- **平台说明**：Returns 1 ('true') if both inputs are 1 ('true'). Otherwise, returns 0 ('false').
- **中文解读**：逻辑与。用于多个条件同时满足才交易或赋值。
- **例子**：`and(input1, input2)`
- **注意**：条件逻辑会显著影响覆盖率和 turnover，写完后要看 Long/Short Count。
- **注意**：不要把大量样本无意中变成 NaN，除非你明确想过滤这些股票。
- **API 其他字段**：`level`=ALL

### `equal`

- **语法/定义**：`input1 == input2`
- **Scope**：`REGULAR`
- **平台说明**：Returns 1 ('true') if input1 and input2 are the same. Otherwise, returns 0 ('false').
- **中文解读**：相等判断。用于离散状态、分类值或事件标签。
- **例子**：`input1 == input2`
- **注意**：条件逻辑会显著影响覆盖率和 turnover，写完后要看 Long/Short Count。
- **注意**：不要把大量样本无意中变成 NaN，除非你明确想过滤这些股票。
- **API 其他字段**：`level`=ALL

### `greater`

- **语法/定义**：`input1 > input2`
- **Scope**：`REGULAR`
- **平台说明**：Returns 1 ('true') if input1 is a larger than input2. Otherwise, returns 0 ('false').
- **中文解读**：大于判断。常用于只取高分位、高覆盖或高强度区域。
- **例子**：`input1 > input2`
- **注意**：条件逻辑会显著影响覆盖率和 turnover，写完后要看 Long/Short Count。
- **注意**：不要把大量样本无意中变成 NaN，除非你明确想过滤这些股票。
- **API 其他字段**：`level`=ALL

### `greater_equal`

- **语法/定义**：`input1 >= input2`
- **Scope**：`REGULAR`
- **平台说明**：Returns 1 ('true') if input1 is a larger or the same as input2. Otherwise, returns 0 ('false').
- **中文解读**：大于等于判断。
- **例子**：`input1 >= input2`
- **注意**：条件逻辑会显著影响覆盖率和 turnover，写完后要看 Long/Short Count。
- **注意**：不要把大量样本无意中变成 NaN，除非你明确想过滤这些股票。
- **API 其他字段**：`level`=ALL

### `if_else`

- **语法/定义**：`if_else(input1, input2, input 3)`
- **Scope**：`REGULAR`
- **平台说明**：The if_else operator returns one of two values based on a condition. If the condition is true, it returns the first value; if false, it returns the second value.
- **中文解读**：条件表达式。用于分段逻辑、缺失值替代、只在某种状态下输出信号。
- **例子**：`if_else(greater(field, 0), field, 0)`
- **注意**：条件逻辑会显著影响覆盖率和 turnover，写完后要看 Long/Short Count。
- **注意**：不要把大量样本无意中变成 NaN，除非你明确想过滤这些股票。
- **API 其他字段**：`level`=ALL

### `is_nan`

- **语法/定义**：`is_nan(input)`
- **Scope**：`REGULAR`
- **平台说明**：If (input == NaN) return 1 else return 0
- **中文解读**：判断是否缺失。常用于构造 fallback 或研究字段覆盖。
- **例子**：`if_else(is_nan(field), 0, field)`
- **注意**：条件逻辑会显著影响覆盖率和 turnover，写完后要看 Long/Short Count。
- **注意**：不要把大量样本无意中变成 NaN，除非你明确想过滤这些股票。
- **API 其他字段**：`level`=ALL

### `less`

- **语法/定义**：`input1 < input2`
- **Scope**：`REGULAR`
- **平台说明**：Returns 1 ('true') if input1 is a smaller than input2. Otherwise, returns 0 ('false').
- **中文解读**：小于判断。常用于阈值过滤。
- **例子**：`input1 < input2`
- **注意**：条件逻辑会显著影响覆盖率和 turnover，写完后要看 Long/Short Count。
- **注意**：不要把大量样本无意中变成 NaN，除非你明确想过滤这些股票。
- **API 其他字段**：`level`=ALL

### `less_equal`

- **语法/定义**：`input1 <= input2`
- **Scope**：`REGULAR`
- **平台说明**：Returns 1 ('true') if input1 is a smaller or the same as input2. Otherwise, returns 0 ('false').
- **中文解读**：小于等于判断。
- **例子**：`input1 <= input2`
- **注意**：条件逻辑会显著影响覆盖率和 turnover，写完后要看 Long/Short Count。
- **注意**：不要把大量样本无意中变成 NaN，除非你明确想过滤这些股票。
- **API 其他字段**：`level`=ALL

### `not`

- **语法/定义**：`not(x)`
- **Scope**：`REGULAR`
- **平台说明**：Returns the logical negation of x. Returns 0 when x is 1 (‘true’) and 1 when x is 0 (‘false’).
- **中文解读**：逻辑非。用于反转布尔条件。
- **例子**：`not(x)`
- **注意**：条件逻辑会显著影响覆盖率和 turnover，写完后要看 Long/Short Count。
- **注意**：不要把大量样本无意中变成 NaN，除非你明确想过滤这些股票。
- **API 其他字段**：`level`=ALL

### `not_equal`

- **语法/定义**：`input1!= input2`
- **Scope**：`REGULAR`
- **平台说明**：Returns 1 ('true') if input1 and input2 are different numbers. Otherwise, returns 0 ('false').
- **中文解读**：不等判断。用于过滤某类状态。
- **例子**：`input1!= input2`
- **注意**：条件逻辑会显著影响覆盖率和 turnover，写完后要看 Long/Short Count。
- **注意**：不要把大量样本无意中变成 NaN，除非你明确想过滤这些股票。
- **API 其他字段**：`level`=ALL

### `or`

- **语法/定义**：`or(input1, input2)`
- **Scope**：`REGULAR`
- **平台说明**：Returns 1 if either input is true (either input1 or input2 has a value of 1), otherwise it returns 0.
- **中文解读**：逻辑或。用于任一条件满足即触发。
- **例子**：`or(input1, input2)`
- **注意**：条件逻辑会显著影响覆盖率和 turnover，写完后要看 Long/Short Count。
- **注意**：不要把大量样本无意中变成 NaN，除非你明确想过滤这些股票。
- **API 其他字段**：`level`=ALL

## Time Series

时间序列算子。沿着单只股票自己的历史做 rolling / delay / delta / regression 等处理。

### `days_from_last_change`

- **语法/定义**：`days_from_last_change(x)`
- **Scope**：`REGULAR`
- **平台说明**：Calculates the number of days since the last change in the value of a given variable.
- **中文解读**：距离上次变化的天数。适合低频更新字段，判断信息新鲜度。
- **例子**：`days_from_last_change(x)`
- **注意**：窗口参数不要机械套用；日频价量可以短一些，基本面/分析师/事件字段通常需要更长窗口。
- **注意**：注意低频字段的更新频率，先用 `ts_std_dev(field, n) != 0 ? 1 : 0` 检查是否真的变化。
- **API 其他字段**：`level`=ALL

### `hump`

- **语法/定义**：`hump(x, hump = 0.01)`
- **Scope**：`REGULAR`
- **平台说明**：Limits amount and magnitude of changes in input (thus reducing turnover)
- **中文解读**：限制日度信号变化幅度，平滑权重路径，常用于降 turnover。
- **例子**：`hump(x, hump = 0.01)`
- **注意**：窗口参数不要机械套用；日频价量可以短一些，基本面/分析师/事件字段通常需要更长窗口。
- **注意**：注意低频字段的更新频率，先用 `ts_std_dev(field, n) != 0 ? 1 : 0` 检查是否真的变化。
- **API 其他字段**：`level`=ALL

### `kth_element`

- **语法/定义**：`kth_element(x, d, k, ignore=“NaN”)`
- **Scope**：`REGULAR`
- **平台说明**：Returns the K-th value from a time series by looking back over a specified number of (‘d’) days, with the option to ignore certain values. Commonly used for backfilling missing data.
- **中文解读**：取窗口内第 k 个元素。适合构造稳健分位或排除极端点。
- **例子**：`kth_element(x, d, k, ignore=“NaN”)`
- **注意**：窗口参数不要机械套用；日频价量可以短一些，基本面/分析师/事件字段通常需要更长窗口。
- **注意**：注意低频字段的更新频率，先用 `ts_std_dev(field, n) != 0 ? 1 : 0` 检查是否真的变化。
- **API 其他字段**：`level`=ALL

### `last_diff_value`

- **语法/定义**：`last_diff_value(x, d)`
- **Scope**：`REGULAR`
- **平台说明**：Returns the most recent value of x from the past d days that is different from the current value of x.
- **中文解读**：寻找最近一个不同于当前值的历史值。适合低频字段变更检测。
- **例子**：`last_diff_value(x, d)`
- **注意**：窗口参数不要机械套用；日频价量可以短一些，基本面/分析师/事件字段通常需要更长窗口。
- **注意**：注意低频字段的更新频率，先用 `ts_std_dev(field, n) != 0 ? 1 : 0` 检查是否真的变化。
- **API 其他字段**：`level`=ALL

### `ts_arg_max`

- **语法/定义**：`ts_arg_max(x, d)`
- **Scope**：`REGULAR`
- **平台说明**：Returns the number of days since the maximum value occurred in the last d days of a time series. If today's value is the maximum, returns 0; if it was yesterday, returns 1, and so on.
- **中文解读**：滚动窗口内最大值出现的位置。常用于判断高点距今多久。
- **例子**：`ts_arg_max(close, 20)`
- **注意**：窗口参数不要机械套用；日频价量可以短一些，基本面/分析师/事件字段通常需要更长窗口。
- **注意**：注意低频字段的更新频率，先用 `ts_std_dev(field, n) != 0 ? 1 : 0` 检查是否真的变化。
- **API 其他字段**：`level`=ALL

### `ts_arg_min`

- **语法/定义**：`ts_arg_min(x, d)`
- **Scope**：`REGULAR`
- **平台说明**：Returns the number of days since the minimum value occurred in a time series over the past d days. If today's value is the minimum, returns 0; if it was yesterday, returns 1, and so on.
- **中文解读**：滚动窗口内最小值出现的位置。常用于判断低点距今多久。
- **例子**：`ts_arg_min(close, 20)`
- **注意**：窗口参数不要机械套用；日频价量可以短一些，基本面/分析师/事件字段通常需要更长窗口。
- **注意**：注意低频字段的更新频率，先用 `ts_std_dev(field, n) != 0 ? 1 : 0` 检查是否真的变化。
- **API 其他字段**：`level`=ALL

### `ts_av_diff`

- **语法/定义**：`ts_av_diff(x, d)`
- **Scope**：`REGULAR`
- **平台说明**：Calculates the difference between a value and its mean over a specified period, ignoring NaN values in the mean calculation. In short, it returns x – ts_mean(x, d) with NaNs ignored.
- **中文解读**：当前值与历史平均的差异。适合做偏离/回归类信号。
- **例子**：`ts_av_diff(close, 20)`
- **注意**：窗口参数不要机械套用；日频价量可以短一些，基本面/分析师/事件字段通常需要更长窗口。
- **注意**：注意低频字段的更新频率，先用 `ts_std_dev(field, n) != 0 ? 1 : 0` 检查是否真的变化。
- **API 其他字段**：`level`=ALL

### `ts_backfill`

- **语法/定义**：`ts_backfill(x,lookback = d, k=1)`
- **Scope**：`REGULAR`
- **平台说明**：Replaces missing (NaN) values in a time series with the most recent valid value from a specified lookback window, improving data coverage and reducing risk from missing data.
- **中文解读**：用历史最近有效值填补缺失。适合稀疏 fundamental、analyst、event 字段。
- **例子**：`ts_backfill(close, 20)`
- **注意**：窗口参数不要机械套用；日频价量可以短一些，基本面/分析师/事件字段通常需要更长窗口。
- **注意**：注意低频字段的更新频率，先用 `ts_std_dev(field, n) != 0 ? 1 : 0` 检查是否真的变化。
- **API 其他字段**：`level`=ALL

### `ts_corr`

- **语法/定义**：`ts_corr(x, y, d)`
- **Scope**：`REGULAR`
- **平台说明**：Calculates the Pearson correlation between two variables, x and y, over the past d days, showing how closely they move together.
- **中文解读**：滚动相关系数。用于检测两个变量历史关系，例如价格与成交量、情绪与收益。
- **例子**：`ts_corr(close, 20)`
- **注意**：窗口参数不要机械套用；日频价量可以短一些，基本面/分析师/事件字段通常需要更长窗口。
- **注意**：注意低频字段的更新频率，先用 `ts_std_dev(field, n) != 0 ? 1 : 0` 检查是否真的变化。
- **API 其他字段**：`level`=ALL

### `ts_count_nans`

- **语法/定义**：`ts_count_nans(x ,d)`
- **Scope**：`REGULAR`
- **平台说明**：Counts the number of missing (NaN) values in a data series over a specified number of days.
- **中文解读**：统计窗口内缺失数量。适合覆盖率、数据质量或稀疏性研究。
- **例子**：`ts_count_nans(close, 20)`
- **注意**：窗口参数不要机械套用；日频价量可以短一些，基本面/分析师/事件字段通常需要更长窗口。
- **注意**：注意低频字段的更新频率，先用 `ts_std_dev(field, n) != 0 ? 1 : 0` 检查是否真的变化。
- **API 其他字段**：`level`=ALL

### `ts_covariance`

- **语法/定义**：`ts_covariance(y, x, d)`
- **Scope**：`REGULAR`
- **平台说明**：Calculates the covariance between two time-series variables, y and x, over the past d days. Useful for measuring how two variables move together within a specified historical window.
- **中文解读**：滚动协方差。类似相关但保留量纲，适合强度关系。
- **例子**：`ts_covariance(close, 20)`
- **注意**：窗口参数不要机械套用；日频价量可以短一些，基本面/分析师/事件字段通常需要更长窗口。
- **注意**：注意低频字段的更新频率，先用 `ts_std_dev(field, n) != 0 ? 1 : 0` 检查是否真的变化。
- **API 其他字段**：`level`=ALL

### `ts_decay_linear`

- **语法/定义**：`ts_decay_linear(x, d, dense = false)`
- **Scope**：`REGULAR`
- **平台说明**：Applies a linear decay to time-series data over a set number of days, smoothing the data by averaging recent values and reducing the impact of older or missing data.
- **中文解读**：线性衰减加权平均。越近权重越高，常用于降低 turnover 且保留近期信息。
- **例子**：`ts_decay_linear(close, 20)`
- **注意**：窗口参数不要机械套用；日频价量可以短一些，基本面/分析师/事件字段通常需要更长窗口。
- **注意**：注意低频字段的更新频率，先用 `ts_std_dev(field, n) != 0 ? 1 : 0` 检查是否真的变化。
- **API 其他字段**：`level`=ALL

### `ts_delay`

- **语法/定义**：`ts_delay(x, d)`
- **Scope**：`REGULAR`
- **平台说明**：Returns the value of a variable x from d days ago. Use this operator to access historical data points by specifying the desired time lag in days.
- **中文解读**：取过去 n 天的值。用于构造滞后项、避免未来函数、比较今天与过去。
- **例子**：`ts_delay(close, 20)`
- **注意**：窗口参数不要机械套用；日频价量可以短一些，基本面/分析师/事件字段通常需要更长窗口。
- **注意**：注意低频字段的更新频率，先用 `ts_std_dev(field, n) != 0 ? 1 : 0` 检查是否真的变化。
- **API 其他字段**：`level`=ALL

### `ts_delta`

- **语法/定义**：`ts_delta(x, d)`
- **Scope**：`REGULAR`
- **平台说明**：Calculates the difference between a value and its delayed version over a specified period. Useful for measuring changes or momentum in time-series data.
- **中文解读**：当前值减去 n 天前值。用于变化、动量、增量或恶化速度。
- **例子**：`ts_delta(close, 20)`
- **注意**：窗口参数不要机械套用；日频价量可以短一些，基本面/分析师/事件字段通常需要更长窗口。
- **注意**：注意低频字段的更新频率，先用 `ts_std_dev(field, n) != 0 ? 1 : 0` 检查是否真的变化。
- **API 其他字段**：`level`=ALL

### `ts_mean`

- **语法/定义**：`ts_mean(x, d)`
- **Scope**：`REGULAR`
- **平台说明**：Calculates the simple average (mean) value of a variable x over the past d days.
- **中文解读**：滚动均值。用于平滑慢频信号、降低 turnover。
- **例子**：`ts_mean(close, 20)`
- **注意**：窗口参数不要机械套用；日频价量可以短一些，基本面/分析师/事件字段通常需要更长窗口。
- **注意**：注意低频字段的更新频率，先用 `ts_std_dev(field, n) != 0 ? 1 : 0` 检查是否真的变化。
- **API 其他字段**：`level`=ALL

### `ts_product`

- **语法/定义**：`ts_product(x, d)`
- **Scope**：`REGULAR`
- **平台说明**：Returns the product of the values of x over the past d days. Useful for calculating geometric means and compounding returns or growth rates.
- **中文解读**：滚动乘积。常用于复合增长或连续变化累积，但要小心极端值。
- **例子**：`ts_product(close, 20)`
- **注意**：窗口参数不要机械套用；日频价量可以短一些，基本面/分析师/事件字段通常需要更长窗口。
- **注意**：注意低频字段的更新频率，先用 `ts_std_dev(field, n) != 0 ? 1 : 0` 检查是否真的变化。
- **API 其他字段**：`level`=ALL

### `ts_quantile`

- **语法/定义**：`ts_quantile(x,d, driver="gaussian" )`
- **Scope**：`REGULAR`
- **平台说明**：Calculates the ts_rank of the input and transforms it using the inverse cumulative distribution function (quantile function) of a specified probability distribution (default: Gaussian/normal). This helps to normalize or reshape the distribution of your data over a rolling window.
- **中文解读**：时间序列分位映射。比 ts_rank 更强调分布形状转换。
- **例子**：`ts_quantile(close, 20)`
- **注意**：窗口参数不要机械套用；日频价量可以短一些，基本面/分析师/事件字段通常需要更长窗口。
- **注意**：注意低频字段的更新频率，先用 `ts_std_dev(field, n) != 0 ? 1 : 0` 检查是否真的变化。
- **API 其他字段**：`level`=ALL

### `ts_rank`

- **语法/定义**：`ts_rank(x, d, constant = 0)`
- **Scope**：`REGULAR`
- **平台说明**：Ranks the value of a variable for each instrument over a specified number of past days, returning the rank of the current value (optionally adjusted by a constant). Useful for normalizing time-series data and highlighting relative performance over time.
- **中文解读**：时间序列排序。衡量当前值在自身历史窗口中的相对位置。
- **例子**：`ts_rank(close, 20)`
- **注意**：窗口参数不要机械套用；日频价量可以短一些，基本面/分析师/事件字段通常需要更长窗口。
- **注意**：注意低频字段的更新频率，先用 `ts_std_dev(field, n) != 0 ? 1 : 0` 检查是否真的变化。
- **API 其他字段**：`level`=ALL

### `ts_regression`

- **语法/定义**：`ts_regression(y, x, d, lag = 0, rettype = 0)`
- **Scope**：`REGULAR`
- **平台说明**：Returns various parameters related to regression function
- **中文解读**：滚动回归。用于提取 beta、残差、趋势或一个变量对另一个变量的解释关系。
- **例子**：`ts_regression(close, 20)`
- **注意**：窗口参数不要机械套用；日频价量可以短一些，基本面/分析师/事件字段通常需要更长窗口。
- **注意**：注意低频字段的更新频率，先用 `ts_std_dev(field, n) != 0 ? 1 : 0` 检查是否真的变化。
- **API 其他字段**：`level`=ALL

### `ts_scale`

- **语法/定义**：`ts_scale(x, d, constant = 0)`
- **Scope**：`REGULAR`
- **平台说明**：Scales a time series to a 0–1 range based on its minimum and maximum values over a specified period, with an optional constant shift.
- **中文解读**：在时间序列窗口内缩放。适合把自身历史范围映射到稳定区间。
- **例子**：`ts_scale(close, 20)`
- **注意**：窗口参数不要机械套用；日频价量可以短一些，基本面/分析师/事件字段通常需要更长窗口。
- **注意**：注意低频字段的更新频率，先用 `ts_std_dev(field, n) != 0 ? 1 : 0` 检查是否真的变化。
- **API 其他字段**：`level`=ALL

### `ts_std_dev`

- **语法/定义**：`ts_std_dev(x, d)`
- **Scope**：`REGULAR`
- **平台说明**：Calculates the standard deviation of a data series x over the past d days, measuring how much the values deviate from their mean during that period.
- **中文解读**：滚动标准差。用于波动率、稳定性或字段更新频率检测。
- **例子**：`ts_std_dev(close, 20)`
- **注意**：窗口参数不要机械套用；日频价量可以短一些，基本面/分析师/事件字段通常需要更长窗口。
- **注意**：注意低频字段的更新频率，先用 `ts_std_dev(field, n) != 0 ? 1 : 0` 检查是否真的变化。
- **API 其他字段**：`level`=ALL

### `ts_step`

- **语法/定义**：`ts_step(1)`
- **Scope**：`REGULAR`
- **平台说明**：Returns a counter of days, incrementing by one each day.
- **中文解读**：时间步计数或序列辅助变量。常用于构造随时间变化的表达式。
- **例子**：`ts_step(close, 20)`
- **注意**：窗口参数不要机械套用；日频价量可以短一些，基本面/分析师/事件字段通常需要更长窗口。
- **注意**：注意低频字段的更新频率，先用 `ts_std_dev(field, n) != 0 ? 1 : 0` 检查是否真的变化。
- **API 其他字段**：`level`=ALL

### `ts_sum`

- **语法/定义**：`ts_sum(x, d)`
- **Scope**：`REGULAR`
- **平台说明**：Sum values of x for the past d days.
- **中文解读**：滚动求和。适合累计事件、成交量、覆盖次数或一段时间总强度。
- **例子**：`ts_sum(close, 20)`
- **注意**：窗口参数不要机械套用；日频价量可以短一些，基本面/分析师/事件字段通常需要更长窗口。
- **注意**：注意低频字段的更新频率，先用 `ts_std_dev(field, n) != 0 ? 1 : 0` 检查是否真的变化。
- **API 其他字段**：`level`=ALL

### `ts_zscore`

- **语法/定义**：`ts_zscore(x, d)`
- **Scope**：`REGULAR`
- **平台说明**：Calculates the Z-score of a time series, showing how far today's value is from the recent average, measured in standard deviations. Useful for standardizing and comparing values over time.
- **中文解读**：时间序列 z-score。衡量当前值相对自身历史是否异常。
- **例子**：`ts_zscore(close, 20)`
- **注意**：窗口参数不要机械套用；日频价量可以短一些，基本面/分析师/事件字段通常需要更长窗口。
- **注意**：注意低频字段的更新频率，先用 `ts_std_dev(field, n) != 0 ? 1 : 0` 检查是否真的变化。
- **API 其他字段**：`level`=ALL

## Transformational

信号形状转换。常用于排序、标准化、压缩尾部、把原始字段变成更稳定的 alpha 输入。

### `bucket`

- **语法/定义**：`bucket(rank(x), range=“0, 1, 0.1”, skipBoth=False, NaNGroup=False)
or
bucket(rank(x), buckets = “2,5,6,7,10”, skipBoth=False, NaNGroup=False)`
- **Scope**：`REGULAR`
- **平台说明**：The bucket operator creates custom groups by dividing data into buckets (ranges) based on ranked values of any data field. These buckets can then be used with group operators like group_neutralize, group_rank, group_zscore etc.
- **中文解读**：把连续值分桶。适合把 size、liquidity、volatility 等连续变量转成分组变量。
- **例子**：`bucket(rank(x), range=“0, 1, 0.1”, skipBoth=False, NaNGroup=False)
or
bucket(rank(x), buckets = “2,5,6,7,10”, skipBoth=False, NaNGroup=False)`
- **注意**：这类算子常用于把原始字段变成更稳健的横截面信号。
- **注意**：通常先处理极端值和 NaN，再做 rank/zscore，结果更稳定。
- **API 其他字段**：`level`=ALL

### `trade_when`

- **语法/定义**：`trade_when(x, y, z)`
- **Scope**：`REGULAR`
- **平台说明**：The trade_when operator changes Alpha values only when a specific condition is met, keeps previous values otherwise, and can close positions by assigning NaN under an exit condition. It is useful for reducing turnover and controlling when trades are executed.
- **中文解读**：条件交易/持仓控制。适合只在信号有效时换仓，其余时间保持或退出。
- **例子**：`trade_when(greater(volume, ts_mean(volume, 20)), rank(close), -1)`
- **注意**：这类算子常用于把原始字段变成更稳健的横截面信号。
- **注意**：通常先处理极端值和 NaN，再做 rank/zscore，结果更稳定。
- **API 其他字段**：`level`=ALL

## Vector

向量字段算子。用于把一天内多个事件/记录聚合成 matrix 值，后续才能接普通算子。

### `vec_avg`

- **语法/定义**：`vec_avg(x)`
- **Scope**：`REGULAR`
- **平台说明**：Calculates the mean (average) of all elements in a vector field for each instrument and date, converting vector data to a single matrix value.
- **中文解读**：向量平均。把一天内多条事件记录聚合为平均值，是 vector 字段最常用入口之一。
- **例子**：`vec_avg(vector_field)`
- **注意**：vector 字段不能直接接大多数 matrix 算子，通常先用 `vec_avg`、`vec_sum`、`vec_max` 等聚合。
- **注意**：聚合方式要贴合经济含义：平均代表典型强度，求和代表累计强度，最大值代表最强事件。
- **API 其他字段**：`level`=ALL

### `vec_sum`

- **语法/定义**：`vec_sum(x)`
- **Scope**：`REGULAR`
- **平台说明**：Calculates the sum of all values in a vector field.
- **中文解读**：向量求和。适合累计事件强度、数量、金额等。
- **例子**：`vec_sum(vector_field)`
- **注意**：vector 字段不能直接接大多数 matrix 算子，通常先用 `vec_avg`、`vec_sum`、`vec_max` 等聚合。
- **注意**：聚合方式要贴合经济含义：平均代表典型强度，求和代表累计强度，最大值代表最强事件。
- **API 其他字段**：`level`=ALL

## 附录：复杂操作符大白话版

这一节不按 API 定义来讲，而是按“你脑子里应该怎么理解它”来讲。很多 BRAIN 操作符的难点不在语法，而在于你要知道它到底是在比较“同一天不同股票”，还是比较“同一只股票自己的历史”，还是在处理“行业内相对关系”和“缺失数据”。

### 1. `rank(x)`：今天大家一起排队

`rank(x)` 是横截面排序。它问的是：

```text
今天这只股票，在全市场/当前 universe 里算高还是低？
```

例子：

```text
rank(close)
```

不是看某只股票今天是不是比昨天高，而是看今天所有股票的 `close` 放在一起，这只股票排第几。

大白话：

- `rank(x)` 比的是“别人”。
- 它最适合估值、基本面、分析师预期、情绪分数这类横截面比较。
- 如果不同行业天然水平差很多，直接 `rank` 可能会把行业差异当成 alpha。

常见搭配：

```text
rank(winsorize(x, std=4))
group_rank(x, industry)
rank(ts_delta(x, 20))
```

### 2. `ts_rank(x, d)`：和自己过去排队

`ts_rank(x, d)` 是时间序列排序。它问的是：

```text
今天这个值，在这只股票自己过去 d 天里算高还是低？
```

例子：

```text
ts_rank(close, 20)
```

意思是：今天的 `close` 在这只股票自己过去 20 天里排第几。

大白话：

- `ts_rank(x, d)` 比的是“自己过去”。
- 它适合做动量、反转、近期高低位、字段自身异常程度。
- 它不关心这只股票和别的股票谁更高，只关心它和自己的历史比。

两个常见组合的区别：

```text
rank(ts_rank(close, 20))
```

先问“每只股票是否接近自己的 20 日高位”，再问“今天谁最接近自己的 20 日高位”。

```text
ts_rank(rank(close), 20)
```

先每天算“这只股票在全市场排第几”，再问“它今天的市场排名在自己过去 20 天里是不是变强了”。

### 3. `group_rank(x, group)`：只和同组的人比

`group_rank(x, industry)` 问的是：

```text
这只股票在自己行业里排第几？
```

它不是全市场排序，而是每个行业内部各排各的。

大白话：

- 银行和银行比，软件和软件比，能源和能源比。
- 适合基本面、估值、利润率、杠杆率、分析师预期等行业差异很大的字段。
- 直接全市场比可能只是买了某个行业，`group_rank` 更像是在找行业内赢家。

例子：

```text
group_rank(value_score, industry)
```

意思是：在每个行业内部找相对便宜/相对高分的公司。

### 4. `group_zscore(x, group)`：看它离同组平均有多远

`group_zscore(x, industry)` 问的是：

```text
这只股票比同一行业平均水平高/低多少个标准差？
```

大白话：

- `group_rank` 只关心名次。
- `group_zscore` 还关心“离平均值有多远”。
- 如果你在意异常程度，而不只是排序，用 `group_zscore` 更合适。

例子：

```text
group_zscore(margin, industry)
```

意思是：这家公司利润率相对同行到底有多突出。

### 5. `group_neutralize(x, group)`：把组的整体影响拿掉

`group_neutralize(x, industry)` 问的是：

```text
如果去掉行业整体偏高/偏低，只看行业内部剩下的相对信号是什么？
```

大白话：

- 它不是排序，而是“去行业味”。
- 如果一个信号只是因为某个行业整体高，neutralize 后这部分会被拿掉。
- 常用于降低行业暴露、提高 sub-universe 或相关性检查的稳定性。

例子：

```text
group_neutralize(rank(x), industry)
```

意思是：先把信号排好，再去掉行业整体偏向。

### 6. `group_mean(x, weight, group)`：拿同组平均值当参照物

`group_mean` 可以理解成：

```text
这个行业/国家/分组的平均水平是多少？
```

大白话：

- 可用来填补缺失值。
- 可用来构造“公司值 - 行业平均值”。
- 可用来判断一家公司是不是比同组更高/更低。

例子：

```text
x - group_mean(x, 1, industry)
```

意思是：这家公司相对行业平均水平的偏离。

### 7. `group_backfill(x, group, d)`：缺数据时向同组借信息

`group_backfill` 的核心问题是：

```text
这只股票缺数据时，能不能用同组相似股票的信息帮忙补一下？
```

大白话：

- `ts_backfill` 是用“自己过去的值”补。
- `group_backfill` 是更多利用“同组其他股票/同组历史信息”补。
- 适合覆盖不完整但行业内有可比性的字段。

注意：

- 补数据不是越多越好。
- 如果 NaN 本身有经济含义，比如“没有分析师覆盖”，盲目填补会破坏信号。

### 8. `ts_backfill(x, d)`：今天没值，就沿用最近一次有效值

`ts_backfill(x, 20)` 问的是：

```text
如果今天 x 缺失，过去 20 天内最近的有效值是多少？
```

大白话：

- 今天没公告，就沿用上次公告。
- 今天没 analyst update，就沿用最近一次 update。
- 今天没新闻情绪，就看过去一段时间有没有最近新闻。

例子：

```text
ts_backfill(fundamental_field, 252)
```

适合低频 fundamental 字段。

不太适合：

```text
ts_backfill(close, 20)
```

因为 `close` 通常每天都有，补不补区别不大。

### 9. `ts_decay_linear(x, d)`：越新的数据权重越大

`ts_decay_linear(x, 10)` 可以理解成：

```text
最近 10 天加权平均，但昨天比 10 天前更重要。
```

大白话：

- 它是平滑器。
- 它能降低 turnover。
- 它比简单 `ts_mean` 更偏向近期信息。

和 simulation setting 里的 `decay` 区别：

- `ts_decay_linear(x, d)` 是你在表达式内部指定对某个变量平滑。
- setting 里的 `decay` 是平台对最终 alpha 信号整体平滑。

常见用法：

```text
rank(ts_decay_linear(signal, 5))
```

### 10. `hump(x, hump=...)`：限制信号每天变化太猛

`hump` 可以理解成给信号加一个“减震器”：

```text
今天信号想变化很多，但我只允许它慢慢变。
```

大白话：

- 它主要用于降低 turnover。
- 适合原始信号每天跳来跳去，但你认为方向有用、不想频繁换仓的情况。
- 它会让 alpha 更钝，太强可能错过短期机会。

适合：

```text
hump(rank(signal), hump=0.01)
```

### 11. `trade_when(x, y, z)`：满足条件才换仓

`trade_when` 可以理解成一个交易开关。

常见理解：

```text
trade_when(入场条件, 新alpha值, 退出条件)
```

大白话：

- 条件满足时，用新的 alpha 值。
- 条件不满足时，尽量保持之前的仓位。
- 退出条件触发时，关闭仓位。

它适合：

- 降低 turnover。
- 只在成交量足够、事件发生、信号强度足够时交易。
- 避免每天因为小噪声换仓。

例子：

```text
trade_when(greater(volume, ts_mean(volume, 20)), rank(signal), -1)
```

意思是：只有今天成交量高于 20 日均量时，才用新信号换仓。

注意：`trade_when` 很容易让覆盖率和 turnover 变化很大，跑完一定要看 Long Count、Short Count、Turnover。

### 12. `bucket(rank(x), ...)`：把股票分箱

`bucket` 可以理解成：

```text
把连续排名切成几个桶，比如低、中、高。
```

大白话：

- 它不是直接生成 alpha 分数，而是生成分组标签。
- 常拿来配合 `group_*` 使用。
- 比如按市值分成 10 桶，然后在每个市值桶里做中性化。

例子：

```text
bucket(rank(market_cap), range="0,1,0.1")
```

意思是：按市值排名分成 10 组。

再配：

```text
group_neutralize(signal, bucket(rank(market_cap), range="0,1,0.1"))
```

意思是：去掉不同市值桶带来的影响。

### 13. `winsorize(x, std=4)`：极端值别太离谱

`winsorize` 做的是：

```text
超过一定标准差的极端值，拉回到边界上。
```

大白话：

- 不是删除极端值。
- 是把太离谱的值压回来。
- 适合数据里有错误点、异常大值、长尾分布时使用。

常见顺序：

```text
rank(winsorize(x, std=4))
```

先处理极端值，再横截面排序。

### 14. `zscore(x)` / `normalize(x)`：把不同量纲变得可比

`zscore(x)` 问的是：

```text
这个值离平均水平有多远？
```

大白话：

- 原始值可能是收入、利润率、情绪分，量纲不同。
- zscore 后都变成“比平均高/低多少标准差”。
- 适合做多字段组合。

例子：

```text
zscore(profitability) - zscore(leverage)
```

意思是：盈利能力越高越好，杠杆越高越差。

### 15. `quantile(x)` / `ts_quantile(x, d)`：把排名变成更平滑的分布

`quantile` 类算子可以理解成：

```text
先排名，再按某种分布重新映射。
```

大白话：

- `rank` 只是 0 到 1 的名次。
- `quantile` 可以让尾部、中间部分变成你想要的形状。
- 适合你想强调头尾、压缩中间，或者让信号更接近正态/均匀形态。

区别：

```text
quantile(x)
```

横截面：今天所有股票之间做。

```text
ts_quantile(x, 20)
```

时间序列：每只股票和自己过去 20 天做。

### 16. `ts_corr(x, y, d)`：最近一段时间两个东西是不是一起动

`ts_corr(x, y, 60)` 问的是：

```text
过去 60 天里，x 和 y 是不是经常同涨同跌？
```

大白话：

- 接近 1：一起上、一起下。
- 接近 -1：一个上另一个下。
- 接近 0：关系不明显。

例子：

```text
ts_corr(close, volume, 20)
```

意思是：最近 20 天价格和成交量的联动关系。

注意：

- 相关性不是因果。
- 对缺失和极端值敏感。
- 窗口太短会很噪，窗口太长会反应慢。

### 17. `ts_covariance(x, y, d)`：一起动的原始强度

`ts_covariance` 和 `ts_corr` 类似，但不标准化。

大白话：

- `ts_corr` 更像“关系方向和紧密程度”。
- `ts_covariance` 还带着原始量纲和波动大小。
- 如果只是想看关系，通常 `ts_corr` 更容易解释。

### 18. `ts_regression(y, x, d)`：看 y 能被 x 解释多少

`ts_regression` 可以理解成滚动回归。

大白话：

```text
过去 d 天里，y 和 x 的线性关系是什么？
```

常见用途：

- 算 beta：股票收益对市场收益的敏感度。
- 算趋势：某个字段随时间上升/下降。
- 算残差：去掉某个解释变量后剩下的异常部分。

例子思路：

```text
ts_regression(returns, market_returns, 252)
```

可以理解为估计股票对市场的暴露。

注意：

- 输入顺序要看平台 definition。
- 回归很容易受极端值影响，必要时先 winsorize/rank。
- 窗口太短会不稳定。

### 19. `ts_arg_max(x, d)` / `ts_arg_min(x, d)`：最高点/最低点离现在多久

这两个不是返回最大值/最小值，而是返回位置。

大白话：

```text
ts_arg_max(close, 20)
```

问：过去 20 天最高价出现在几天前？

```text
ts_arg_min(close, 20)
```

问：过去 20 天最低价出现在几天前？

用途：

- 判断是否刚创新高。
- 判断高点是不是很久以前。
- 构造趋势衰退或反转信号。

### 20. `days_from_last_change(x)`：这个字段多久没变了

它问的是：

```text
x 距离上一次变化已经过了多少天？
```

大白话：

- 对每天都变的价格字段意义不大。
- 对 analyst rating、fundamental、事件状态这类低频字段很有用。
- 可以判断信息新鲜度。

例子：

```text
days_from_last_change(ts_backfill(analyst_rating, 252))
```

意思是：最近一次分析师评级变化离现在多久。

### 21. `last_diff_value(x, d)`：上一个不同的值是什么

它问的是：

```text
当前值之前，最近一个不一样的历史值是多少？
```

大白话：

- 适合低频字段。
- 可以拿当前值和上一个旧值比较，判断这次更新是上调还是下调。

例子思路：

```text
x - last_diff_value(x, 252)
```

意思是：当前值相比上一次不同的值变化了多少。

### 22. `kth_element(x, d, k)`：取窗口里第 k 个有效值

它不是平均，也不是最大最小，而是：

```text
过去 d 天里，取第 k 个有效观察值。
```

大白话：

- 适合处理有缺失的序列。
- 可以避免只看最近一天，因为最近一天可能是 NaN 或异常。
- 有时用来取“最近第 k 次出现的事件值”。

### 23. `ts_count_nans(x, d)`：数一数最近缺了多少天

它问的是：

```text
过去 d 天里 x 有多少天是 NaN？
```

大白话：

- 用来检查数据质量。
- 也可以把“缺失本身”当成信号。
- 如果一个公司长期没有 analyst/news/fundamental 更新，这件事本身可能有含义。

例子：

```text
ts_count_nans(news_sentiment, 60)
```

意思是：过去 60 天新闻情绪缺失了多少天。

### 24. `vec_avg(x)` / `vec_sum(x)`：把一天多条记录压成一个数

Vector 字段是一只股票一天可能有多条记录，比如多条新闻、多条事件、多条明细。

普通算子通常需要 matrix 值，也就是：

```text
一天一只股票一个数
```

所以要先聚合。

大白话：

```text
vec_avg(news_sentiment)
```

今天所有新闻情绪的平均值，代表“平均态度”。

```text
vec_sum(news_sentiment)
```

今天所有新闻情绪加总，代表“总冲击强度”。

选择方法：

- 想看典型水平：`vec_avg`
- 想看累计冲击：`vec_sum`
- 想看事件数量：如果有 `vec_count` 可用，用 count 类算子
- 想看最强事件：如果有 `vec_max` / `vec_min` 可用，用 max/min 类算子

### 25. `signed_power(x, y)`：保留正负号地放大极端值

普通 `power(x, y)` 遇到负数时可能不好处理。

`signed_power` 的直觉是：

```text
正的还是正的，负的还是负的，但绝对值按幂次放大/缩小。
```

大白话：

- 适合正负方向都有意义的信号。
- 比如 surprise、zscore、变化率。
- `y > 1` 会放大极端正负值。
- `0 < y < 1` 会压缩极端值。

例子：

```text
signed_power(zscore(signal), 2)
```

意思是：保留好坏方向，同时更强调离平均很远的股票。

### 26. `densify(x)`：把稀疏标签重新编号

`densify` 可以理解成：

```text
把零散的类别编号整理成连续编号。
```

大白话：

- 适合分类值、bucket、group 前处理。
- 它不是找 alpha 强弱，而是让后续分组更干净。
- 如果原始类别编号是 10、50、900，densify 后可能变成 0、1、2 这类紧密标签。

### 27. `scale(x)`：控制整体仓位强度

`scale` 可以理解成：

```text
把信号整体缩放到一个统一强度。
```

大白话：

- 不一定改变谁高谁低。
- 更多是在控制信号整体大小。
- 常用于组合多个信号前，让它们强度更可比。

例子：

```text
scale(rank(x) - 0.5)
```

意思是：先把排名转成多空方向，再统一缩放。

### 28. `ts_scale(x, d)`：按自己过去的范围缩放

`ts_scale` 问的是：

```text
当前值在自己过去 d 天范围里处于什么缩放位置？
```

大白话：

- 和 `ts_rank` 有点像，都看自己历史。
- `ts_rank` 更关心名次。
- `ts_scale` 更关心在历史数值范围里的相对位置。

### 29. `ts_av_diff(x, d)`：今天比过去平均高多少

它可以理解成：

```text
当前值 - 过去 d 天平均值
```

大白话：

- 正数：今天比近期平均高。
- 负数：今天比近期平均低。
- 适合做偏离、异常、均值回归或趋势判断。

例子：

```text
ts_av_diff(volume, 20)
```

意思是：今天成交量相对过去 20 天平均是否异常。

### 30. 怎么选复杂操作符：一句话路线图

如果你想问“今天谁比别人强”：

```text
rank(x)
```

如果你想问“今天谁比自己过去强”：

```text
ts_rank(x, d)
```

如果你想问“谁在同行里强”：

```text
group_rank(x, industry)
```

如果你想问“这个值是不是异常偏离同组平均”：

```text
group_zscore(x, industry)
```

如果你想处理缺失：

```text
ts_backfill(x, d)
group_backfill(x, group, d)
is_nan(x) ? fallback : x
```

如果你想降低 turnover：

```text
ts_decay_linear(x, d)
hump(x)
trade_when(condition, alpha, exit)
```

如果你想处理极端值：

```text
winsorize(x, std=4)
rank(x)
quantile(x)
signed_power(x, y)
```

如果你手里的字段是 vector：

```text
vec_avg(x)
vec_sum(x)
```

先把它变成 matrix，再接 `rank`、`ts_rank`、`group_rank` 等普通操作符。
