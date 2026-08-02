"""JWT 认证 API 路由。

提供 login 端点获取 access token，以及受保护端点示例。
"""

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.api.responses import Result
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

    当前为简化实现：仅验证密码非空，返回固定 user_id="default"。
    生产环境应接入真实用户系统。
    """
    if not body.password:
        return Result.error(ErrorCode.UNAUTHORIZED, "密码不能为空")

    # 简化：固定 user_id，生产应替换为真实认证逻辑
    user_id = "default"
    token = create_access_token(user_id)
    if not token:
        return Result.error(ErrorCode.INTERNAL_ERROR, "JWT 未配置，请联系管理员")

    return Result.success(data=LoginResponse(access_token=token))


@router.get("/me", response_model=Result[dict[str, str]])
async def me(user_id: str = Depends(get_current_user)) -> Result[dict[str, str]]:
    """获取当前用户信息（需认证）。"""
    return Result.success(data={"user_id": user_id})
