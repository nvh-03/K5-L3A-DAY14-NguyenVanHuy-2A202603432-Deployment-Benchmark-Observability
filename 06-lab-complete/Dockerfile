# ============================================================
# Production Dockerfile — multi-stage (tiêu chí 1)
#   Stage builder : cài dependencies vào virtualenv /opt/venv
#   Stage runtime : chỉ copy venv + code, chạy bằng user non-root
# Build: docker build -t agent .      (context là thư mục 06-lab-complete)
# ============================================================

# ── Stage 1: builder ─────────────────────────────────────────
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
# Copy requirements trước để layer cài đặt được cache khi chỉ sửa code
COPY requirements.txt .
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install -r requirements.txt

# ── Stage 2: runtime ─────────────────────────────────────────
FROM python:3.11-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    WEB_CONCURRENCY=2

RUN groupadd --system agent \
 && useradd --system --gid agent --home-dir /app --shell /usr/sbin/nologin agent

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=agent:agent app/ ./app/
COPY --chown=agent:agent utils/ ./utils/

USER agent

EXPOSE 8000

# Liveness cho Docker / Compose — gọi /health theo đúng PORT đang dùng
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request as u; u.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '8000'), timeout=4)" || exit 1

# 1) `python -c "import app.config"`: kiểm tra cấu hình TRƯỚC khi chạy uvicorn. Với --workers > 1,
#    process cha của uvicorn không import app; nếu config sai, worker crash và uvicorn khởi động lại
#    worker mãi mãi (container treo, không thoát). Kiểm tra trước → config sai thì container thoát ngay.
# 2) `exec` để uvicorn là PID 1 và nhận SIGTERM trực tiếp khi `docker stop`.
# ${PORT:-8000}: Railway/Render cấp PORT qua biến môi trường.
# --timeout-graceful-shutdown 8: chờ request đang chạy tối đa 8 s, nhỏ hơn 10 s của `docker stop`.
# --no-access-log: app đã tự ghi log request dạng JSON.
CMD ["sh", "-c", "python -c 'import app.config' && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-2} --timeout-graceful-shutdown 8 --no-access-log"]
