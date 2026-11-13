import type { Role } from "../../app/navigation";
import { apiGet, apiPost } from "../../shared/api/base";

export type AuthUser = {
  id: number;
  username: string;
  display_name: string;
  role: "researcher" | "admin";
};

export const roleLabel = (user: AuthUser): Role => user.role === "admin" ? "管理员" : "研究员";

export const authApi = {
  login: (credentials: { username: string; password: string; remember?: boolean }) =>
    apiPost<AuthUser>("/api/auth/login", credentials),
  me: () => apiGet<AuthUser>("/api/auth/me"),
  logout: () => apiPost("/api/auth/logout", {}),
};
