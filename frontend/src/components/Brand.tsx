import { Flex, Typography } from "antd";
import { AreaChartOutlined } from "@ant-design/icons";

const { Text } = Typography;

export function Brand({ light = false }: { light?: boolean }) {
  return (
    <Flex align="center" gap={12} className="brand">
      <div className="brand-mark"><AreaChartOutlined /></div>
      <div>
        <Text strong className={light ? "brand-name brand-name-light" : "brand-name"}>QuantLab</Text>
        {!light && <Text className="brand-sub">量化因子研究平台</Text>}
      </div>
    </Flex>
  );
}
