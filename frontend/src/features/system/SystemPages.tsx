import { useState } from "react";
import { Alert, App, Button, Card, DatePicker, Flex, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag } from "antd";
import type { AuthUser } from "../auth/api";
import { apiGet, apiPost, useApiData, withQuery } from "../../shared/api/base";

type Account = AuthUser & { enabled: boolean };
type AuditEntry = { id: number; actor: string; action: string; target: string; created_at: string };
const actions: Record<string, string> = {
  login: "登录", login_failed: "登录失败", logout: "退出", change_password: "修改密码",
  rename_user: "修改显示名", create_user: "创建账号", enable_user: "启用账号", disable_user: "停用账号", reset_password: "重置密码",
};
const passwordRules = [{ required: true, min: 12, max: 256, message: "请输入 12 至 256 个字符" }];

function ConfirmPasswordField() {
  return <Form.Item name="confirm_password" label="确认密码" dependencies={["password"]}
    rules={[
      { required: true, message: "请再次输入密码" },
      ({ getFieldValue }) => ({
        validator: (_, value) => !value || value === getFieldValue("password")
          ? Promise.resolve() : Promise.reject(new Error("两次输入的密码不一致")),
      }),
    ]}>
    <Input.Password autoComplete="new-password" />
  </Form.Item>;
}

function systemError(error: string) {
  return error.includes("HTTP 404")
    ? "当前后端没有提供此系统管理接口。请确认后端已更新并重启，再刷新页面。"
    : error;
}

export function PasswordDialog({ onClose, onChanged }: { onClose: () => void; onChanged: () => void }) {
  const { message } = App.useApp();
  const [busy, setBusy] = useState(false);
  async function submit(values: { current_password: string; password: string }) {
    setBusy(true);
    try {
      await apiPost("/api/auth/password", { current_password: values.current_password, password: values.password });
      message.success("密码已更新，请重新登录");
      onChanged();
    } catch (error) {
      message.error(String(error));
    } finally {
      setBusy(false);
    }
  }
  return <Modal title="修改密码" open onCancel={onClose} footer={null}>
    <Form layout="vertical" onFinish={submit}>
      <Form.Item name="current_password" label="当前密码" rules={[{ required: true }]}>
        <Input.Password autoComplete="current-password" />
      </Form.Item>
      <Form.Item name="password" label="新密码" rules={passwordRules}>
        <Input.Password autoComplete="new-password" />
      </Form.Item>
      <ConfirmPasswordField />
      <Button type="primary" htmlType="submit" loading={busy}>保存并重新登录</Button>
    </Form>
  </Modal>;
}

export function UsersPage() {
  const api = useApiData(() => apiGet<Account[]>("/api/auth/users"));
  const { message } = App.useApp();
  const [search, setSearch] = useState("");
  const [renameAccount, setRenameAccount] = useState<Account | null>(null);
  const [editor, setEditor] = useState<Account | "new" | null>(null);
  const [busy, setBusy] = useState(false);
  async function save(path: string, values: unknown) {
    setBusy(true);
    try {
      await apiPost(path, values);
      setEditor(null);
      setRenameAccount(null);
      api.reload();
      message.success("账号已更新");
    } catch (error) {
      message.error(String(error));
    } finally {
      setBusy(false);
    }
  }
  const query = search.trim().toLowerCase();
  const accounts = (api.data ?? []).filter((account) =>
    [account.username, account.display_name].some((value) => value.toLowerCase().includes(query)));
  return <Card title="账号列表" extra={<Space>
    <Button onClick={api.reload} loading={api.loading}>刷新</Button>
    <Button type="primary" disabled={!api.data || Boolean(api.error)} onClick={() => setEditor("new")}>创建研究员</Button>
  </Space>}>
    <Input.Search allowClear placeholder="搜索用户名或显示名" aria-label="搜索账号"
      value={search} onChange={(event) => setSearch(event.target.value)} style={{ maxWidth: 280, marginBottom: 16 }} />
    {api.error && <Alert showIcon type="error" message={systemError(api.error)} />}
    <Table rowKey="id" dataSource={accounts} loading={api.loading} columns={[
      { title: "用户名", dataIndex: "username" },
      { title: "显示名", dataIndex: "display_name" },
      { title: "角色", render: (_, account) => account.role === "admin" ? "管理员" : "研究员" },
      { title: "状态", render: (_, account) => <Tag color={account.enabled ? "green" : "default"}>{account.enabled ? "启用" : "停用"}</Tag> },
      { title: "操作", render: (_, account) => account.role === "researcher" && <Space>
        <Button type="link" disabled={busy} onClick={() => setRenameAccount(account)}>修改显示名</Button>
        <Button type="link" disabled={busy} onClick={() => setEditor(account)}>重置密码</Button>
        <Popconfirm title={account.enabled ? "停用账号并撤销会话？" : "启用账号？"}
          onConfirm={() => save(`/api/auth/users/${account.id}`, { enabled: !account.enabled })}>
          <Button type="link" danger={account.enabled} disabled={busy}>{account.enabled ? "停用" : "启用"}</Button>
        </Popconfirm>
      </Space> },
    ]} />
    {renameAccount && <Modal title={`修改 ${renameAccount.username} 的显示名`}
      open onCancel={() => setRenameAccount(null)} footer={null}>
      <Form layout="vertical" initialValues={{ display_name: renameAccount.display_name }}
        onFinish={(values) => save(`/api/auth/users/${renameAccount.id}`, values)}>
        <Form.Item label="显示名" name="display_name" rules={[{ required: true, whitespace: true }]}>
          <Input maxLength={100} />
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={busy}>保存</Button>
      </Form>
    </Modal>}
    {editor && <Modal title={editor === "new" ? "创建研究员" : `重置 ${editor.username} 的密码`}
      open onCancel={() => setEditor(null)} footer={null}>
      <Form layout="vertical" onFinish={({ username, display_name, password }) => save(
        editor === "new" ? "/api/auth/users" : `/api/auth/users/${editor.id}`,
        editor === "new" ? { username, display_name, password } : { password },
      )}>
        {editor === "new" && <>
          <Form.Item label="用户名" name="username" rules={[{ required: true, whitespace: true }]}><Input maxLength={100} /></Form.Item>
          <Form.Item label="显示名" name="display_name" rules={[{ required: true, whitespace: true }]}><Input maxLength={100} /></Form.Item>
        </>}
        <Form.Item label="密码" name="password" rules={passwordRules}><Input.Password autoComplete="new-password" /></Form.Item>
        <ConfirmPasswordField />
        <Button type="primary" htmlType="submit" loading={busy}>保存</Button>
      </Form>
    </Modal>}
  </Card>;
}

export function AuditPage() {
  const [actor, setActor] = useState("");
  const [action, setAction] = useState<string>();
  const [dates, setDates] = useState<string[]>([]);
  const [page, setPage] = useState(1);
  const api = useApiData(() => apiGet<{ items: AuditEntry[]; total: number }>(withQuery("/api/auth/audit", {
    actor, action, start: dates[0], end: dates[1], offset: (page - 1) * 20,
  })), [actor, action, dates, page]);

  return <Card title="账号操作记录" extra={<Button onClick={api.reload}>刷新</Button>}>
    <Flex gap={12} wrap style={{ marginBottom: 16 }}>
      <Input.Search placeholder="按用户名查询" allowClear onSearch={(value) => { setActor(value.trim()); setPage(1); }} style={{ width: 210 }} />
      <Select allowClear placeholder="全部操作" style={{ width: 150 }} value={action}
        options={Object.entries(actions).map(([value, label]) => ({ value, label }))}
        onChange={(value) => { setAction(value); setPage(1); }} />
      <DatePicker.RangePicker onChange={(_, values) => { setDates(values); setPage(1); }} />
    </Flex>
    {api.error && <Alert showIcon type="error" message={systemError(api.error)} />}
    <Table rowKey="id" loading={api.loading} dataSource={api.data?.items ?? []}
      pagination={{ current: page, pageSize: 20, total: api.data?.total, showSizeChanger: false, onChange: setPage }}
      columns={[
        { title: "时间 (UTC)", dataIndex: "created_at", render: (value: string) => value.replace("T", " ") },
        { title: "操作者", dataIndex: "actor" },
        { title: "操作", dataIndex: "action", render: (value: string) => actions[value] ?? value },
        { title: "目标账号", dataIndex: "target", render: (value: string) => value || "—" },
      ]} />
  </Card>;
}
