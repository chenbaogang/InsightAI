
import base64
import hashlib
import hmac
import json
import time


class TokenError(Exception):
    pass


_ALG = "HS256"
_REQUIRED = ("HS256",)


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def encode(payload: dict, secret: str) -> str:
    body = dict(payload)
    now = int(time.time())
    body.setdefault("iat", now)
    header = _b64e(json.dumps({"alg": _ALG, "typ": "JWT"}, separators=(",", ":")).encode("utf-8"))
    claims = _b64e(json.dumps(body, separators=(",", ":")).encode("utf-8"))
    return f"{header}.{claims}.{_signature(header, claims, secret)}"


def _signature(header: str, claims: str, secret: str) -> str:
    signing_input = f"{header}.{claims}".encode("ascii")
    return _b64e(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest())


def decode(token: str, secret: str, *, leeway: int = 30) -> dict:
    if not token:
        raise TokenError("token 为空")
    parts = token.split(".")
    if len(parts) != 3:
        raise TokenError("token 结构不合法")
    header, claims, sig = parts
    try:
        head = json.loads(_b64d(header))
    except (ValueError, UnicodeDecodeError):
        raise TokenError("token 头部不合法")
    if head.get("alg") not in _REQUIRED or head.get("typ") != "JWT":
        raise TokenError("不支持的签名算法")
    if not hmac.compare_digest(sig, _signature(header, claims, secret)):
        raise TokenError("签名校验失败")
    try:
        body = json.loads(_b64d(claims))
    except (ValueError, UnicodeDecodeError):
        raise TokenError("token 内容不合法")
    if not isinstance(body, dict):
        raise TokenError("token 内容不合法")
    now = int(time.time())
    exp = body.get("exp")
    if exp is None:
        raise TokenError("token 缺少过期时间")
    if now - leeway >= int(exp):
        raise TokenError("token 已过期")
    iat = body.get("iat")
    if iat is not None and int(iat) > now + leeway:
        raise TokenError("token 签发时间在未来")
    return body

