"""
Rate limiting (tiêu chí 7) — sliding window log trên Redis sorted set.

  • Mỗi API key tối đa RATE_LIMIT_PER_MINUTE request trong 60 giây.
  • Vượt giới hạn → HTTP 429 kèm Retry-After.
  • State nằm trong Redis → mọi worker / instance dùng chung, còn nguyên sau khi restart agent.

Kiểm tra và ghi nhận nằm trong MỘT Lua script nên nguyên tử: nhiều worker gửi
cùng lúc cũng không lọt quá giới hạn (khác với kiểu GET → kiểm tra → ghi).
Request bị từ chối không được ghi vào window, nên client bị chặn không tự kéo dài thời gian chặn.
"""
import hashlib
import math
import time
import uuid

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_MS = 60_000

_SLIDING_WINDOW = r.register_script("""
local key    = KEYS[1]
local now    = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit  = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  return {0, count, tonumber(oldest[2])}
end
redis.call('ZADD', key, now, ARGV[4])
redis.call('PEXPIRE', key, window)
return {1, count + 1, 0}
""")


def _key_for(api_key: str) -> str:
    # Không lưu API key gốc trong Redis — chỉ lưu dấu băm
    return "ratelimit:" + hashlib.sha256(api_key.encode()).hexdigest()[:24]


def check_rate_limit(key: str) -> dict:
    """Raise 429 nếu vượt giới hạn; trả về thông tin còn lại nếu hợp lệ."""
    limit = settings.rate_limit_per_minute
    now_ms = int(time.time() * 1000)
    try:
        allowed, count, oldest_ms = _SLIDING_WINDOW(
            keys=[_key_for(key)],
            args=[now_ms, WINDOW_MS, limit, f"{now_ms}-{uuid.uuid4().hex}"],
        )
    except redis.RedisError as exc:
        # Không có Redis thì không đếm được → từ chối (fail closed) thay vì mở cửa
        raise HTTPException(status_code=503, detail="Rate limiter unavailable") from exc

    if not allowed:
        retry_after = max(1, math.ceil((int(oldest_ms) + WINDOW_MS - now_ms) / 1000))
        raise HTTPException(
            status_code=429,
            detail={"error": "Rate limit exceeded", "limit_per_minute": limit,
                    "retry_after_seconds": retry_after},
            headers={"Retry-After": str(retry_after),
                     "X-RateLimit-Limit": str(limit),
                     "X-RateLimit-Remaining": "0"},
        )
    return {"limit": limit, "remaining": max(0, limit - int(count))}
