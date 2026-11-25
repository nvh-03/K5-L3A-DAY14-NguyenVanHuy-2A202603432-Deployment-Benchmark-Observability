"""
Cost guard (tiêu chí 8).

  • Cộng dồn chi phí LLM (tính theo token) vào Redis, theo ngày và theo tháng (UTC).
  • Tổng chi phí của ngày ≥ DAILY_BUDGET_USD, hoặc của tháng ≥ MONTHLY_BUDGET_USD → HTTP 402.
  • Reset tự động: mỗi ngày / tháng là một key riêng (cost:day:2026-11-25, cost:month:2026-11),
    key cũ tự hết hạn — không có biến tổng nào "quên" reset.

Giới hạn đã biết: check_budget và record_cost là hai bước, nên các request đang chạy
song song lúc gần chạm ngưỡng có thể vượt budget một chút (tối đa ≈ số request đồng thời
× chi phí 1 request). Với rate limit theo phút, mức vượt này rất nhỏ.
"""
from datetime import datetime, timezone

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

_DAY_TTL = 2 * 24 * 3600
_MONTH_TTL = 32 * 24 * 3600


def _keys() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return f"cost:day:{now:%Y-%m-%d}", f"cost:month:{now:%Y-%m}"


def estimate_tokens(text: str) -> int:
    """Ước lượng ~4 ký tự / token (mock LLM không trả usage thật)."""
    return max(1, len(text) // 4)


def get_spend() -> dict:
    day_key, month_key = _keys()
    day, month = r.mget(day_key, month_key)
    return {"day_usd": float(day or 0), "month_usd": float(month or 0)}


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    try:
        spend = get_spend()
    except redis.RedisError as exc:
        # Không đọc được chi phí thì không gọi LLM (fail closed — bảo vệ tiền)
        raise HTTPException(status_code=503, detail="Cost guard unavailable") from exc

    if spend["day_usd"] >= settings.daily_budget_usd:
        raise HTTPException(status_code=402, detail={
            "error": "Daily budget exceeded",
            "spent_usd": round(spend["day_usd"], 6),
            "budget_usd": settings.daily_budget_usd,
            "resets": "00:00 UTC",
        })
    if spend["month_usd"] >= settings.monthly_budget_usd:
        raise HTTPException(status_code=402, detail={
            "error": "Monthly budget exceeded",
            "spent_usd": round(spend["month_usd"], 6),
            "budget_usd": settings.monthly_budget_usd,
            "resets": "1st of next month, 00:00 UTC",
        })


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """
    Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request.

    Lỗi Redis (redis.RedisError) được để lan ra cho caller: lúc này LLM đã trả lời,
    caller quyết định vẫn trả câu trả lời nhưng ghi log lỗi.
    """
    cost = input_tokens / 1000 * PRICE_INPUT_PER_1K + output_tokens / 1000 * PRICE_OUTPUT_PER_1K
    day_key, month_key = _keys()
    pipe = r.pipeline(transaction=True)  # MULTI/EXEC: cả 4 lệnh cùng được áp dụng
    pipe.incrbyfloat(day_key, cost)
    pipe.expire(day_key, _DAY_TTL)
    pipe.incrbyfloat(month_key, cost)
    pipe.expire(month_key, _MONTH_TTL)
    pipe.execute()
    return cost
