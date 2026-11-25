"""
Production AI Agent — Part 6 Final Project.

Chạy:  uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2

Endpoint:
  GET  /health  liveness  — luôn 200 khi process còn chạy (không phụ thuộc Redis)
  GET  /ready   readiness — 200 khi Redis kết nối được và không đang tắt; ngược lại 503
  POST /ask     X-API-Key → rate limit (429) → cost guard (402) → mock LLM

Graceful shutdown (tiêu chí 11): không tự đăng ký handler SIGTERM. uvicorn bắt SIGTERM,
ngừng nhận kết nối mới, chờ request đang chạy xong rồi mới gọi phần shutdown của lifespan.
/ask là hàm `def` (không phải `async def`) nên lời gọi LLM blocking chạy trong threadpool,
không chặn event loop — /health vẫn trả lời ngay cả khi đang có nhiều request /ask.
"""
import time
import uuid
from contextlib import asynccontextmanager

import redis
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, estimate_tokens, record_cost
from app.logging_setup import get_logger
from app.rate_limiter import check_rate_limit
from app.redis_client import r, redis_healthy
from utils.mock_llm import ask as llm_ask

APP_VERSION = "1.0.0"
logger = get_logger(settings.log_level)

START_TIME = time.time()
_state = {"shutting_down": False}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup: không chặn khởi động nếu Redis chưa sẵn sàng (/ready sẽ báo 503) ──
    logger.info("startup", extra={
        "version": APP_VERSION,
        "environment": settings.environment,
        "rate_limit_per_minute": settings.rate_limit_per_minute,
        "daily_budget_usd": settings.daily_budget_usd,
        "monthly_budget_usd": settings.monthly_budget_usd,
        "redis_reachable": redis_healthy(),
    })
    if not settings.agent_api_key:
        logger.warning("agent_api_key_missing", extra={"effect": "every /ask request will get 401"})

    yield

    # ── Shutdown: uvicorn đã chờ xong request đang chạy trước khi tới đây ──
    _state["shutting_down"] = True
    logger.info("shutdown", extra={"uptime_seconds": round(time.time() - START_TIME, 1)})
    r.connection_pool.disconnect()


app = FastAPI(
    title="Production AI Agent",
    version=APP_VERSION,
    lifespan=lifespan,
    docs_url=None if settings.environment == "production" else "/docs",
    redoc_url=None,
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Mỗi request một dòng log JSON; gắn X-Request-ID để dò log theo request."""
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("request_failed", extra={
            "request_id": request_id, "method": request.method, "path": request.url.path})
        raise
    response.headers["X-Request-ID"] = request_id
    if request.url.path not in ("/health", "/ready"):  # probe gọi liên tục — không làm nhiễu log
        logger.info("request", extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "ms": round((time.perf_counter() - started) * 1000, 1),
        })
    return response


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=128)


@app.get("/health")
def health():
    """Liveness: process còn sống là 200 — cố ý KHÔNG kiểm tra Redis (Redis chết thì restart agent cũng vô ích)."""
    return {
        "status": "ok",
        "version": APP_VERSION,
        "environment": settings.environment,
        "uptime_seconds": round(time.time() - START_TIME, 1),
    }


@app.get("/ready")
def ready():
    """Readiness: load balancer chỉ gửi traffic khi Redis dùng được và instance không đang tắt."""
    if _state["shutting_down"]:
        return JSONResponse(status_code=503, content={"ready": False, "reason": "shutting down"})
    if not redis_healthy():
        return JSONResponse(status_code=503, content={"ready": False, "reason": "redis unreachable"})
    return {"ready": True}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    rate = check_rate_limit(api_key)  # 429 nếu vượt giới hạn
    check_budget()                    # 402 nếu hết budget — kiểm tra TRƯỚC khi tốn tiền gọi LLM

    answer = llm_ask(body.question)

    input_tokens, output_tokens = estimate_tokens(body.question), estimate_tokens(answer)
    try:
        cost = record_cost(input_tokens, output_tokens)
    except redis.RedisError:
        # LLM đã trả lời: vẫn trả kết quả cho user, nhưng để lại dấu vết để đối soát chi phí
        cost = None
        logger.error("cost_record_failed", extra={"input_tokens": input_tokens, "output_tokens": output_tokens})

    return {
        "question": body.question,
        "answer": answer,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost, 8) if cost is not None else None,
            "rate_limit_remaining": rate["remaining"],
        },
    }
