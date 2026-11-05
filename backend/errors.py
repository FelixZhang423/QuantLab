"""领域异常：services/repositories 只抛这里定义的异常，不依赖 FastAPI。"""
from __future__ import annotations


class DomainError(Exception):
    status_code = 500

    def __init__(self, detail: str = "") -> None:
        self.detail = str(detail)
        super().__init__(self.detail)


class BadRequestError(DomainError):
    status_code = 400


class ValidationError(DomainError):
    status_code = 422


class NotFoundError(DomainError):
    status_code = 404


class ConflictError(DomainError):
    status_code = 409


class InternalError(DomainError):
    status_code = 500


class UpstreamError(DomainError):
    status_code = 502


class UnavailableError(DomainError):
    status_code = 503


_BY_STATUS = {
    400: BadRequestError,
    404: NotFoundError,
    409: ConflictError,
    422: ValidationError,
    500: InternalError,
    502: UpstreamError,
    503: UnavailableError,
}


def make_error(status_code: int, detail: str = "") -> DomainError:
    """按 HTTP 语义状态码选择异常类；兼容旧代码里的 HTTPException(status_code=...)。"""
    return _BY_STATUS.get(status_code, DomainError)(detail)
