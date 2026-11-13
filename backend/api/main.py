"""FastAPI 应用装配：只建 app、挂中间件、注册路由。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict

from fastapi import Depends, FastAPI

from api.errors import install_error_handlers
from api.routers import (
    auth,
    composition,
    data,
    factor_backtest,
    factor_generation,
    jobs,
    manual_backtest,
    pools,
    results,
)
from repositories import clickhouse as live_db
from schemas import HealthResponse


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    # 后台预热实时查询缓存（无密码 / 不在公司网络时静默跳过）
    live_db.prewarm()
    yield


app = FastAPI(title="QuantLab Custom Backtester API", version="0.1.0", lifespan=_lifespan)
install_error_handlers(app)


@app.get("/api/health", response_model=HealthResponse)
def health() -> Dict[str, Any]:
    return {"ok": True, "service": "quantlab-backend-api"}


app.include_router(auth.router)
for business_router in (data, pools, jobs, factor_generation, factor_backtest, composition, manual_backtest, results):
    app.include_router(business_router.router, dependencies=[
        Depends(auth.require_user), Depends(auth.require_write_header),
    ])
