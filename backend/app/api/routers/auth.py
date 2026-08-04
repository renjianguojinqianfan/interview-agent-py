"""JWT 认证 API 路由。

提供 login 端点获取 access token，以及受保护端点示例。
"""

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import DEFAULT_USER_ID, get_current_user
from app.api.responses import Result
from app.config.settings import settings
from app.domain.errors import ErrorCode
from app.infrastructure.auth.jwt import create_access_token

router = APIRouter(prefix="/api/auth", tags=["认证"])


class LoginRequest(BaseModel):
    """登录请求。"""

    username: str
    password: str


class LoginResponse(BaseModel):
    """登录响应。"""

    access_token: str
    token_type: str = "bearer"


@router.post("/login", response_model=Result[LoginResponse])
async def login(body: LoginRequest) -> Result[Any]:
    """登录获取 JWT access token。

    两者均未配置 = 降级无认证，任意账号放行；
    配置了任一凭据则必须与请求用户名密码完全匹配，否则返回 code=401。
    """
    credentials_configured = bool(settings.auth_admin_username or settings.auth_admin_password)
    if credentials_configured and (
        not settings.auth_admin_username
        or not settings.auth_admin_password
        or body.username != settings.auth_admin_username
        or body.password != settings.auth_admin_password
    ):
        return Result.error(ErrorCode.UNAUTHORIZED, "用户名或密码错误")

    user_id = DEFAULT_USER_ID
    token = create_access_token(user_id)
    if not token:
        return Result.error(ErrorCode.INTERNAL_ERROR, "JWT 未配置，请联系管理员")

    return Result.success(data=LoginResponse(access_token=token))


@router.get("/me", response_model=Result[dict[str, str]])
async def me(user_id: str = Depends(get_current_user)) -> Result[dict[str, str]]:
    """获取当前用户信息（需认证）。"""
    return Result.success(data={"user_id": user_id})
