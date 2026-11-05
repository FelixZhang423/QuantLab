"""HTTP 路由：因子运行与批量因子回测查询/提交。"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from schemas import FactorBacktestRequest
from services import factor_backtest_service

router = APIRouter()

@router.get('/api/factor-runs')
def get_factor_runs(pool_id: Optional[str]=Query(None, description='按股票池过滤'), limit: int=Query(100, ge=1, le=500, description='返回条数上限')) -> Dict[str, Any]:
    return factor_backtest_service.get_factor_runs(pool_id, limit)

@router.get('/api/factor-runs/{run_id}')
def get_factor_run(run_id: str) -> Dict[str, Any]:
    return factor_backtest_service.get_factor_run(run_id)

@router.post('/api/factor-backtests', status_code=202)
def create_factor_backtest(request: FactorBacktestRequest) -> Dict[str, Any]:
    return factor_backtest_service.create_factor_backtest(request)

@router.get('/api/factor-backtests')
def get_factor_backtests(factor_run_id: str=Query(..., description='因子运行目录名'), pool_id: Optional[str]=Query(None, description='可选：校验股票池')) -> Dict[str, Any]:
    return factor_backtest_service.get_factor_backtests(factor_run_id, pool_id)

@router.get('/api/factor-backtests/{backtest_id}')
def get_factor_backtest(backtest_id: str, factor_run_id: str=Query(..., description='因子运行目录名'), pool_id: Optional[str]=Query(None, description='可选：校验股票池')) -> Dict[str, Any]:
    return factor_backtest_service.get_factor_backtest(backtest_id, factor_run_id, pool_id)

@router.get('/api/factor-backtests/{backtest_id}/files/{file_name}')
def download_factor_backtest_file(backtest_id: str, file_name: str, factor_run_id: str=Query(..., description='因子运行目录名'), pool_id: Optional[str]=Query(None, description='可选：校验股票池')) -> FileResponse:
    file_path = factor_backtest_service.download_factor_backtest_file(backtest_id, file_name, factor_run_id, pool_id)
    return FileResponse(file_path, filename=file_name)
