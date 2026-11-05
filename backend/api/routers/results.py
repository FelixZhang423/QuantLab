"""HTTP 路由：回测结果列表、详情与文件下载。"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from schemas import ResultsResponse
from services import result_service

router = APIRouter()

@router.get('/api/results', response_model=ResultsResponse)
def get_results() -> Dict[str, Any]:
    return result_service.get_results()

@router.get('/api/results/detail')
def get_result_by_key(run_key: str=Query(..., description='结果相对路径，如 factor/pool/run/backtest_id/factor_xxx')) -> Dict[str, Any]:
    return result_service.get_result_by_key(run_key)

@router.get('/api/results/file')
def download_result_file_by_key(run_key: str=Query(..., description='结果相对路径'), file_name: str=Query(..., description='manifest 中列出的文件名')) -> FileResponse:
    file_path = result_service.download_result_file_by_key(run_key, file_name)
    return FileResponse(file_path, filename=file_name)

@router.get('/api/results/{run_name}')
def get_result(run_name: str) -> Dict[str, Any]:
    return result_service.get_result(run_name)

@router.get('/api/results/{run_name}/files/{file_name}')
def download_result_file(run_name: str, file_name: str) -> FileResponse:
    file_path = result_service.download_result_file(run_name, file_name)
    return FileResponse(file_path, filename=file_name)
