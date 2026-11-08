export type UserRole = "研究员" | "管理员";

export type UserItem = {
  username: string; name: string; role: UserRole; email: string; lastLogin: string; enabled: boolean; service?: boolean;
};

export const usersData: UserItem[] = [
  { username: "admin", name: "系统管理员", role: "管理员", email: "admin@quantlab.cn", lastLogin: "2026-10-07 09:12", enabled: true },
  { username: "system", name: "系统服务账号", role: "管理员", email: "system@quantlab.local", lastLogin: "2026-10-07 06:30", enabled: true, service: true },
  { username: "lin", name: "林研究员", role: "研究员", email: "lin@quantlab.cn", lastLogin: "2026-10-07 08:47", enabled: true },
  { username: "zhou", name: "周研究员", role: "研究员", email: "zhou@quantlab.cn", lastLogin: "2026-10-07 08:05", enabled: true },
  { username: "zhang", name: "张研究员", role: "研究员", email: "zhang@quantlab.cn", lastLogin: "2026-10-06 17:15", enabled: true },
  { username: "chen", name: "陈研究员", role: "研究员", email: "chen@quantlab.cn", lastLogin: "2026-10-06 14:28", enabled: true },
  { username: "wang", name: "王研究员", role: "研究员", email: "wang@quantlab.cn", lastLogin: "2026-09-28 11:02", enabled: false },
];

export type AuditItem = { id: number; time: string; user: string; action: string; target: string; detail: string; ip: string };

export const auditData: AuditItem[] = [
  { id: 1, time: "2026-10-07 09:12:04", user: "admin", action: "login", target: "—", detail: "管理员登录成功", ip: "192.168.1.15" },
  { id: 2, time: "2026-10-07 08:47:33", user: "lin", action: "login", target: "—", detail: "研究员登录成功", ip: "192.168.1.23" },
  { id: 3, time: "2026-10-07 08:12:45", user: "zhou", action: "task_submit", target: "#1031", detail: "提交因子生成任务 ppo_run_101", ip: "192.168.1.31" },
  { id: 4, time: "2026-10-07 08:13:52", user: "zhou", action: "task_retry", target: "#1031", detail: "重试失败任务（特征覆盖率低于阈值）", ip: "192.168.1.31" },
  { id: 5, time: "2026-10-06 17:22:18", user: "zhang", action: "task_submit", target: "#1027", detail: "提交批量回测任务 value_pack_06（24 个因子）", ip: "192.168.1.18" },
  { id: 6, time: "2026-10-06 17:35:40", user: "zhang", action: "download", target: "#1027", detail: "下载因子回测汇总 factor_backtest_summary.csv", ip: "192.168.1.18" },
  { id: 7, time: "2026-10-06 16:04:09", user: "zhou", action: "task_submit", target: "#1026", detail: "提交因子生成任务 ppo_run_100", ip: "192.168.1.31" },
  { id: 8, time: "2026-10-06 15:41:27", user: "zhang", action: "task_submit", target: "#1021", detail: "提交手动回测任务 ma_bias_20", ip: "192.168.1.18" },
  { id: 9, time: "2026-10-06 14:31:56", user: "chen", action: "task_submit", target: "#1025", detail: "提交建池任务 liquid_500_refresh", ip: "192.168.1.42" },
  { id: 10, time: "2026-10-06 13:12:03", user: "lin", action: "task_submit", target: "#1024", detail: "提交因子组合任务 multi_factor_v8", ip: "192.168.1.23" },
  { id: 12, time: "2026-10-06 10:02:44", user: "zhang", action: "download", target: "#1022", detail: "下载回测结果 turnover_neutral 全部文件", ip: "192.168.1.18" },
  { id: 13, time: "2026-10-05 19:21:10", user: "lin", action: "note", target: "#1030", detail: "保存结果备注（momentum_20_prod）", ip: "192.168.1.23" },
  { id: 14, time: "2026-10-05 10:40:22", user: "admin", action: "permission", target: "wang", detail: "新增用户 wang（研究员角色）", ip: "192.168.1.15" },
  { id: 15, time: "2026-10-04 15:02:17", user: "admin", action: "permission", target: "wang", detail: "禁用用户 wang（离职交接）", ip: "192.168.1.15" },
  { id: 16, time: "2026-10-04 09:18:55", user: "chen", action: "pool_create", target: "liquid_500", detail: "创建股票池 liquid_500（500 只）", ip: "192.168.1.42" },
  { id: 18, time: "2026-10-02 16:45:38", user: "admin", action: "config", target: "platform.yaml", detail: "修改回测默认成本参数（滑点 0.0004 → 0.0005）", ip: "192.168.1.15" },
  { id: 19, time: "2026-10-02 11:32:51", user: "lin", action: "task_cancel", target: "#1029", detail: "取消排队中的建池任务", ip: "192.168.1.23" },
  { id: 20, time: "2026-10-01 09:05:12", user: "system", action: "login", target: "—", detail: "服务账号定时任务启动", ip: "127.0.0.1" },
];
