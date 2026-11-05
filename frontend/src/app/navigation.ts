import type { Task } from "../features/tasks/mock";

export type Page =
  | "login"
  | "dashboard"
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
  | "users"
  | "audit";

export type Role = "研究员" | "管理员";

export type PageNav = (p: string, id?: number, runKey?: string) => void;

export type TaskAdder = (task: Omit<Task, "id"> & { id?: number }) => number;
