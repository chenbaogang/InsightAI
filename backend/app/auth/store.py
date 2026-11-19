import logging
import threading
import time

from app.config import get_settings

logger = logging.getLogger("insightai.auth")

REVOKED_PREFIX = "insightai:revoked:"
RATE_PREFIX = "insightai:loginrl:"

_client = None
_client_failed_at = 0.0
_mem_revoked: dict[str, float] = {}
_mem_lock = threading.Lock()
_mem_hits: dict[str, list[float]] = {}
_hits_lock = threading.Lock()


def _redis():
    global _client, _client_failed_at
    url = (get_settings().redis_url or "").strip()
    if not url:
        return None
    if _client is not None:
        return _client
    if _client_failed_at and time.time() - _client_failed_at < 60:
        return None
    try:
        import redis

        client = redis.Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2, decode_responses=True)
        client.ping()
        _client = client
        logger.info("登录吊销与限流已接入 Redis")
    except Exception as exc:
        _client_failed_at = time.time()
        logger.warning("Redis 不可用（%s），吊销与限流暂退化为进程内存；60 秒后重试", exc)
    return _client


def revoke(jti: str, exp_at: float) -> None:
    ttl = max(1, int(exp_at - time.time()) + 1)
    r = _redis()
    if r is not None:
        try:
            r.setex(REVOKED_PREFIX + jti, ttl, "1")
            return
        except Exception as exc:
            logger.warning("Redis revoke 失败，退回内存: %s", exc)
    now = time.time()
    with _mem_lock:
        for stale in [k for k, e in _mem_revoked.items() if e < now]:
            _mem_revoked.pop(stale, None)
        _mem_revoked[jti] = exp_at


def is_revoked(jti: str) -> bool:
    r = _redis()
    if r is not None:
        try:
            return bool(r.exists(REVOKED_PREFIX + jti))
        except Exception as exc:
            logger.warning("Redis is_revoked 失败，按未吊销处理: %s", exc)
    with _mem_lock:
        return jti in _mem_revoked


def register_attempt(key: str, limit: int, window: int = 60) -> tuple[bool, int]:
    if limit <= 0:
        return True, 0
    r = _redis()
    if r is not None:
        try:
            k = RATE_PREFIX + key
            pipe = r.pipeline()
            pipe.incr(k)
            pipe.ttl(k)
            count, ttl = pipe.execute()
            if int(ttl) < 0:
                r.expire(k, window)
            if int(count) > limit:
                return False, max(1, int(ttl) if int(ttl) > 0 else window)
            return True, 0
        except Exception as exc:
            logger.warning("Redis 限流失败，退回内存: %s", exc)
    now = time.time()
    with _hits_lock:
        hits = [t for t in _mem_hits.get(key, []) if now - t < window]
        if len(hits) >= limit:
            _mem_hits[key] = hits
            return False, max(1, int(window - (now - hits[0])))
        hits.append(now)
        _mem_hits[key] = hits
        for stale in [k for k, v in _mem_hits.items() if not v or now - v[-1] > window * 2]:
            _mem_hits.pop(stale, None)
        return True, 0
