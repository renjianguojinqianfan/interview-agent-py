#!/usr/bin/env python3
"""
基础设施连接测试脚本

验证 PostgreSQL、Redis、MinIO 三个服务是否能正常连接。
仅使用 Python 标准库，无需 pip install 任何第三方包。

用法:
    python check_services.py

可通过环境变量覆盖默认连接参数（与 application.yml / docker-compose 中的变量名一致）:
    PostgreSQL: POSTGRES_HOST / POSTGRES_PORT / POSTGRES_DB / POSTGRES_USER / POSTGRES_PASSWORD
    Redis:      REDIS_HOST / REDIS_PORT
    MinIO:      APP_STORAGE_ENDPOINT / APP_STORAGE_ACCESS_KEY / APP_STORAGE_SECRET_KEY / APP_STORAGE_BUCKET
"""

import os
import socket
import sys
import urllib.request
import urllib.error

# 强制 stdout/stderr 使用 UTF-8（解决 Windows GBK 终端编码问题）
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# ── ANSI 颜色 ──────────────────────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

if sys.platform == "win32":
    os.system("")  # 启用 Windows ANSI 转义序列


def _env(key, default=""):
    return os.environ.get(key, default)


def _ok(service, detail):
    print(f"  {GREEN}{BOLD}[✓] {service}{RESET}  {detail}")


def _fail(service, error):
    print(f"  {RED}{BOLD}[✗] {service}{RESET}  {RED}{error}{RESET}")


def _section(title):
    print(f"\n{CYAN}{BOLD}── {title} ──{RESET}")


def _recv_exact(sock, n):
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            break
        data += chunk
    return data


# ══════════════════════════════════════════════════════════════════════════
#  PostgreSQL — 通过协议握手验证连接
# ══════════════════════════════════════════════════════════════════════════
def check_postgresql():
    _section("PostgreSQL")
    host = _env("POSTGRES_HOST", "localhost")
    port = int(_env("POSTGRES_PORT", "5432"))
    database = _env("POSTGRES_DB", "interview_guide")
    user = _env("POSTGRES_USER", "postgres")
    password = _env("POSTGRES_PASSWORD", "password")
    print(f"  主机: {host}:{port}  数据库: {database}  用户: {user}")

    sock = None
    try:
        sock = socket.create_connection((host, port), timeout=5)
        sock.settimeout(5)

        # 构造 StartupMessage（协议版本 3.0）
        params = f"user\x00{user}\x00database\x00{database}\x00\x00".encode("utf-8")
        body = (196608).to_bytes(4, "big") + params
        length = (len(body) + 4).to_bytes(4, "big")
        sock.sendall(length + body)

        # 读取响应
        header = _recv_exact(sock, 5)
        if not header or len(header) < 5:
            raise ConnectionError("服务端未返回数据，可能不是 PostgreSQL")
        msg_type = chr(header[0])
        msg_len = int.from_bytes(header[1:5], "big")
        msg_body = _recv_exact(sock, msg_len - 4) if msg_len > 4 else b""

        if msg_type == "E":
            fields = _parse_pg_error(msg_body)
            raise ConnectionError(
                f"PostgreSQL 拒绝连接: {fields.get('M', '未知错误')} "
                f"(code={fields.get('C', '?')})"
            )

        if msg_type == "R":
            auth_type = int.from_bytes(msg_body[:4], "big") if len(msg_body) >= 4 else -1
            auth_names = {0: "无需认证", 3: "明文密码", 5: "MD5", 10: "SASL/SCRAM"}
            auth_name = auth_names.get(auth_type, f"类型{auth_type}")

            if auth_type == 3:
                # 发送明文密码验证
                payload = password.encode("utf-8") + b"\x00"
                msg = b"p" + (len(payload) + 4).to_bytes(4, "big") + payload
                sock.sendall(msg)
                resp = _recv_exact(sock, 5)
                r_type = chr(resp[0])
                r_len = int.from_bytes(resp[1:5], "big")
                r_body = _recv_exact(sock, r_len - 4) if r_len > 4 else b""
                if r_type == "E":
                    f = _parse_pg_error(r_body)
                    raise ConnectionError(f"密码错误: {f.get('M', '认证失败')} (code={f.get('C', '?')})")
                if r_type == "R" and int.from_bytes(r_body[:4], "big") == 0:
                    _ok("PostgreSQL", f"连接成功（明文认证通过）-> {host}:{port}/{database}")
                    return True
                raise ConnectionError("密码认证失败")

            if auth_type == 0:
                _ok("PostgreSQL", f"连接成功（无需密码）-> {host}:{port}/{database}")
            else:
                _ok("PostgreSQL",
                    f"服务可达（{auth_name}认证，TCP握手成功）-> {host}:{port}/{database}")
            return True

        _ok("PostgreSQL", f"服务可达（响应类型={msg_type}）-> {host}:{port}/{database}")
        return True

    except socket.timeout:
        _fail("PostgreSQL", f"连接超时: {host}:{port}（请确认服务已启动）")
    except ConnectionRefusedError:
        _fail("PostgreSQL", f"连接被拒绝: {host}:{port}（服务可能未启动或端口不对）")
    except ConnectionError as e:
        _fail("PostgreSQL", str(e))
    except Exception as e:
        _fail("PostgreSQL", f"未知错误: {type(e).__name__}: {e}")
    finally:
        if sock:
            try:
                sock.close()
            except Exception:
                pass
    return False


def _parse_pg_error(body):
    fields = {}
    i = 0
    while i < len(body):
        ft = chr(body[i])
        i += 1
        end = body.index(b"\x00", i)
        fields[ft] = body[i:end].decode("utf-8", errors="replace")
        i = end + 1
    return fields


# ══════════════════════════════════════════════════════════════════════════
#  Redis — RESP 协议 PING
# ══════════════════════════════════════════════════════════════════════════
def check_redis():
    _section("Redis")
    host = _env("REDIS_HOST", "localhost")
    port = int(_env("REDIS_PORT", "6379"))
    print(f"  主机: {host}:{port}")

    sock = None
    try:
        sock = socket.create_connection((host, port), timeout=5)
        sock.settimeout(5)
        sock.sendall(b"*1\r\n$4\r\nPING\r\n")
        resp = sock.recv(1024).decode("utf-8", errors="replace").strip()
        if resp == "+PONG":
            _ok("Redis", f"连接成功 -> {host}:{port}  (PING -> PONG)")
            return True
        else:
            _fail("Redis", f"收到异常响应: {resp!r}（期望 '+PONG'）")
    except socket.timeout:
        _fail("Redis", f"连接超时: {host}:{port}（请确认服务已启动）")
    except ConnectionRefusedError:
        _fail("Redis", f"连接被拒绝: {host}:{port}（服务可能未启动或端口不对）")
    except Exception as e:
        _fail("Redis", f"未知错误: {type(e).__name__}: {e}")
    finally:
        if sock:
            try:
                sock.close()
            except Exception:
                pass
    return False


# ══════════════════════════════════════════════════════════════════════════
#  MinIO — HTTP 健康检查 + Bucket 列表验证
# ══════════════════════════════════════════════════════════════════════════
def check_minio():
    _section("MinIO / RustFS (S3 兼容存储)")
    endpoint = _env("APP_STORAGE_ENDPOINT", "http://localhost:9000")
    access_key = _env("APP_STORAGE_ACCESS_KEY", "minioadmin")
    secret_key = _env("APP_STORAGE_SECRET_KEY", "minioadmin")
    bucket = _env("APP_STORAGE_BUCKET", "interview-guide")
    print(f"  端点: {endpoint}")
    print(f"  AccessKey: {access_key}  Bucket: {bucket}")

    # 1) 健康检查（无需认证）
    health_url = endpoint.rstrip("/") + "/minio/health/live"
    try:
        req = urllib.request.Request(health_url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                print(f"  {GREEN}健康检查通过{RESET}  ({health_url} -> 200)")
            else:
                _fail("MinIO", f"健康检查返回 HTTP {resp.status}")
                return False
    except urllib.error.HTTPError as e:
        _fail("MinIO", f"健康检查失败: HTTP {e.code} {e.reason} ({health_url})")
        return False
    except urllib.error.URLError as e:
        reason = str(e.reason)
        if "Connection refused" in reason or "ConnectionRefused" in reason:
            _fail("MinIO", f"连接被拒绝: {endpoint}（服务可能未启动）")
        elif "timed out" in reason.lower():
            _fail("MinIO", f"连接超时: {endpoint}")
        else:
            _fail("MinIO", f"连接失败: {reason}")
        return False
    except Exception as e:
        _fail("MinIO", f"健康检查未知错误: {type(e).__name__}: {e}")
        return False

    # 2) 尝试列出 Bucket（验证凭证是否有效）
    try:
        import hmac
        import hashlib
        from datetime import datetime, timezone

        # 构建 AWS Signature V4 签名（简化版，仅列出 buckets）
        now = datetime.now(timezone.utc)
        date_stamp = now.strftime("%Y%m%d")
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        region = _env("APP_STORAGE_REGION", "us-east-1")

        # 列出所有 bucket: GET /
        canonical_uri = "/"
        canonical_querystring = ""
        host_header = endpoint.replace("http://", "").replace("https://", "").rstrip("/")
        canonical_headers = f"host:{host_header}\nx-amz-date:{amz_date}\n"
        signed_headers = "host;x-amz-date"
        payload_hash = hashlib.sha256(b"").hexdigest()

        canonical_request = (
            f"GET\n{canonical_uri}\n{canonical_querystring}\n"
            f"{canonical_headers}\n{signed_headers}\n{payload_hash}"
        )

        credential_scope = f"{date_stamp}/{region}/s3/aws4_request"
        string_to_sign = (
            f"AWS4-HMAC-SHA256\n{amz_date}\n{credential_scope}\n"
            f"{hashlib.sha256(canonical_request.encode()).hexdigest()}"
        )

        def _sign(key, msg):
            return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

        signing_key = _sign(
            _sign(_sign(_sign(("AWS4" + secret_key).encode("utf-8"), date_stamp), region), "s3"),
            "aws4_request",
        )
        signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

        auth_header = (
            f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )

        req = urllib.request.Request(endpoint.rstrip("/") + "/", method="GET")
        req.add_header("Authorization", auth_header)
        req.add_header("x-amz-date", amz_date)
        req.add_header("x-amz-content-sha256", payload_hash)

        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                body = resp.read().decode("utf-8", errors="replace")
                has_bucket = bucket in body
                if has_bucket:
                    _ok("MinIO", f"连接成功 -> {endpoint}  (Bucket '{bucket}' 存在)")
                else:
                    _ok("MinIO",
                        f"连接成功 -> {endpoint}  (凭证有效，但 Bucket '{bucket}' 尚未创建)")
                return True
            else:
                _fail("MinIO", f"ListBuckets 返回 HTTP {resp.status}")
                return False

    except urllib.error.HTTPError as e:
        if e.code == 403:
            _fail("MinIO", f"凭证无效 (HTTP 403): AccessKey/SecretKey 不正确")
        elif e.code == 401:
            _fail("MinIO", f"认证失败 (HTTP 401): 请检查 AccessKey/SecretKey")
        else:
            body = e.read().decode("utf-8", errors="replace")[:200]
            _fail("MinIO", f"ListBuckets 失败: HTTP {e.code} {e.reason}  {body}")
        return False
    except Exception as e:
        _fail("MinIO", f"凭证验证未知错误: {type(e).__name__}: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════
#  主函数
# ══════════════════════════════════════════════════════════════════════════
def main():
    print(f"\n{BOLD}{'=' * 60}{RESET}")
    print(f"{BOLD}  基础设施连接测试{RESET}")
    print(f"{BOLD}{'=' * 60}{RESET}")
    print(f"  时间: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    results = {
        "PostgreSQL": check_postgresql(),
        "Redis": check_redis(),
        "MinIO": check_minio(),
    }

    # 汇总
    _section("汇总")
    all_ok = True
    for service, ok in results.items():
        status = f"{GREEN}✓ 正常{RESET}" if ok else f"{RED}✗ 失败{RESET}"
        print(f"  {service:12s} {status}")
        if not ok:
            all_ok = False

    print()
    if all_ok:
        print(f"  {GREEN}{BOLD}🎉 所有服务连接正常！{RESET}")
    else:
        failed = [s for s, ok in results.items() if not ok]
        print(f"  {RED}{BOLD}⚠ 以下服务连接失败: {', '.join(failed)}{RESET}")

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
