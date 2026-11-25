"""
Exercise 4.4 — Cost guard dựa trên Redis (budget theo tháng).

Logic:
- Mỗi user có budget $10/tháng.
- Spending được lưu trong Redis, key = budget:{user_id}:{YYYY-MM}.
- Reset tự động đầu tháng: key của tháng mới là key khác; key cũ hết hạn sau 32 ngày.

Khác với lời giải mẫu trong CODE_LAB.md: lời giải mẫu làm GET → kiểm tra → INCRBYFLOAT,
nên hai request song song có thể cùng đọc một giá trị cũ rồi cùng vượt budget.
Ở đây cộng trước bằng INCRBYFLOAT (nguyên tử), nếu vượt thì trừ lại.
"""
import os
from datetime import datetime

import redis

MONTHLY_BUDGET_USD = 10.0
KEY_TTL_SECONDS = 32 * 24 * 3600  # 32 ngày — đủ phủ một tháng

_redis = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)


def check_budget(user_id: str, estimated_cost: float) -> bool:
    """
    Return True nếu còn budget (và ghi nhận chi phí), False nếu vượt.
    """
    month_key = datetime.now().strftime("%Y-%m")
    key = f"budget:{user_id}:{month_key}"

    new_total = float(_redis.incrbyfloat(key, estimated_cost))
    if new_total > MONTHLY_BUDGET_USD:
        # Vượt budget: hoàn lại phần vừa cộng để không tính chi phí của request bị từ chối
        _redis.incrbyfloat(key, -estimated_cost)
        return False

    _redis.expire(key, KEY_TTL_SECONDS)
    return True
