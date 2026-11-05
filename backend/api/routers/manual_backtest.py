"""HTTP 路由：手动表达式回测提交。"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from schemas import ManualBacktestRequest
from services import manual_backtest_service

router = APIRouter()

@router.post('/api/manual-backtests', status_code=202)
def create_manual_backtest(request: ManualBacktestRequest) -> Dict[str, Any]:
    return manual_backtest_service.create_manual_backtest(request)
