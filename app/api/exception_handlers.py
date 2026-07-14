import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.errors import BusinessException, ErrorCode
from app.api.responses import Result

logger = logging.getLogger(__name__)

_HTTP_STATUS_TO_ERROR: dict[int, ErrorCode] = {
    400: ErrorCode.BAD_REQUEST,
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
}


async def business_exception_handler(request: Request, exc: BusinessException) -> JSONResponse:
    result = Result.error(exc.error_code, exc.message)
    return JSONResponse(status_code=200, content=result.model_dump())


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    error_code = _HTTP_STATUS_TO_ERROR.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
    result = Result.error(error_code, str(exc.detail))
    return JSONResponse(status_code=200, content=result.model_dump())


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    result = Result.error(ErrorCode.BAD_REQUEST, "请求参数错误")
    return JSONResponse(status_code=200, content=result.model_dump())


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled exception", exc_info=exc)
    result = Result.error(ErrorCode.INTERNAL_ERROR)
    return JSONResponse(status_code=200, content=result.model_dump())


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(BusinessException, business_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, generic_exception_handler)
