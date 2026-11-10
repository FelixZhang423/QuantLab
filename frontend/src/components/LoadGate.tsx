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
            <Text type="secondary">{state.error.includes("HTTP 502") ? "后端已响应，但上游数据查询失败；请检查数据库查询超时或连接状态后重试。" : "请检查后端服务及网络连接，或根据上方错误信息排查。"}</Text>
            {hint && <Text type="secondary">{hint}</Text>}
          </Space>}
          action={<Button icon={<ReloadOutlined />} onClick={state.reload}>重试</Button>}
        />
      </Card>
    );
  }
  return <>{children}</>;
}
