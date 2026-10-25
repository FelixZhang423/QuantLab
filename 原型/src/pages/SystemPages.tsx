import { useState } from "react";
import {
  Button, Card, DatePicker, Flex, Form, Input, message, Modal, Pagination, Result, Select, Space, Switch, Table, Tag, Typography,
} from "antd";
import type { TableColumnsType } from "antd";
import { AuditOutlined, PlusOutlined, UserOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { auditData, usersData, type AuditItem, type UserItem, type UserRole } from "../mockExtended";

const { Text } = Typography;

function Forbidden() {
  return (
    <Card>
      <Result status="403" title="无访问权限" subTitle="系统管理仅对管理员开放，当前登录角色为研究员"
        extra={<Button type="primary" onClick={() => { window.scrollTo(0, 0); }}>联系管理员申请权限</Button>} />
    </Card>
  );
}

/* ============ 用户与权限 ============ */

export function UsersPage({ role }: { role: UserRole }) {
  const [users, setUsers] = useState<UserItem[]>(usersData);
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState<string>("all");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<UserItem | null>(null);
  const [form] = Form.useForm();
  if (role !== "管理员") return <Forbidden />;
  const filtered = users.filter((u) => (roleFilter === "all" || u.role === roleFilter) && `${u.username}${u.name}${u.email}`.toLowerCase().includes(search.toLowerCase()));
  const openCreate = () => { setEditing(null); form.resetFields(); setOpen(true); };
  const openEdit = (u: UserItem) => { setEditing(u); form.setFieldsValue({ username: u.username, name: u.name, email: u.email, role: u.role }); setOpen(true); };
  const save = () => {
    form.validateFields().then((values: Record<string, unknown>) => {
      if (editing) {
        setUsers((current) => current.map((u) => u.username === editing.username ? { ...u, name: String(values.name), email: String(values.email), role: values.role as UserRole } : u));
        message.success(`用户 ${editing.username} 已更新`);
      } else {
        setUsers((current) => [...current, { username: String(values.username), name: String(values.name), role: values.role as UserRole, email: String(values.email), lastLogin: "—", enabled: true }]);
        message.success(`用户 ${String(values.username)} 已创建`);
      }
      setOpen(false);
    }).catch(() => undefined);
  };
  const resetPassword = (u: UserItem) => Modal.confirm({
    title: `重置 ${u.username} 的密码？`, content: "将重置为初始密码并强制下次登录修改。",
    onOk: () => message.success(`已向 ${u.email} 发送重置链接（演示）`),
  });
  const columns: TableColumnsType<UserItem> = [
    { title: "用户名", dataIndex: "username", width: 110, render: (v) => <Text code>{v}</Text> },
    { title: "姓名", dataIndex: "name", width: 130, render: (v, r) => <Space>{v}{r.service && <Tag color="default">服务账号</Tag>}</Space> },
    { title: "角色", dataIndex: "role", width: 96, render: (v: UserRole) => <Tag color={v === "管理员" ? "gold" : "blue"}>{v}</Tag> },
    { title: "邮箱", dataIndex: "email", ellipsis: true },
    { title: "最近登录", dataIndex: "lastLogin", width: 160 },
    { title: "状态", dataIndex: "enabled", width: 80, render: (v, r) => <Switch size="small" checked={v} disabled={r.service}
      onChange={(checked) => { setUsers((current) => current.map((u) => u.username === r.username ? { ...u, enabled: checked } : u)); message.success(`${r.username} 已${checked ? "启用" : "禁用"}`); }} /> },
    { title: "操作", key: "action", width: 160, align: "right", render: (_, r) => <Space size={4}>
      <Button type="link" size="small" disabled={r.service} onClick={() => openEdit(r)}>编辑</Button>
      <Button type="link" size="small" onClick={() => resetPassword(r)}>重置密码</Button>
    </Space> },
  ];
  return (
    <Space direction="vertical" size={16} className="page-stack">
      <Card className="filter-card">
        <Flex justify="space-between" gap={16} wrap>
          <Space wrap>
            <Select value={roleFilter} onChange={setRoleFilter} className="filter-select" options={[{ value: "all", label: "全部角色" }, { value: "管理员", label: "管理员" }, { value: "研究员", label: "研究员" }]} />
            <Input.Search allowClear value={search} onChange={(e) => setSearch(e.target.value)} placeholder="搜索用户名 / 姓名 / 邮箱" className="task-search" />
          </Space>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增用户</Button>
        </Flex>
      </Card>
      <Card className="data-card">
        <Table rowKey="username" size="middle" columns={columns} dataSource={filtered} pagination={false} />
        <Flex justify="flex-end" className="table-pagination"><Text type="secondary">共 {filtered.length} 个账号 · 权限模型：管理员 / 研究员 两级</Text></Flex>
      </Card>
      <Modal open={open} title={editing ? `编辑用户 ${editing.username}` : "新增用户"} okText="保存" cancelText="取消" onOk={save} onCancel={() => setOpen(false)} width={440}>
        <Form form={form} layout="vertical" initialValues={{ role: "研究员" }} className="user-form">
          <Form.Item label="用户名" name="username" rules={[{ required: true, message: "请输入用户名" }]}>
            <Input prefix={<UserOutlined />} placeholder="登录账号（英文）" disabled={!!editing} />
          </Form.Item>
          <Form.Item label="姓名" name="name" rules={[{ required: true, message: "请输入姓名" }]}><Input placeholder="真实姓名" /></Form.Item>
          <Form.Item label="邮箱" name="email" rules={[{ required: true, type: "email", message: "请输入有效邮箱" }]}><Input placeholder="user@quantlab.cn" /></Form.Item>
          <Form.Item label="角色" name="role" rules={[{ required: true }]}>
            <Select options={[{ value: "研究员", label: "研究员 · 数据与任务操作" }, { value: "管理员", label: "管理员 · 全部权限" }]} />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  );
}

/* ============ 审计日志 ============ */

const ACTION_META: Record<string, { label: string; color: string }> = {
  login: { label: "登录", color: "green" },
  task_submit: { label: "任务提交", color: "blue" },
  task_retry: { label: "任务重试", color: "orange" },
  task_cancel: { label: "任务取消", color: "default" },
  data_import: { label: "数据导入", color: "purple" },
  pool_create: { label: "建池", color: "cyan" },
  download: { label: "结果下载", color: "geekblue" },
  note: { label: "备注编辑", color: "default" },
  permission: { label: "权限变更", color: "gold" },
  config: { label: "配置修改", color: "volcano" },
};

export function AuditPage({ role }: { role: UserRole }) {
  const [range, setRange] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>([dayjs("2026-10-01"), dayjs("2026-10-07")]);
  const [action, setAction] = useState<string>("all");
  const [user, setUser] = useState<string>("all");
  const [page, setPage] = useState(1);
  if (role !== "管理员") return <Forbidden />;
  const usernames = [...new Set(auditData.map((a) => a.user))];
  const filtered = auditData.filter((a) => {
    const t = dayjs(a.time);
    const inRange = !range || (t.isAfter(range[0].startOf("day")) && t.isBefore(range[1].endOf("day")));
    return inRange && (action === "all" || a.action === action) && (user === "all" || a.user === user);
  });
  const columns: TableColumnsType<AuditItem> = [
    { title: "时间", dataIndex: "time", width: 170, sorter: (a, b) => a.time.localeCompare(b.time) },
    { title: "操作人", dataIndex: "user", width: 100, render: (v) => <Text code>{v}</Text> },
    { title: "操作类型", dataIndex: "action", width: 110, render: (v: string) => { const m = ACTION_META[v] ?? { label: v, color: "default" }; return <Tag color={m.color}>{m.label}</Tag>; } },
    { title: "对象", dataIndex: "target", width: 120, render: (v) => <Text code>{v}</Text> },
    { title: "详情", dataIndex: "detail", ellipsis: true },
    { title: "来源 IP", dataIndex: "ip", width: 130, render: (v) => <Text type="secondary">{v}</Text> },
  ];
  return (
    <Space direction="vertical" size={16} className="page-stack">
      <Card className="filter-card">
        <Flex justify="space-between" gap={16} wrap>
          <Space wrap>
            <DatePicker.RangePicker value={range} onChange={(v) => setRange(v as [dayjs.Dayjs, dayjs.Dayjs] | null)} allowClear />
            <Select value={action} onChange={setAction} className="filter-select" options={[{ value: "all", label: "全部类型" }, ...Object.entries(ACTION_META).map(([value, item]) => ({ value, label: item.label }))]} />
            <Select value={user} onChange={setUser} className="filter-select" options={[{ value: "all", label: "全部操作人" }, ...usernames.map((u) => ({ value: u, label: u }))]} />
          </Space>
          <Text type="secondary"><AuditOutlined /> 共 {filtered.length} 条记录 · 审计日志只读、不可删除</Text>
        </Flex>
      </Card>
      <Card className="data-card">
        <Table rowKey="id" size="middle" columns={columns} dataSource={filtered.slice((page - 1) * 10, page * 10)} pagination={false} />
        <Flex justify="flex-end" className="table-pagination"><Pagination current={page} pageSize={10} total={filtered.length} showSizeChanger={false} onChange={setPage} /></Flex>
      </Card>
    </Space>
  );
}
