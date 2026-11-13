export type Page =
  | "login"
  | "tasks"
  | "backtest"
  | "result"
  | "data_overview"
  | "fields"
  | "stocks"
  | "operators"
  | "pools"
  | "factor_generation"
  | "factor_backtest"
  | "composition"
  | "composition_results"
  | "users"
  | "audit";

export type Role = "研究员" | "管理员";

export type PageNav = (p: string, id?: number, runKey?: string) => void;
