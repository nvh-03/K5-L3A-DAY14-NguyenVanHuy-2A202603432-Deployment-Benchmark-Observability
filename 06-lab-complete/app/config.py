"""
Config — 12-Factor: mọi cấu hình đọc từ biến môi trường (tiêu chí 9).

Không có secret nào trong code. Giá trị mặc định chỉ để chạy local; khi
ENVIRONMENT=production mà thiếu AGENT_API_KEY thì dừng ngay lúc khởi động
(fail fast) thay vì chạy với API mở hoặc khoá cứng.
"""
import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


@dataclass(frozen=True)
class Settings:
    port: int = field(default_factory=lambda: _int("PORT", 8000))
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())

    # Bảo mật — không có giá trị mặc định: thiếu key thì mọi request /ask bị 401
    agent_api_key: str = field(default_factory=lambda: os.getenv("AGENT_API_KEY", ""))

    # Redis dùng chung cho rate limiter và cost guard (state không nằm trong process)
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"))

    # Giới hạn
    rate_limit_per_minute: int = field(default_factory=lambda: _int("RATE_LIMIT_PER_MINUTE", 10))
    daily_budget_usd: float = field(default_factory=lambda: _float("DAILY_BUDGET_USD", 1.0))
    monthly_budget_usd: float = field(default_factory=lambda: _float("MONTHLY_BUDGET_USD", 10.0))

    def validate(self) -> "Settings":
        if self.environment == "production" and not self.agent_api_key:
            raise RuntimeError("AGENT_API_KEY must be set when ENVIRONMENT=production")
        if self.rate_limit_per_minute < 1:
            raise RuntimeError("RATE_LIMIT_PER_MINUTE must be >= 1")
        if self.daily_budget_usd <= 0 or self.monthly_budget_usd <= 0:
            raise RuntimeError("DAILY_BUDGET_USD and MONTHLY_BUDGET_USD must be > 0")
        return self


settings = Settings().validate()
