"""FastAPI 应用装配：只建 app、挂中间件、注册路由。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.errors import install_error_handlers
from api.routers import (
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
# 本地开发：前端 dev server 通过 vite proxy 访问，这里放开跨域方便直接调试
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)
install_error_handlers(app)


@app.get("/api/health", response_model=HealthResponse)
def health() -> Dict[str, Any]:
    return {"ok": True, "service": "quantlab-backend-api"}


app.include_router(data.router)
app.include_router(pools.router)
app.include_router(jobs.router)
app.include_router(factor_generation.router)
app.include_router(factor_backtest.router)
app.include_router(manual_backtest.router)
app.include_router(results.router)
