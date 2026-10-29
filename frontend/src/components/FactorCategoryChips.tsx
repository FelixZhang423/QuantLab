import { Space, Tag, Tooltip } from "antd";
import {
  CATEGORY_META, CATEGORY_ORDER,
  type CategoryCount, type FactorCategoryKey,
} from "../factorInsights";

type Props = {
  counts: CategoryCount;
  value: FactorCategoryKey | "all";
  onChange: (value: FactorCategoryKey | "all") => void;
};

/**
 * 因子语义类别筛选条。只展示当前运行里真实出现过的类别，
 * 这样 9 个因子的演示运行也不会出现一排空类别。
 */
export function FactorCategoryChips({ counts, value, onChange }: Props) {
  const total = Object.values(counts).reduce((sum, count) => sum + count, 0);
  const visible = CATEGORY_ORDER.filter((key) => counts[key] > 0 || value === key);
  return (
    <Space size={6} wrap className="factor-category-chips">
      <Tag.CheckableTag
        checked={value === "all"}
        onChange={() => onChange("all")}
        className="factor-category-chip"
      >
        全部<span className="factor-category-count">{total}</span>
      </Tag.CheckableTag>
      {visible.map((key) => (
        <Tooltip key={key} title={CATEGORY_META[key].description}>
          <Tag.CheckableTag
            checked={value === key}
            onChange={() => onChange(key)}
            className="factor-category-chip"
          >
            {CATEGORY_META[key].label}
            <span className="factor-category-count">{counts[key]}</span>
          </Tag.CheckableTag>
        </Tooltip>
      ))}
    </Space>
  );
}
