import { Alert, Button, Card, Skeleton, Space, Typography } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import type { ApiState } from "../shared/api/base";

const { Text } = Typography;

/** 统一处理加载中 / 请求失败 / 正常渲染；hint 用于补充该页特有的失败原因说明 */
export function LoadGate({ state, hint, children }: { state: ApiState<unknown>; hint?: React.ReactNode; children: React.ReactNode }) {
  if (state.loading) return <Card><Skeleton active paragraph={{ rows: 8 }} /></Card>;
  if (state.error) {
    return (
      <Card>
        <Alert
          type="error" showIcon message="数据加载失败"
          description={<Space direction="vertical" size={4}>
            <Text>{state.error}</Text>
            <Text type="secondary">请确认 backend 目录下已运行 <Text code>py -3 -m api</Text>（默认 127.0.0.1:8000）</Text>
            {hint && <Text type="secondary">{hint}</Text>}
          </Space>}
          action={<Button icon={<ReloadOutlined />} onClick={state.reload}>重试</Button>}
        />
      </Card>
    );
  }
  return <>{children}</>;
}
