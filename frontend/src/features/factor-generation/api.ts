import { apiGet, apiPost, withQuery } from "../../shared/api/base";

export type FactorGenerationSplit = { cache_start: string; cache_end: string };

export type FactorGenerationQuality = Record<string, number | null | undefined>;

export type FactorGenerationDefaults = {
  data_source: string;
  fields: string[];
  field_count: number;
  splits: Record<string, FactorGenerationSplit>;
  split_source: "pool" | "config";
  split_ratios: Record<string, number>;
  pool_window: { start: string; end: string } | null;
  warnings: string[];
  quality: FactorGenerationQuality;
  max_backtrack_days: number;
  target_horizon: number;
  max_future_days: number;
  target_factor_count: number;
  max_attempts: number;
  rollout_timesteps: number;
  seed: number;
  device: string;
};

export type FactorGenerationRequest = {
  pool_id: string;
  run_name?: string;
  fields?: string[];
  operators?: string[];
  splits?: Record<string, FactorGenerationSplit>;
  max_backtrack_days?: number;
  target_horizon?: number;
  max_future_days?: number;
  target_factor_count?: number;
  max_attempts?: number;
  rollout_timesteps?: number;
  seed?: number;
  device?: string;
  quality?: FactorGenerationQuality;
};

export type FactorGenerationResponse = {
  job_id: string;
  status: string;
  operation: string;
  pool_id: string;
  pool_name: string | null;
  run_id: string | null;
  run_name: string | null;
  data_source: string;
  warnings: string[];
  request_summary: Record<string, unknown>;
};

export const generationApi = {
  factorGenerationDefaults: (poolId?: string) =>
    apiGet<FactorGenerationDefaults>(
      withQuery("/api/factor-generations/defaults", { pool_id: poolId }),
    ),
  createFactorGeneration: (payload: FactorGenerationRequest) =>
    apiPost<FactorGenerationResponse>("/api/factor-generations", payload),
};
