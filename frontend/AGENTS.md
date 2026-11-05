# QuantLab 前端开发约定

React 19 + Vite + TypeScript + Ant Design 5 + ECharts 6。真实数据经 `/api/*` 访问 `backend/` 的 FastAPI（开发期由 Vite 代理）。

## 项目结构

- `src/main.tsx`：React 入口，挂载 `src/app/App.tsx` 到 `#root`
- `src/app/App.tsx`：登录态、布局、侧边菜单、页面切换；页面状态用 `useState<Page>`，没有路由库
- `src/app/navigation.ts`：`Page` / `Role` / `PageNav` / `TaskAdder` 类型
- `src/features/`：按业务功能聚合
  - `auth/`：登录；`dashboard/`：总览；`tasks/`：任务中心
  - `data-browser/`：数据总览 / 字段 / 股票 / 操作符
  - `pools/`、`factor-generation/`、`factor-backtest/`、`manual-backtest/`
  - `results/`：结果详情 / 批次结果 / 结果分析
  - `composition/`、`system/`：因子组合、用户/审计（仍是 mock）
- `src/components/`：`Brand` / `Charts` / `LoadGate` / `FilterChips` 等跨 feature 组件
- `src/shared/api/base.ts`：fetch 基座、`ApiError`、`useApiData` / `useJobPolling`
- `src/features/<feature>/api.ts`：该 feature 的类型与请求；`index.ts` 是对外出口
- `src/api/client.ts`：兼容 barrel（合并各 feature API），新代码优先从 feature 内导入
- `src/features/<feature>/mock.ts`：仅服务尚未接入后端的页面（tasks / results / composition / system）
- `src/shared/domain/`：factorCategories / fieldCategories 等跨 feature 领域工具
- `src/index.css`：Tailwind CSS v4 入口与全局样式

## 代码约定

- **组件使用 named export**；只有 `src/app/App.tsx` 用 `export default`。
- 页面跳转通过 `PageNav` 回调，任务提交通过 `TaskAdder` 回调，由 `src/app/App.tsx` 统一持有状态；不要引入路由库或全局状态库。
- 服务端数据从 `src/api/client.ts` 取；新增接口时先在那里补类型和函数，不要在各页面里散落 `fetch`。feature 专属接口可放到该 feature 的 `api.ts`。
- 后台任务是异步的：提交后拿 `job_id`，用 `useJobPolling` 轮询到 `finished` / `failed`。
- 仍是 mock 的模块：任务中心、用户与权限、审计日志、因子组合提交表单。接入真实后端时替换对应页面里的 mock 数据。

## 样式

- Tailwind CSS v4 通过 `@tailwindcss/vite` 接入；优先用工具类，全局样式与主题变量放 `src/index.css`。
- UI 组件优先用 Ant Design，图表用 ECharts。
- 字符串含撇号时用双引号包裹；确保 JSX 标签闭合、花括号配对。
- 格式化用 `oxfmt`。

## 验证

```powershell
pnpm exec tsc --noEmit
pnpm build
```

`vite.config.ts` 里的 Figma Make 插件是历史脚手架（`index.html` 也有对应的占位槽），修改构建配置前先确认 `pnpm build` 仍通过。
