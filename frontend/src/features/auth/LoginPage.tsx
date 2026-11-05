import { useState } from "react";
import { Button, Card, Checkbox, Col, Divider, Flex, Form, Input, message, Row, Space, Typography } from "antd";
import { SafetyCertificateOutlined, UserOutlined } from "@ant-design/icons";
import { Brand } from "../../components/Brand";
import type { Role } from "../../app/navigation";

const { Title, Text } = Typography;

export function LoginPage({ onLogin }: { onLogin: (role: Role) => void }) {
  const [loading, setLoading] = useState(false);
  const [form] = Form.useForm();
  const submit = (role: Role = "研究员") => {
    setLoading(true);
    setTimeout(() => { setLoading(false); onLogin(role); message.success(`欢迎回来，${role}`); }, 650);
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
          <Form form={form} layout="vertical" initialValues={{ remember: true }} onFinish={() => submit()}>
            <Form.Item label="用户名" name="username" rules={[{ required: true, message: "请输入用户名" }]}>
              <Input size="large" prefix={<UserOutlined />} placeholder="请输入用户名" />
            </Form.Item>
            <Form.Item label="密码" name="password" rules={[{ required: true, message: "请输入密码" }]}>
              <Input.Password size="large" prefix={<SafetyCertificateOutlined />} placeholder="请输入密码" />
            </Form.Item>
            <Flex justify="space-between" align="center" className="login-options">
              <Form.Item name="remember" valuePropName="checked" noStyle><Checkbox>记住我</Checkbox></Form.Item>
              <Button type="link" onClick={() => message.info("请联系系统管理员重置密码")}>忘记密码？</Button>
            </Flex>
            <Button block size="large" type="primary" htmlType="submit" loading={loading}>登录平台</Button>
          </Form>
          <Divider plain><Text type="secondary">演示快捷入口</Text></Divider>
          <Row gutter={12}>
            <Col span={12}><Button block onClick={() => submit("研究员")}>研究员登录</Button></Col>
            <Col span={12}><Button block onClick={() => submit("管理员")}>管理员登录</Button></Col>
          </Row>
        </Space>
      </Card>
      <Text className="login-footer">© 2026 QuantLab · 让每一个因子都经得起验证</Text>
    </div>
  );
}
