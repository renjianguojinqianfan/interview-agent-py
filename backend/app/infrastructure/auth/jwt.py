"""JWT token 创建与验证工具。

基于 PyJWT，使用 HS256 对称签名。
密钥来源于 settings.secret_key，若为空则禁用 JWT 认证（降级模式）。
"""

from datetime import datetime, timedelta, timezone

import jwt

from app.config.settings import settings

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 小时


def _get_secret() -> str:
    if not settings.secret_key:
        return ""
    return settings.secret_key


def create_access_token(user_id: str, expires_delta: timedelta | None = None) -> str:
    """创建 JWT access token。

    Args:
        user_id: 用户标识
        expires_delta: 过期时间，默认 24 小时

    Returns:
        JWT 字符串。若 secret_key 未配置则返回空字符串。
    """
    secret = _get_secret()
    if not secret:
        return ""

    now = datetime.now(timezone.utc)  # noqa: UP017
    expire = now + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def verify_token(token: str) -> str | None:
    """验证 JWT token 并返回 user_id。

    Args:
        token: JWT 字符串

    Returns:
        user_id（sub 字段）。token 无效或过期时返回 None。
    """
    secret = _get_secret()
    if not secret:
        return None

    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None
