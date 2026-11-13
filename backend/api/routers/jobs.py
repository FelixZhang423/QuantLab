"""HTTP 路由：后台任务状态查询。"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from services import job_service

router = APIRouter()

@router.get('/api/jobs')
def list_jobs() -> list[Dict[str, Any]]:
    return job_service.list_jobs()


@router.get('/api/jobs/{job_id}')
def get_job(job_id: str) -> Dict[str, Any]:
    return job_service.get_job(job_id)
