import { useCallback, useEffect, useRef, useState } from "react";

export type JobStatus = {
  job_id: string;
  operation?: string;
  status: "queued" | "running" | "finished" | "failed" | "missing" | string;
  message?: string;
  updated_at?: string;
  result?: Record<string, unknown> | null;
  progress?: Record<string, unknown> | null;
  traceback?: string | null;
};

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function readResponse<T>(response: Response, path: string): Promise<T> {
  if (!response.ok) {
    // 后端用 detail 传中文原因（如「未配置 ClickHouse 密码」「需要在公司网络环境下访问」），
    // 必须带出来，否则页面只剩一个 HTTP 状态码
    let detail = "";
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload?.detail === "string") detail = payload.detail;
    } catch {
      // 响应体不是 JSON：保留状态码信息即可
    }
    throw new ApiError(
      `请求 ${path} 失败（HTTP ${response.status}）${detail ? `：${detail}` : ""}`,
      response.status,
    );
  }
  return (await response.json()) as T;
}

export async function apiGet<T>(path: string): Promise<T> {
  // 后端改了响应结构时，避免浏览器拿旧的 GET 缓存（HMR 不会重新触发已挂载的请求）。
  const response = await fetch(path, { headers: { Accept: "application/json" }, cache: "no-store" });
  return readResponse<T>(response, path);
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return readResponse<T>(response, path);
}

export async function apiDelete<T>(path: string): Promise<T> {
  const response = await fetch(path, {
    method: "DELETE",
    headers: { Accept: "application/json" },
  });
  return readResponse<T>(response, path);
}

export function withQuery(path: string, params: Record<string, unknown>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item !== undefined && item !== null && item !== "") search.append(key, String(item));
      }
    } else {
      search.set(key, String(value));
    }
  }
  return search.size > 0 ? `${path}?${search.toString()}` : path;
}

export const fetchJob = (jobId: string) => apiGet<JobStatus>(`/api/jobs/${encodeURIComponent(jobId)}`);

export type ApiState<T> = { data: T | null; loading: boolean; error: string | null; reload: () => void };

export function useApiData<T>(loader: () => Promise<T>, deps: unknown[] = []): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    loaderRef.current()
      .then((value) => { if (alive) { setData(value); setLoading(false); } })
      .catch((err: unknown) => {
        if (alive) {
          setError(err instanceof Error ? err.message : String(err));
          setLoading(false);
        }
      });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, ...deps]);

  const reload = useCallback(() => setTick((value) => value + 1), []);
  return { data, loading, error, reload };
}

/* ---------- 后台任务轮询 Hook ---------- */

export type JobPollingState = {
  job: JobStatus | null;
  error: string | null;
  /** queued / running 期间为 true */
  polling: boolean;
};

/**
 * 轮询建池任务；返回 queued/running 状态并持续查询，
 * finished/failed/missing 后自动停止（不会无限打后端）。
 */
export function useJobPolling(jobId: string | null, intervalMs = 1500): JobPollingState {
  const [job, setJob] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [polling, setPolling] = useState(false);

  useEffect(() => {
    if (!jobId) {
      setJob(null);
      setError(null);
      setPolling(false);
      return;
    }
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    setJob(null);
    setError(null);
    setPolling(true);

    const tick = () => {
      fetchJob(jobId)
        .then((status) => {
          if (!alive) return;
          setJob(status);
          setError(null);
          if (status.status === "queued" || status.status === "running") {
            timer = setTimeout(tick, intervalMs);
          } else {
            setPolling(false);
          }
        })
        .catch((err: unknown) => {
          if (!alive) return;
          setError(err instanceof Error ? err.message : String(err));
          setPolling(false);
        });
    };

    tick();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [jobId, intervalMs]);

  return { job, error, polling };
}
