# Deployment Information

## Public URL
https://k5-l3a-day14-nguyenvanhuy-2a202603432.onrender.com

## Platform
**Render** — Web Service (gói Free), runtime Docker, Root Directory `06-lab-complete` (build từ `06-lab-complete/Dockerfile`), deploy tự động từ nhánh `main` (đang chạy commit `7d2698c`). Redis: Render Key Value, kết nối qua Internal URL.

Log khởi động trên Render (deploy 2026-11-25 17:18 GMT+7):
```
{"ts": "2026-11-25T10:19:04.248+00:00", "lvl": "INFO", "logger": "agent", "event": "startup", "version": "1.0.0", "environment": "production", "rate_limit_per_minute": 10, "daily_budget_usd": 1.0, "monthly_budget_usd": 10.0, "redis_reachable": true}
INFO:     Uvicorn running on http://0.0.0.0:10000 (Press CTRL+C to quit)
```
Render cấp `PORT=10000`; `CMD` của Dockerfile đọc `${PORT:-8000}` nên lắng nghe đúng cổng. Gói Free ngủ khi không có truy cập — request đầu tiên sau khi ngủ có thể mất ~50 s.

## Test Commands

Đặt biến trước khi chạy (không ghi key thật vào file):

```bash
BASE=https://k5-l3a-day14-nguyenvanhuy-2a202603432.onrender.com
AGENT_API_KEY=<key đã đặt trên Render>
```

4 lệnh tự kiểm của CP6 (mỗi lệnh chỉ in mã HTTP):

```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

Kết quả đã chạy (2026-11-25):

| Lệnh | Mong đợi | Kết quả |
|---|---|---|
| `GET /health` | 200 | **200** `{"status":"ok","version":"1.0.0","environment":"production",...}` |
| `GET /ready` | 200 | **200** `{"ready":true}` (Redis kết nối được) |
| `POST /ask` không có key | 401 | **401** `{"detail":"Missing or invalid API key. Include header: X-API-Key: <key>"}` |
| `POST /ask` có key | 200 | _người làm bài tự chạy với key của mình — điền kết quả_ |
| `POST /ask` key sai | 401 | **401** |
| `GET /docs` | 404 (ẩn khi production) | **404** |

### Health Check
```bash
curl https://k5-l3a-day14-nguyenvanhuy-2a202603432.onrender.com/health
# {"status":"ok","version":"1.0.0","environment":"...","uptime_seconds":...}
```

### API Test (with authentication)
```bash
curl -X POST https://k5-l3a-day14-nguyenvanhuy-2a202603432.onrender.com/ask \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
# 200 {"question":"Hello","answer":"...","usage":{"input_tokens":..,"output_tokens":..,"cost_usd":..,"rate_limit_remaining":..}}
```

### Script chấm với URL public
```bash
cd 06-lab-complete
python check_production_ready.py --public-url https://k5-l3a-day14-nguyenvanhuy-2a202603432.onrender.com
#  ✅ Public URL: GET https://k5-l3a-day14-nguyenvanhuy-2a202603432.onrender.com/health → 200
#  Result: 12/12 tiêu chí đạt · 44/44 checks passed
#  🎉 PASS 12/12 — PRODUCTION READY!
```
(Chạy trong container Linux `python:3.11-slim` + Docker CLI, vì trên Windows script không gửi được SIGTERM — xem `MISSION_ANSWERS.md` Part 6.)

## Environment Variables Set

Đặt trong Render → Service → Environment (không có giá trị nào trong code hay git):

| Biến | Giá trị | Ghi chú |
|---|---|---|
| `AGENT_API_KEY` | secret (chuỗi ngẫu nhiên) | header `X-API-Key` phải trùng |
| `REDIS_URL` | Internal URL của Render Key Value | state rate limit + chi phí; `/ready` = 200 xác nhận đã kết nối |
| `ENVIRONMENT` | `production` | bật fail-fast khi thiếu key, ẩn `/docs` |
| `RATE_LIMIT_PER_MINUTE` | `10` | |
| `DAILY_BUDGET_USD` | `1.0` | cost guard → 402 |
| `MONTHLY_BUDGET_USD` | không đặt → mặc định `10.0` | |
| `PORT` | Render tự cấp (`10000`) | `CMD` trong Dockerfile đọc `${PORT:-8000}` |
| `LOG_LEVEL` | không đặt → mặc định `INFO` | |

**Sự cố khi đặt biến:** lần đầu tên biến bị gõ sai thành `AGEN_API_KEY` và `ENVIROMENT`. App không đọc được nên **âm thầm dùng giá trị mặc định**: `/health` báo `"environment":"development"`, `/docs` mở công khai, và `/ask` trả 401 cho cả key đúng (vì app không có key nào). Phát hiện nhờ `/health` trả về `environment`. Sau khi sửa tên (và tạo key mới, vì key cũ đã hiện trong ảnh chụp màn hình) → log khởi động báo `"environment": "production"`.

Health Check Path trên Render: `/health`.

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png) — _trang Deploy của Render (Deploy succeeded / Live, commit `7d2698c`)_
- [Service running](screenshots/running.png) — `GET /health` trên URL public (`"environment":"production"`)
- [Test results](screenshots/test.png) — _terminal chạy 4 lệnh tự kiểm ở trên (che key)_
