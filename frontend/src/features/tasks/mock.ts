export type TaskStatus = "queued" | "running" | "finished" | "failed";

export type Task = {
  id: number;
  type: string;
  typeLabel: string;
  name: string;
  status: TaskStatus;
  progress: number;
  submittedAt: string;
  duration: string;
  owner: string;
  expression?: string;
  logs: string[];
  params?: Record<string, unknown>;
  cancelled?: boolean;
};

/** 统一动态日志时间戳（静态历史日志保留原样，新增日志一律用当前时间） */
export function nowStamp(): string {
  return new Date().toLocaleTimeString("zh-CN", { hour12: false });
}

const commonLogs = [
  "[09:12:01] 任务参数校验通过",
  "[09:12:04] 连接行情数据集，读取 5,432 只股票",
];

export const initialTasks: Task[] = [
  {
    id: 1033, type: "manual_backtest", typeLabel: "手动回测", name: "momentum_20", status: "running", progress: 62,
    submittedAt: "06-16 09:12", duration: "3m22s", owner: "林研究员", expression: "close / delay(close, 20) - 1",
    logs: [...commonLogs, "[09:12:18] 读取股票池 liquid_500", "[09:13:40] 回测进度 45%", "[09:14:22] 回测进度 62%"],
  },
  {
    id: 1032, type: "compose_factors", typeLabel: "因子组合", name: "quality_momentum_v2", status: "finished", progress: 100,
    submittedAt: "06-16 08:55", duration: "2m47s", owner: "林研究员",
    logs: [...commonLogs, "[08:56:04] 载入 8 个候选因子", "[08:57:18] 权重优化完成", "[08:57:42] 完成，结果已保存"],
  },
  {
    id: 1031, type: "generate_factors", typeLabel: "因子生成", name: "ppo_run_101", status: "failed", progress: 18,
    submittedAt: "06-16 08:12", duration: "1m15s", owner: "周研究员",
    logs: ["[08:12:01] PPO 训练环境初始化", "[08:12:19] Epoch 1/20，reward 0.113", "[08:13:16] ERROR: 特征覆盖率 coverage 低于阈值"],
  },
  {
    id: 1030, type: "manual_backtest", typeLabel: "手动回测", name: "momentum_20_prod", status: "finished", progress: 100,
    submittedAt: "06-16 07:47", duration: "4m01s", owner: "林研究员", expression: "close / delay(close, 20) - 1",
    logs: [...commonLogs, "[07:48:11] 读取股票池 liquid_500", "[07:50:45] 计算交易成本与每日持仓", "[07:51:48] 完成，结果已保存"],
  },
  {
    id: 1029, type: "create_pool", typeLabel: "股票池", name: "liquid_500", status: "queued", progress: 0,
    submittedAt: "06-16 07:10", duration: "—", owner: "陈研究员",
    logs: ["[07:10:01] 已提交建池任务", "[07:10:02] 等待可用计算资源"],
  },
  {
    id: 1028, type: "prepare_master", typeLabel: "主缓存导入", name: "daily_master_0616", status: "finished", progress: 100,
    submittedAt: "06-16 06:30", duration: "8m12s", owner: "系统",
    logs: ["[06:30:01] 校验源数据", "[06:34:42] 已写入 4,120,000 行", "[06:38:13] 完成，共写入 6,031,842 行"],
  },
  {
    id: 1027, type: "backtest_factors", typeLabel: "批量回测", name: "value_pack_06", status: "finished", progress: 100,
    submittedAt: "06-15 17:22", duration: "12m08s", owner: "张研究员", expression: "ts_rank(close, 20) - rank(TurnoverRate)",
    logs: [...commonLogs, "[17:29:05] 已完成 18/24 个因子", "[17:34:10] 完成，RankIC 均值 0.047"],
  },
  {
    id: 1026, type: "generate_factors", typeLabel: "因子生成", name: "ppo_run_100", status: "finished", progress: 100,
    submittedAt: "06-15 16:04", duration: "18m32s", owner: "周研究员",
    logs: ["[16:04:01] PPO 训练环境初始化", "[16:15:10] Epoch 16/20，reward 0.681", "[16:22:33] 完成，ICIR 1.21，score 0.74"],
  },
  {
    id: 1025, type: "create_pool", typeLabel: "股票池", name: "liquid_500_refresh", status: "failed", progress: 73,
    submittedAt: "06-15 14:31", duration: "5m44s", owner: "陈研究员",
    logs: ["[14:31:01] 读取全市场股票", "[14:34:20] 流动性筛选完成 73%", "[14:36:45] ERROR: 交易日历版本不一致"],
  },
  {
    id: 1024, type: "compose_factors", typeLabel: "因子组合", name: "multi_factor_v8", status: "queued", progress: 0,
    submittedAt: "06-15 13:12", duration: "—", owner: "林研究员", logs: ["[13:12:01] 已进入任务队列"],
  },
  {
    id: 1023, type: "prepare_master", typeLabel: "主缓存导入", name: "fundamental_q1", status: "finished", progress: 100,
    submittedAt: "06-15 11:08", duration: "6m19s", owner: "系统", logs: ["[11:08:01] 开始导入", "[11:14:20] 完成数据校验与索引构建"],
  },
  {
    id: 1022, type: "backtest_factors", typeLabel: "批量回测", name: "turnover_neutral", status: "finished", progress: 100,
    submittedAt: "06-15 10:02", duration: "9m21s", owner: "张研究员", expression: "-rank(TurnoverRate)",
    logs: [...commonLogs, "[10:11:22] 完成，coverage 98.7%"],
  },
  {
    id: 1021, type: "manual_backtest", typeLabel: "手动回测", name: "ma_bias_20", status: "finished", progress: 100,
    submittedAt: "06-15 09:41", duration: "5m02s", owner: "张研究员", expression: "close / ts_mean(close, 20) - 1",
    logs: [...commonLogs, "[09:42:06] 读取股票池 liquid_500", "[09:45:58] 完成，结果已保存"],
  },
];
