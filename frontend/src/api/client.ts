/**
 * 兼容 barrel：feature API 已拆到 src/features/<feature>/api.ts。
 * 新代码优先从 feature 内导入，这里只保留既有调用路径。
 */
export * from "../shared/api/base";
export * from "../features/data-browser/api";
export * from "../features/pools/api";
export * from "../features/results/api";
export * from "../features/factor-backtest/api";
export * from "../features/factor-generation/api";
export * from "../features/composition/api";
export * from "../features/manual-backtest/api";

import { fetchJob } from "../shared/api/base";
import { dataApi } from "../features/data-browser/api";
import { poolApi } from "../features/pools/api";
import { resultApi } from "../features/results/api";
import { factorApi } from "../features/factor-backtest/api";
import { generationApi } from "../features/factor-generation/api";
import { compositionApi } from "../features/composition/api";
import { manualApi } from "../features/manual-backtest/api";

export const api = {
  ...dataApi,
  ...poolApi,
  job: fetchJob,
  ...resultApi,
  ...factorApi,
  ...generationApi,
  ...compositionApi,
  ...manualApi,
};
