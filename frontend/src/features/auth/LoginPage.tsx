import { useState } from "react";
import { Button, Card, Checkbox, Form, Input, message, Space, Typography } from "antd";
import { SafetyCertificateOutlined, UserOutlined } from "@ant-design/icons";
import { Brand } from "../../components/Brand";
import { authApi, type AuthUser } from "./api";

const { Title, Text } = Typography;

export function LoginPage({ onLogin }: { onLogin: (user: AuthUser) => void }) {
  const [loading, setLoading] = useState(false);
  const submit = async (values: Parameters<typeof authApi.login>[0]) => {
    setLoading(true);
    try {
      onLogin(await authApi.login(values));
    } catch (error) {
      message.error(error instanceof Error ? error.message : "登录失败");
    } finally {
      setLoading(false);
    }
  };
  return (
    <div className="login-page">
      <div className="login-orb login-orb-a" />
      <div className="login-orb login-orb-b" />
      <Card className="login-card" bordered={false}>
        <Space direction="vertical" size={26} className="full-width">
          <div className="login-heading">
            <Brand />
            <Title level={3}>欢迎登录</Title>
            <Text type="secondary">面向量化研究团队的一站式因子研究与回测平台</Text>
          </div>
          <Form layout="vertical" onFinish={submit}>
            <Form.Item label="用户名" name="username" rules={[{ required: true, message: "请输入用户名" }]}>
              <Input size="large" prefix={<UserOutlined />} placeholder="请输入用户名" />
            </Form.Item>
            <Form.Item label="密码" name="password" rules={[{ required: true, message: "请输入密码" }]}>
              <Input.Password size="large" prefix={<SafetyCertificateOutlined />} placeholder="请输入密码" />
            </Form.Item>
            <Form.Item name="remember" valuePropName="checked"><Checkbox>记住我</Checkbox></Form.Item>
            <Button block size="large" type="primary" htmlType="submit" loading={loading}>登录平台</Button>
          </Form>
        </Space>
      </Card>
      <Text className="login-footer">© 2026 QuantLab · 让每一个因子都经得起验证</Text>
    </div>
  );
}
