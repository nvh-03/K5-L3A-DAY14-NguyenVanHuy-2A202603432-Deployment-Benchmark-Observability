"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

  • Đọc REDIS_URL từ config.
  • Không ping lúc import: redis.from_url chỉ tạo connection pool, kết nối thật
    được mở khi có lệnh đầu tiên → app vẫn khởi động được khi Redis chưa sẵn sàng.
  • Timeout ngắn để /ready và /ask không bị treo lâu khi Redis chết.
"""
import redis

from app.config import settings

r = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=1.0,
    socket_timeout=1.0,
    health_check_interval=30,
)


def redis_healthy() -> bool:
    """Dùng cho GET /ready: Redis không kết nối được → False."""
    try:
        return bool(r.ping())
    except redis.RedisError:
        return False
