"""Structured error contract.

`{ error_code, message, retryable }` — never a bare HTTP 500
(02_Architecture/04_ML_Service.md §4). The gateway branches on `retryable` to
decide between retry and fallback, which it cannot do from a status code alone.
"""

from fastapi import Request
from fastapi.responses import JSONResponse


class MlError(Exception):
    def __init__(
        self,
        error_code: str,
        message: str,
        status_code: int = 400,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable


async def ml_error_handler(_: Request, exc: MlError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error_code": exc.error_code, "message": exc.message, "retryable": exc.retryable},
    )


async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    """Last resort: still the structured shape, still no internals leaked."""
    return JSONResponse(
        status_code=500,
        content={
            "error_code": "internal_error",
            "message": type(exc).__name__,
            "retryable": True,
        },
    )
