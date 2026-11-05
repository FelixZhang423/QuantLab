import { Flex, Tag } from "antd";

/** 横铺的筛选标签行（操作符分类 / 字段来源共用）：选中项置灰，未选中为浅色胶囊 */
export function FilterChips<T extends string>({ items, value, onChange }: { items: { key: T; label: string; count: number }[]; value: T; onChange: (key: T) => void }) {
  return (
    <Flex gap={8} wrap>
      {items.map(({ key, label, count }) => (
        <Tag.CheckableTag key={key} checked={value === key} className={`category-chip${value === key ? " category-chip-active" : ""}`} onChange={() => onChange(key)}>
          {label}<span className="category-chip-count">{count}</span>
        </Tag.CheckableTag>
      ))}
    </Flex>
  );
}
