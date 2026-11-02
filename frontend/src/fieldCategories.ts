import type { FieldInfo } from "./api/client";

/** 来源表 → 字段类别；字段页与因子生成页共用。 */
export const FIELD_CATEGORY: Record<string, { label: string; color: string }> = {
  "dws.ll_stock_daily_sharing": { label: "行情与技术", color: "blue" },
  "ods_dps_target.lc_maindatanew": { label: "财务原始", color: "purple" },
  "dws.f10_derivative_index_fd": { label: "财务衍生", color: "geekblue" },
  "dws.f10_finance_index_fd": { label: "估值", color: "gold" },
};

const CATEGORY_COLORS: Record<string, string> = {
  行情与技术: "blue",
  财务原始: "purple",
  财务衍生: "geekblue",
  估值: "gold",
};

export function categoryForSource(source?: string | null) {
  return FIELD_CATEGORY[source ?? ""] ?? { label: "其他", color: "default" };
}

export function fieldCategory(field: FieldInfo) {
  if (field.category) {
    return { label: field.category, color: CATEGORY_COLORS[field.category] ?? "default" };
  }
  return categoryForSource(field.source);
}
