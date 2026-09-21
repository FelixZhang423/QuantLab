# 独立研究数据

本目录只保存从原系统导出的版本化研究快照。研究代码只读取 `snapshots/<snapshot_id>`，不会读取 `custom_backtester` 或 `single_factor`。`current.txt` 只在完整导出和校验成功后更新；旧快照保留不变。

常用流程：

```powershell
$env:PYTHONPATH = "research_pipeline"
python -m research_system export --config research_pipeline/config.local.yaml
python -m research_system validate --data-root research_data
python -m research_system states --data-root research_data --runs-root research_runs --snapshot-id <snapshot_id>
python -m research_system values --data-root research_data --runs-root research_runs --snapshot-id <snapshot_id>
python -m research_system conditional --data-root research_data --values-run <values_run> --state-run <state_run> --runs-root research_runs --snapshot-id <snapshot_id> --horizon 20
python -m research_system select --data-root research_data --conditional-run <conditional_run> --runs-root research_runs --snapshot-id <snapshot_id> --state-id bull --split train --top-n 10
```

快照包含行情、股票池、因子目录、生成阶段指标、回测汇总和 SHA-256 清单。当前真实快照包含 500 只股票、469,982 行行情和 1,264 个 accepted 因子。

`values` 根据快照中的行情字段和因子表达式逐因子计算值，结果保存在独立运行目录：

```text
research_runs/<values_run>/
  factor_values/
    factor_id=<factor_id>/values.parquet
```

每个值分区包含 `date`、`code`、`factor_id`、`value`。系统不会把缺失值伪造成零；表达式无法计算的因子会记录失败原因。

`states` 从快照行情生成规则市场状态，结果保存在 `market_states.parquet`。`conditional` 使用未来收益标签，按状态和全局交易日顺序输出 `train`、`valid`、`test` 指标，默认比例为 60%/20%/20%，可用 `--train-ratio` 和 `--valid-ratio` 覆盖。

`select` 默认只使用训练段，先选状态下得分最高的类别，再选择具体因子并生成等权组合，同时写入 `selection.json` 和审计 manifest。当前选择基线不自动读取全部因子值计算相关性；K-Means、动态 MoE 和组合样本外回测仍属于后续研究阶段。
