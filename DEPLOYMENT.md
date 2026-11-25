# Deployment Information

## Public URL
https://k5-l3a-day14-nguyenvanhuy-2a202603432.onrender.com

## Platform
**Render** — Web Service, runtime Docker, Root Directory `06-lab-complete` (build từ `06-lab-complete/Dockerfile`), deploy tự động từ nhánh `main` (commit `4ae1a83`). Redis: Render Key Value, kết nối qua Internal URL.

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
| `GET /health` | 200 | **200** `{"status":"ok","version":"1.0.0",...}` |
| `GET /ready` | 200 | **200** `{"ready":true}` (Redis kết nối được) |
| `POST /ask` không có key | 401 | **401** `{"detail":"Missing or invalid API key. Include header: X-API-Key: <key>"}` |
| `POST /ask` có key | 200 | _người làm bài tự chạy với key của mình — điền kết quả_ |

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
| `AGENT_API_KEY` | secret (Render **Generate**) | header `X-API-Key` phải trùng |
| `REDIS_URL` | Internal URL của Render Key Value | state rate limit + chi phí; `/ready` = 200 xác nhận đã kết nối |
| `ENVIRONMENT` | `production` | bật fail-fast khi thiếu key, ẩn `/docs` |
| `RATE_LIMIT_PER_MINUTE` | `10` | mặc định 10 nếu không đặt |
| `DAILY_BUDGET_USD` / `MONTHLY_BUDGET_USD` | `1.0` / `10.0` | cost guard → 402 |
| `PORT` | do Render cấp | `CMD` trong Dockerfile đọc `${PORT:-8000}` |
| `LOG_LEVEL` | `INFO` (mặc định) | |

Health Check Path trên Render: `/health`.

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png) — _trang Deploy của Render (Deploy succeeded / Live, commit `4ae1a83`)_
- [Service running](screenshots/running.png) — `GET /health` trên URL public
- [Test results](screenshots/test.png) — _terminal chạy 4 lệnh tự kiểm ở trên (che key)_
