# Day 14 Lab — Mission Answers

> Môi trường: Windows 11, Python 3.11.9, Docker Desktop 29.9.2 (Docker Engine 29.9.2), mock LLM (không có API key).
> Mọi output dưới đây lấy từ lệnh chạy trên máy này trong phiên làm bài.

---

## Part 1: Localhost vs Production (CP1)

### Exercise 1.1: Anti-patterns found (`01-localhost-vs-production/develop/app.py`)

1. **Secret hardcode** (dòng 17–18): `OPENAI_API_KEY` và `DATABASE_URL` (có password `password123`) viết thẳng trong code → push lên Git là lộ.
2. **Log ra secret** (dòng 34): `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` in API key ra stdout/log.
3. **Debug mode trong production** (dòng 21, 53): `DEBUG = True` và `reload=True` trong `uvicorn.run`.
4. **Host và port cứng** (dòng 51–52): `host="localhost"`, `port=8000`. Không nhận kết nối từ bên ngoài container/cloud và không đọc biến `PORT` mà platform inject. Đã kiểm chứng (xem Exercise 1.3, thử nghiệm A).
5. **Không có health check** (dòng 42–43, comment tự thừa nhận): platform không biết agent đã chết để restart.
6. **`print()` thay cho logging có cấu trúc** (dòng 33, 38): không có level, không parse được bởi log aggregator.
7. **Không có config management** (dòng 20–22): mọi giá trị nằm trong code, đổi môi trường phải sửa code.
8. **Không có lifecycle / graceful shutdown**: không có `lifespan`, không xử lý SIGTERM; request đang chạy bị cắt khi tắt.

Ngoài ra, phát hiện khi chạy: endpoint `/ask` nhận `question` làm **query param** (`def ask_agent(question: str)`), nên lệnh curl gửi JSON body trong đề bài bị lỗi (xem Exercise 1.2).

### Exercise 1.2: Chạy basic version

Chạy `python app.py` trong `01-localhost-vs-production/develop/`, port 8000.

Lệnh trong đề (JSON body):
```
$ curl -i http://localhost:8000/ask -X POST -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 422 Unprocessable Entity
{"detail":[{"type":"missing","loc":["query","question"],"msg":"Field required","input":null}]}
```

Gọi đúng contract của code (query param):
```
$ curl -X POST "http://localhost:8000/ask?question=Hello"
HTTP 200
{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

`GET /health` trả 404 (không có endpoint).

**Quan sát:** app chạy được nhưng không production-ready: API contract không khớp tài liệu, không có health check, log lộ key.

### Exercise 1.3: So sánh develop vs production

Chạy `production/` với `cp .env.example .env` và `PORT=8001` (xem ghi chú bên dưới).

| Feature | Basic (develop) | Advanced (production) | Tại sao quan trọng? |
|---------|-----------------|------------------------|---------------------|
| Config | Hardcode trong code | `config.py` đọc `os.getenv(...)` có giá trị mặc định | Đổi môi trường (dev/staging/prod) không cần sửa code; secret không nằm trong Git |
| Secrets | Key và DB password trong code | Chỉ đọc từ env (`AGENT_API_KEY` bắt buộc khi `ENVIRONMENT=production`) | Secret trong code là lộ ngay khi push; fail-fast nếu thiếu config |
| Health check | Không có | `/health` (liveness, trả uptime) và `/ready` (readiness, 503 trước khi startup xong) | Platform biết restart container khi chết; load balancer chỉ route traffic vào instance đã sẵn sàng |
| Logging | `print()`, log cả secret | `logging` + format JSON trong code, không log secret | Log có cấu trúc để tìm kiếm/cảnh báo; không rò rỉ bí mật |
| Port / host | `localhost:8000` cứng | `HOST=0.0.0.0`, `PORT` từ env | Container và cloud cần bind `0.0.0.0` và port do platform cấp |
| Debug / reload | `DEBUG=True`, `reload=True` cố định | `DEBUG` đọc từ env, mặc định `false` | Reload và debug mode làm chậm và lộ thông tin khi chạy thật |
| Shutdown | Đột ngột | `lifespan` đánh dấu `is_ready=False` khi tắt | Cho request đang chạy hoàn thành (xem ghi chú) |

**Kết quả gọi production (đã chạy):**
```
GET  /health  → 200 {"status":"ok","uptime_seconds":5.7,"version":"1.0.0",...}
GET  /ready   → 200 {"ready":true}
POST /ask (JSON body) → 200 {"question":"Hello","answer":"...","model":"gpt-4o-mini"}
POST /ask (question="") → 422 {"detail":"question field is required"}
```

### Kiểm chứng bằng container

Windows không gửi được SIGTERM và không giống môi trường deploy, nên tôi chạy code trong container `python:3.11-slim` (Docker 29.9.2). Code trong repo không bị sửa; các thử nghiệm cần sửa code đều chạy trên bản copy ngoài repo.

**A. `host="localhost"` của bản develop** — chạy `develop/app.py` trong container, publish `-p 8010:8000`:
```
gọi từ BÊN TRONG container:  GET http://localhost:8000/  → 200
gọi từ máy host:             curl http://localhost:8010/  → không có response (curl exit 52: empty reply)
socket đang listen (/proc/net/tcp): 0100007F:1F40  = 127.0.0.1:8000
```
App chỉ nghe trên loopback của container, nên traffic chuyển vào qua port mapping (hoặc từ load balancer của cloud) không tới được app. Bản production bind `0.0.0.0` nên gọi được bình thường.

**B. `.env` không được đọc** — bản copy với `.env` đặt `APP_NAME=Name-From-Dotenv`, `APP_VERSION=9.9.9-from-dotenv`:
```
chỉ có file .env trong thư mục   → GET / {"app":"AI Agent","version":"1.0.0",...}               ← giá trị mặc định
truyền bằng docker --env-file .env → GET / {"app":"Name-From-Dotenv","version":"9.9.9-from-dotenv",...}
```
`config.py` chỉ dùng `os.getenv`, không gọi `load_dotenv` (dù `requirements.txt` có `python-dotenv`). Bước `cp .env.example .env` trong đề không có tác dụng; giá trị phải được đưa vào biến môi trường (shell, `--env-file`, hoặc dashboard của platform).

**C. Graceful shutdown của bản production.** Gửi 20 request `/ask` đồng thời, tắt server khi đã có đủ 20 kết nối mở và chưa request nào xong, rồi so sánh `docker stop -t 10` (SIGTERM, 10 s trước khi SIGKILL) với `docker kill` (SIGKILL). Để có request "đang chạy" khi tắt, hai bản copy đều đặt mock delay 3 s.

| | Code gốc (`async def` gọi `ask()` blocking) | Bản copy: `await run_in_threadpool(ask, question)` |
|---|---|---|
| `docker stop` (SIGTERM) | 3/20 OK; tắt mất 10,8 s; **exit 137** | **20/20 OK**; tắt mất 2,7 s; exit 0 |
| `docker kill` (SIGKILL) | 0/20 OK | 0/20 OK |

Với delay gốc 0,1 s, 20 request đồng thời mất 2,51 s, tức khoảng 20 × 0,125 s: các request bị xử lý **tuần tự**.

Kết luận:
- **SIGKILL luôn cắt ngang request đang chạy (0/20).** SIGTERM với code xử lý đúng thì không mất request nào (20/20). Đây là lý do cần graceful shutdown.
- **`handle_sigterm` của app không tham gia.** Hàm này chỉ ghi log, không thoát. Nếu nó thật sự giữ SIGTERM, `docker stop` luôn phải chờ đủ 10 s rồi SIGKILL. Thực tế bản threadpool tắt sau 2,7 s với exit 0, và một lần chạy với delay 0,1 s tắt sau 0,8 s với exit 0. Nghĩa là uvicorn đã thay handler này bằng handler riêng; phần graceful shutdown thực sự do uvicorn làm.
- **Code gốc vẫn mất 17/20 request khi nhận SIGTERM.** `async def ask_agent` gọi hàm blocking `ask()` (dùng `time.sleep`) nên chặn event loop, request phải xếp hàng. Uvicorn lại chạy không có `timeout_graceful_shutdown` nên chờ cả hàng đợi, vượt 10 s của Docker và bị SIGKILL (exit 137). Ở lần này log không có dòng `Shutting down`; tôi chưa rõ lý do.
- **Cách sửa:** chạy hàm blocking trong threadpool (`def` hoặc `run_in_threadpool`/`asyncio.to_thread`), và đặt `timeout_graceful_shutdown` nhỏ hơn thời gian chờ của platform.
- **Log shutdown không hiện:** các dòng `"Agent shutting down gracefully..."` trong lifespan không xuất hiện, do lỗi logging nêu dưới đây.

### Ghi chú — lỗi khác phát hiện khi chạy thật

- **Log JSON không hoạt động.** `config.py` gọi `logging.warning(...)` lúc import, khiến root logger được cấu hình mặc định trước. Khi `app.py` gọi `logging.basicConfig(format=...)` thì nó là no-op, và các `logger.info(...)` (startup, `agent_request`, shutdown, ...) bị bỏ im lặng. Log thực tế chỉ còn dòng `WARNING:root:...` và log của uvicorn, không có dòng JSON nào. Sửa: gọi `basicConfig` trước khi import `config`, hoặc không log warning ở import time.

---

## Part 2: Docker (CP2)

### Exercise 2.1: Dockerfile questions (`02-docker/develop/Dockerfile`)

1. **Base image:** `python:3.11` — bản Python đầy đủ (full Debian), image khoảng 1 GB+.
2. **Working directory:** `/app` (`WORKDIR /app`). Mọi lệnh `COPY`, `RUN`, `CMD` sau đó chạy trong thư mục này.
3. **Vì sao `COPY requirements.txt` trước:** Docker cache theo từng layer. Khi `requirements.txt` không đổi, layer `pip install` được lấy từ cache. Nếu copy cả source trước, mọi lần sửa `app.py` đều chạy lại `pip install`.
4. **CMD vs ENTRYPOINT:** `ENTRYPOINT` cố định executable; `CMD` là lệnh/tham số mặc định và bị thay thế khi `docker run <image> <args>`. Dockerfile này dùng `CMD ["python", "app.py"]`, nên `docker run my-agent:develop bash` sẽ thay thế hoàn toàn lệnh chạy app.

### Exercise 2.2: Build và run

```
$ docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .    # chạy từ gốc repo
$ docker run -d --name agent-dev -p 8000:8000 my-agent:develop
$ curl http://localhost:8000/health
{"status":"ok","uptime_seconds":2.6,"container":true}
$ curl -X POST "http://localhost:8000/ask?question=What%20is%20Docker%3F"
HTTP 200  {"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

Lưu ý: `/ask` trong `02-docker/develop/app.py` cũng nhận `question` qua query param, nên lệnh curl JSON body của đề trả 422 (giống Part 1).

Image size:
```
$ docker images my-agent:develop
my-agent:develop   1.67GB
```

### Exercise 2.3: Multi-stage build (`02-docker/production/Dockerfile`)

- **Stage 1 `builder`** (`python:3.11-slim`): cài `gcc`, `libpq-dev`, rồi `pip install --user` vào `/root/.local`. Stage này chỉ để build, không deploy.
- **Stage 2 `runtime`** (`python:3.11-slim` mới, không kế thừa stage 1): tạo user không phải root `appuser`, `COPY --from=builder /root/.local` và chỉ copy `main.py` + `utils/`. `gcc`, apt cache và file build trung gian không có trong image cuối.

Vì sao nhỏ hơn: image cuối không chứa compiler, package manager cache hay bước build. Để biết phần nào do base slim, phần nào do multi-stage, tôi build thêm 2 biến thể single-stage trên base slim (Dockerfile để ngoài repo, context là gốc repo):

| Image | Cách build | Byte | Ghi chú |
|---|---|---|---|
| `my-agent:develop` | `python:3.11`, single-stage | 1 667 771 534 | base full có layer build-deps 696 MB, git/svn 202 MB |
| `slim-gcc-single` | `python:3.11-slim` + gcc/libpq-dev, single-stage (giống stage `builder` nhưng chạy app luôn) | 559 269 717 | layer gcc + libpq-dev: 224 MB |
| `slim-single` | `python:3.11-slim`, single-stage, không cài gcc | 256 325 691 | |
| `my-agent:advanced` | `python:3.11-slim`, multi-stage | 239 819 483 | |

Trong tổng 1 427 952 051 byte (≈ 1 428 MB) giảm được:
- **Đổi base `python:3.11` → `python:3.11-slim`:** giảm 1 108,5 MB, khoảng **77,6%**.
- **Multi-stage** (so với slim + gcc single-stage): giảm thêm 319,4 MB, khoảng **22,4%**, chủ yếu do không mang layer gcc/libpq-dev 224 MB sang image cuối.
- So với bản slim không cài gcc, multi-stage chỉ nhỏ hơn 16,5 MB. Với `requirements.txt` hiện tại (fastapi, uvicorn) thì không cần gcc; lợi ích của multi-stage lớn khi có package phải compile (như `psycopg2` cần `libpq-dev`).

(Số liệu từ `docker image inspect`; kích thước từng layer từ `docker history`.)

Build và so sánh (đo bằng `docker image inspect`, đơn vị byte):
```
$ docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .    # từ gốc repo
$ docker images
my-agent:develop    1.67GB   (1 667 771 534 bytes)
my-agent:advanced   240MB    (239 819 483 bytes)
```

| | Kích thước | So với develop |
|---|---|---|
| Develop (`python:3.11`, single-stage) | 1 667 771 534 B ≈ 1 667.8 MB | — |
| Production (`python:3.11-slim`, multi-stage) | 239 819 483 B ≈ 239.8 MB | giảm **85.6%** |

Kiểm tra runtime: `docker exec agent-adv whoami` → `appuser`; `docker inspect` → `health=healthy`.

Ghi chú: lệnh trong đề (`cd 02-docker/production && docker build -t my-agent:advanced .`) **bị lỗi**, không tạo được image:
```
ERROR: ... "/02-docker/production/main.py": not found
ERROR: ... "/02-docker/production/requirements.txt": not found
ERROR: failed to build: ... "/utils/mock_llm.py": not found
exit=1
```
Các `COPY` trong Dockerfile dùng đường dẫn tính từ gốc repo, nên phải build từ gốc với `-f 02-docker/production/Dockerfile` (như comment cuối Dockerfile).

### Exercise 2.4: Docker Compose stack (`02-docker/production/docker-compose.yml`)

Cần tạo `02-docker/production/.env.local` (file này nằm trong `.gitignore`; Compose báo lỗi nếu thiếu). Chạy với project name riêng:

```
$ docker compose -p k5-day14-docker -f 02-docker/production/docker-compose.yml up -d --build
NAME                       SERVICE   STATUS                    PORTS
k5-day14-docker-agent-1    agent     Up (healthy)              8000/tcp
k5-day14-docker-nginx-1    nginx     Up                        0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
k5-day14-docker-qdrant-1   qdrant    Up (healthy)              6333-6334/tcp
k5-day14-docker-redis-1    redis     Up (healthy)              6379/tcp
```

Sơ đồ service:

```
 Client
   │  HTTP :80
   ▼
 ┌────────┐  proxy_pass agent:8000   ┌────────────┐
 │ nginx  │ ───────────────────────► │ agent (1)  │
 └────────┘  (network "internal")    └────────────┘
                                       │         │
                       depends_on,     │         │   depends_on (healthy)
                       healthy         ▼         ▼
                                  ┌────────┐  ┌────────┐
                                  │ redis  │  │ qdrant │
                                  └────────┘  └────────┘
```

Ghi chú sơ đồ:
- Chỉ `nginx` publish port ra máy host (80). Agent và redis/qdrant chỉ đi trong network `internal`.
- `agent` đợi `redis` và `qdrant` healthy (`depends_on: condition: service_healthy`), nhưng `main.py` không import redis hay gọi `QDRANT_URL`. Hiện tại hai service này chưa được agent dùng.

Kết quả test qua Nginx:
```
$ curl -i http://localhost/health
HTTP/1.1 200 OK
Server: nginx
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block
{"status":"ok","uptime_seconds":27.4,"version":"2.0.0","timestamp":"..."}

$ curl -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question":"Explain microservices"}'
HTTP 200  {"answer":"Đây là câu trả lời từ AI agent (mock). ..."}
```

**Rate limit của Nginx** (`limit_req zone=api_limit` 10 request/giây/IP, `burst=20 nodelay`; `/health` không bị giới hạn). Bắn 40 request **cùng lúc** từ một container trong network `internal` (Python thread + barrier):
```
POST /ask   x40: {200: 21, 429: 19} in 1.41s | 429 body: {"error":"Too many requests","retry_after":1}
GET /health x40: {200: 40}          in 0.10s
nginx log: 19 dòng "limiting requests, excess: ... by zone "api_limit""
```
21 = 20 (burst) + 1 request trong rate. Gửi 40 request bằng `curl` song song từ Windows thì cả 40 đều 200, vì mỗi tiến trình `curl.exe` khởi động chậm nên request bị dàn trải và vẫn nằm trong giới hạn. Muốn thấy 429 phải bắn thật sự cùng lúc.

**Debug container (Checkpoint 2):**
```
$ docker compose -p k5-day14-docker -f 02-docker/production/docker-compose.yml logs --tail 4 agent
INFO:     172.19.0.5:33554 - "GET /health HTTP/1.1" 200 OK          ← nginx gọi /health
$ docker compose ... exec agent sh -c 'whoami'                     → appuser
$ docker compose ... exec agent python -c "...urlopen('http://localhost:8000/health')..."  → 200
$ docker inspect k5-day14-docker-agent-1 --format '{{.State.Health.Status}}'          → healthy (failing_streak=0)
```
Image slim không có `ps`/`curl`, nên kiểm tra bên trong container bằng `python -c`.

Đã dọn stack bằng `docker compose -p k5-day14-docker ... down -v`.

**Ghi chú khác:** `docker-compose.yml` có `version: "3.9"` đã lỗi thời (Compose cảnh báo và bỏ qua); port 443 được map nhưng Nginx không listen 443 và chưa có cert.

---

## Part 3: Cloud Deployment (CP6)

### Exercise 3.1 / 3.2: Deploy lên Railway hoặc Render

Nền tảng chính: **Render** (Exercise 3.2). Deploy chính agent Part 6 (`06-lab-complete/`, runtime Docker, Root Directory `06-lab-complete`), không deploy app mẫu `03-cloud-deployment/`. Chi tiết: [`DEPLOYMENT.md`](DEPLOYMENT.md).

- URL: https://k5-l3a-day14-nguyenvanhuy-2a202603432.onrender.com
- Screenshot: [`screenshots/running.png`](screenshots/running.png) (`GET /health` trên URL public); `screenshots/dashboard.png`, `screenshots/test.png` do người làm bài chụp.

Kết quả 4 lệnh tự kiểm của CP6 trên URL public:
```
GET  /health              → 200 {"status":"ok","version":"1.0.0","environment":"production",...}
GET  /ready               → 200 {"ready":true}
POST /ask (không key)     → 401 {"detail":"Missing or invalid API key. Include header: X-API-Key: <key>"}
POST /ask (có key)        → (người làm bài tự chạy với key của mình)
POST /ask (key sai)       → 401
GET  /docs                → 404 (ẩn khi ENVIRONMENT=production)
```
`check_production_ready.py --public-url https://k5-l3a-day14-nguyenvanhuy-2a202603432.onrender.com` → `✅ Public URL: GET .../health → 200`, `Result: 12/12 tiêu chí đạt · 44/44 checks passed`.

**Sự cố khi deploy:** lần deploy đầu tiên trên Render build từ commit `83e677f` — lúc đó code Part 6 chưa được push nên Render chạy **bản khung TODO**: `/health` 404, `/ready` 404, `/ask` không key 200. Sau khi push commit `4ae1a83`, Render tự build lại và 3 lệnh không cần key đều đúng. Bài học: platform build từ **git**, không từ máy mình — phải push trước rồi kiểm tra commit đang chạy trên dashboard.

**Sự cố thứ hai — gõ sai tên biến môi trường:** `AGEN_API_KEY` và `ENVIROMENT` thay vì `AGENT_API_KEY` và `ENVIRONMENT`. App không báo lỗi mà âm thầm dùng giá trị mặc định: `/health` báo `"environment":"development"`, `/docs` mở công khai, `/ask` trả 401 cho cả key đúng. Phát hiện nhờ `/health` trả về `environment`. Sau khi sửa tên (và tạo key mới vì key cũ đã hiện trong ảnh chụp màn hình), log khởi động trên Render báo `"environment": "production", "redis_reachable": true` và Uvicorn nghe cổng `10000` do Render cấp. Bài học: endpoint health nên phơi ra cấu hình không bí mật (environment, version) để kiểm tra được từ bên ngoài; cấu hình production nên fail-fast — chính cơ chế "thiếu `AGENT_API_KEY` khi production thì dừng" đã chứng minh key được nạp đúng (deploy khởi động thành công).

Đã kiểm tra trên máy với app mẫu `03-cloud-deployment/railway/`: chạy đúng `startCommand` của `railway.toml` với `PORT` khác mặc định (`uvicorn app:app --host 0.0.0.0 --port $PORT`, `PORT=8123`) → `/health` 200, `/ask` 200. Như vậy app đọc port do platform cấp và bind `0.0.0.0`.

### So sánh `railway.toml` và `render.yaml` (`03-cloud-deployment/`)

| Khía cạnh | `railway/railway.toml` | `render/render.yaml` |
|---|---|---|
| Định dạng, phạm vi | TOML, config-as-code cho **một service**: chỉ mô tả cách build và chạy | YAML **Blueprint**: mô tả cả hạ tầng, gồm nhiều service (web + Redis) trong một file |
| Build | `builder = "NIXPACKS"`: Railway tự nhận diện Python và tự cài | `runtime: python` + `buildCommand: pip install -r requirements.txt` viết rõ |
| Start | `startCommand = "uvicorn app:app --host 0.0.0.0 --port $PORT"` | `startCommand: uvicorn app:app --host 0.0.0.0 --port $PORT` (giống nhau) |
| Health check | `healthcheckPath = "/health"`, `healthcheckTimeout = 30` | `healthCheckPath: /health` |
| Restart | `restartPolicyType = "ON_FAILURE"`, tối đa 3 lần | không khai báo trong file |
| Biến môi trường, secret | không khai trong file; đặt bằng CLI (`railway variables`) hoặc dashboard | khai trong `envVars`: giá trị thường ghi thẳng (`ENVIRONMENT`, `PYTHON_VERSION`); secret thì `sync: false` (nhập tay trên dashboard) hoặc `generateValue: true` (Render tự sinh, dùng cho `AGENT_API_KEY`) |
| Redis | không có; phải thêm service riêng trên Railway | khai luôn `type: redis` (`allkeys-lru`) trong cùng file |
| Region, gói, auto deploy | không khai (chọn trên dashboard) | `region: singapore`, `plan: free`, `autoDeploy: true` khi push GitHub |

**Vì sao khác nhau:** Railway thiên về CLI và dashboard. `railway.toml` chỉ ghi đè cách build/deploy cho service hiện tại, còn biến môi trường, database và domain đặt ngoài file. Render Blueprint là Infrastructure as Code cho cả project: Render đọc file từ repo GitHub và tự tạo mọi thứ (web, Redis, biến môi trường), nên file phải mô tả đầy đủ, kèm cách xử lý secret mà không ghi giá trị thật vào git.

**Lỗi trong file mẫu:** thư mục `03-cloud-deployment/render/` chỉ có `render.yaml`, không có `app.py` hay `requirements.txt`, và blueprint không khai `rootDir`. `buildCommand` và `startCommand` sẽ không tìm thấy file nếu dùng nguyên như vậy.

### Cấu hình deploy của agent Part 6 (`06-lab-complete/`)

| | `railway.toml` | `render.yaml` |
|---|---|---|
| Build | `builder = "DOCKERFILE"` | `runtime: docker`, `rootDir: 06-lab-complete` |
| Health check | `healthcheckPath = "/health"`, timeout 60 s | `healthCheckPath: /health` |
| Restart | `ON_FAILURE`, tối đa 3 lần | không khai báo trong file |
| `AGENT_API_KEY` | đặt bằng CLI/dashboard, không có trong file | `generateValue: true` (Render tự sinh) |
| Redis | thêm service Redis trong project; `REDIS_URL` tham chiếu biến của service đó | khai `type: keyvalue` trong file, `REDIS_URL` lấy qua `fromService` |

Cả hai build từ cùng `Dockerfile`, nên image chạy trên cloud giống image đã qua `check_production_ready.py`. `PORT` do nền tảng cấp và được `CMD` đọc qua `${PORT:-8000}`. `render.yaml` mới chỉ được kiểm bằng script chấm, chưa deploy thử trên Render.

**Giả lập môi trường Railway trên máy** (Railway cấp `PORT` khác 8000, Redis là service riêng): container nhận `PORT=9123`, `ENVIRONMENT=production`, Redis ở container khác cùng network:
```
/health 200 · /ready 200 · /ask không key 401 · /ask có key 200
cổng 8000 trong container: closed (app nghe đúng PORT=9123) · Docker HEALTHCHECK: healthy
```

**Lỗi phát hiện và đã sửa nhờ giả lập này:** khi `ENVIRONMENT=production` mà thiếu `AGENT_API_KEY`, config ném lỗi ngay (fail fast), nhưng container **không thoát**. Với `--workers 2`, process cha của uvicorn không import app; worker crash lúc import và uvicorn 0.30 khởi động lại worker mãi mãi (log lặp `Child process [...] died`). Trên Railway, lần deploy sẽ treo đến khi healthcheck hết hạn thay vì báo lỗi rõ ràng.

Sửa trong `Dockerfile`: `CMD ["sh","-c","python -c 'import app.config' && exec uvicorn ..."]`. Cấu hình được kiểm tra trước khi chạy uvicorn. Sau khi sửa: thiếu key → container thoát exit 1 kèm `RuntimeError: AGENT_API_KEY must be set when ENVIRONMENT=production`; config đúng → PID 1 vẫn là uvicorn, `docker stop` exit 0; script chấm vẫn `PASS 12/12`.

### Exercise 3.3: Pipeline Cloud Run (`production-cloud-run/`, chỉ đọc, không deploy)

Pipeline `cloudbuild.yaml` có 4 bước, bước sau `waitFor` bước trước, nên bước nào fail thì dừng toàn bộ:
1. **test**: dùng container `python:3.11-slim` cài `requirements.txt` + `pytest`, chạy `pytest tests/`.
2. **build**: `docker build` gắn 2 tag `gcr.io/$PROJECT_ID/ai-agent:$COMMIT_SHA` và `:latest`, tận dụng cache từ `:latest`.
3. **push**: đẩy cả 2 tag lên Container Registry.
4. **deploy**: `gcloud run deploy ai-agent` dùng image theo `$COMMIT_SHA` (tag cố định, rollback được) tại `asia-southeast1`, min 1 / max 10 instance, 512 Mi, 1 CPU, public, `OPENAI_API_KEY` lấy từ Secret Manager.

`service.yaml` là bản khai báo service tương ứng (Knative): mỗi instance tối đa 80 request đồng thời, timeout 60 s, liveness probe `/health`, startup probe `/ready`, secret qua `secretKeyRef`.

Điểm chưa khớp khi đọc: thư mục không có `tests/` và `Dockerfile`, nên bước 1–2 sẽ fail nếu chạy `gcloud builds submit` ngay tại đây. `cloudbuild.yaml` không set `AGENT_API_KEY` trong khi `service.yaml` có. `service.yaml` dùng image `:latest` còn pipeline deploy theo `$COMMIT_SHA`, tức có hai nguồn cấu hình khác nhau cho cùng một service.

---

## Part 4: API Security (CP3)

### Exercise 4.1: API Key authentication (`04-api-gateway/develop/app.py`)

- **Key được check ở đâu:** dependency `verify_api_key` (dòng 39–54), gắn vào `/ask` qua `Depends(verify_api_key)`. `/`, `/health` là public.
- **Sai key hoặc thiếu key:** thiếu header → **401** "Missing API key"; có header nhưng sai → **403** "Invalid API key." (không phải 401 như nhiều người nghĩ).
- **Rotate key:** key đọc từ env `AGENT_API_KEY` lúc khởi động (dòng 35). Đổi key = đổi env và restart. Không hỗ trợ hai key cùng lúc, nên client phải đổi đồng thời với server. Hướng cải tiến: cho phép danh sách key có thời hạn, hoặc lưu hash key trong DB.
- **Điểm yếu thấy khi đọc:** nếu không set env thì dùng mặc định `demo-key-change-in-production`; dòng 91 in toàn bộ API key ra stdout khi chạy `__main__`.

Kết quả test (`AGENT_API_KEY=secret-key-123 uvicorn app:app`):
```
no key      → HTTP/1.1 401 Unauthorized  {"detail":"Missing API key. Include header: X-API-Key: <your-key>"}
wrong key   → HTTP/1.1 403 Forbidden     {"detail":"Invalid API key."}
right key   → HTTP/1.1 200 OK            {"question":"Hello","answer":"Agent đang hoạt động tốt! ..."}
empty q     → 422
```

### Exercise 4.2: JWT authentication (`04-api-gateway/production/auth.py`)

Flow: `POST /auth/token` (username/password) → `create_token()` ký JWT HS256 với claim `sub`, `role`, `iat`, `exp` (60 phút) → client gửi `Authorization: Bearer <token>` → `verify_token()` kiểm tra chữ ký và hạn.

Lệnh lấy token trong đề (`POST /token` với `admin/secret`) **không chạy với code này**: endpoint đúng là `POST /auth/token`, tài khoản demo là `student/demo123` (role `user`) và `teacher/teach456` (role `admin`).

Kết quả test (token tạo bằng PyJWT, không sửa code):
```
POST /token        admin/secret          → 404 {"detail":"Not Found"}            ← lệnh trong đề
POST /auth/token   admin/secret          → 401 {"detail":"Invalid credentials"}
POST /auth/token   student/<sai>         → 401 {"detail":"Invalid credentials"}
/ask  JWT hết hạn (exp = 1 giờ trước)     → 401 {"detail":"Token expired. Please login again."}
/ask  JWT tự ký bằng secret khác, role=admin → 403 {"detail":"Invalid token."}
/ask  token rác "abc.def.ghi"            → 403 {"detail":"Invalid token."}
/admin/stats  token teacher (admin)      → 200
/admin/stats  token student (user)       → 403 {"detail":"Admin only"}
/admin/stats  JWT tự ký bằng SECRET MẶC ĐỊNH trong repo, role=admin → 200   ← lỗ hổng
```

- Thiếu token → 401. Token hết hạn → 401. Token sai chữ ký / không hợp lệ → **403** (không đồng nhất với chuẩn là 401).
- **Lỗ hổng nghiêm trọng:** `JWT_SECRET` có giá trị mặc định hardcode (`super-secret-change-in-production-please`) nằm công khai trong repo. Nếu deploy mà quên set biến môi trường, ai đọc code cũng tự ký được token `role=admin` và server chấp nhận (đã test: 200). Sửa: không cho giá trị mặc định; thiếu `JWT_SECRET` khi production thì dừng khởi động (fail-fast), dùng secret ngẫu nhiên ≥ 32 byte.
- `DEMO_USERS` lưu mật khẩu plaintext; chỉ dùng cho demo.

### Exercise 4.3: Rate limiting (`04-api-gateway/production/rate_limiter.py`)

- **Algorithm:** docstring ghi "Sliding Window Counter", nhưng implementation là **sliding window log**: mỗi user có `deque` lưu timestamp từng request, bỏ timestamp cũ hơn 60 giây.
- **Limit:** `student` (role `user`) 10 req/phút; `teacher` (role `admin`) 100 req/phút.
- **Bypass cho admin:** code không có cách bypass. Admin chỉ được bucket lớn hơn, chọn theo claim `role` trong JWT (dòng 141). Muốn bỏ hẳn giới hạn thì phải bỏ lời gọi `limiter.check()`. Đã test bằng token `teacher` (admin), gửi 105 request liên tiếp: **100 × 200, 5 × 429**, 429 đầu tiên ở request thứ 101.
- **Hạn chế khi scale:** bộ nhớ lưu trong process. Với nhiều instance, mỗi instance đếm riêng, nên giới hạn thực tế bị nhân lên. Cần Redis (CP4/Part 6).

Kết quả test (20 lần liên tiếp bằng token của `student`): 10 request đầu → 200; từ request thứ 11 → 429 (xem output đầy đủ ở Exercise 4.4 và phần tóm tắt dưới).

```
1:200 2:200 3:200 4:200 5:200 6:200 7:200 8:200 9:200 10:429 11:429 ... 20:429
```

(Lần đầu gọi thêm 1 request "Explain JWT" trước vòng lặp, nên request thứ 10 của vòng lặp là request thứ 11 trong cửa sổ 60 giây.)

### Exercise 4.4: Cost guard

**Cách code hiện có hoạt động** (`cost_guard.py`):
1. Trước khi gọi LLM: `check_budget(user)` kiểm tra budget ngày của user (mặc định $1/ngày) và tổng budget toàn hệ thống (mặc định $10). Vượt user budget → **402**; vượt global → **503**.
2. Gọi LLM (mock).
3. Sau khi gọi: `record_usage()` cộng token (mock: số từ × 2) × đơn giá để tính chi phí.

Quan hệ với rate limit: **rate limit bảo vệ tốc độ** (tránh spam, một user dồn request), **cost guard bảo vệ tiền** (một request đắt cũng có thể tiêu hết budget). Cần cả hai vì chúng chặn hai rủi ro khác nhau.

Các điểm phát hiện khi đọc và chạy:
- `_global_cost` **không bao giờ reset** dù mô tả là "daily". Sau khi tổng chi phí vượt $10 (qua nhiều ngày), toàn bộ service trả 503 cho đến khi restart.
- Trường `usage.budget_remaining_usd` trong response `/ask` thực ra là **số tiền đã dùng** (ví dụ `1.6e-05`), không phải số còn lại. Tên và giá trị không khớp.
- Dữ liệu lưu in-memory, không chia sẻ được giữa các instance.

**Kiểm chứng 402 / 503 / reset theo ngày.** Qua API không thể tiêu hết $1 vì rate limit 10 request/phút chặn trước, mỗi request chỉ tốn khoảng $0.00002. Tôi gọi trực tiếp class `CostGuard` của repo với budget nhỏ (không sửa file):
```
1) budget user $0.001: trước khi dùng → OK
   sau khi dùng $0.0015 → 402 {'error': 'Daily budget exceeded', 'used_usd': 0.0015, 'budget_usd': 0.001, 'resets_at': 'midnight UTC'}
   user khác → OK                                    ← budget tính riêng từng user
2) budget toàn hệ thống $0.001, đã dùng $0.0015 → 503 Service temporarily unavailable due to budget limits. Try again tomorrow.
3) giả lập sang ngày mới (đổi time.strftime):
   usage của alice reset về 0.0, nhưng global_cost vẫn = 0.003 → vẫn 503 "Try again tomorrow"   ← không bao giờ hết
4) /ask trả 'budget_remaining_usd' = 2.5e-05 (= số đã dùng); số còn lại thật = 0.999975
```
Điểm 3 và 4 xác nhận hai lỗi nêu trên: global budget không reset theo ngày (thông báo "Try again tomorrow" sai), và trường `budget_remaining_usd` trả số đã dùng.

**Implement theo đề (`04-api-gateway/production/budget_guard.py`):** `check_budget(user_id, estimated_cost) -> bool`, budget $10/tháng, lưu trong Redis với key `budget:{user_id}:{YYYY-MM}`, TTL 32 ngày.

Khác với lời giải mẫu trong CODE_LAB.md: lời giải mẫu làm `GET` → kiểm tra → `INCRBYFLOAT`, nên hai request song song có thể cùng đọc giá trị cũ rồi cùng được duyệt (race condition). Bản này cộng trước bằng `INCRBYFLOAT` (nguyên tử); nếu vượt thì trừ lại phần vừa cộng.

Kiểm thử với Redis 7 thật (`docker run redis:7-alpine`):
```
alice: 4.0 OK, 5.5 OK, 1.0 → False (không được tính); total = 9.5
bob: 9.99 OK (budget độc lập)
TTL của key = 2764800 s (32 ngày)
50 luồng đồng thời, mỗi luồng $0.5 → 20 được duyệt; total cuối = 10.0
ALL CHECKS PASSED
```

**Tóm tắt output `curl -i` (token đã che, đầy đủ trong bản ghi chạy):**

```
### 401 — không có token
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

### 200 — token hợp lệ (eyJhbG...<masked>)
HTTP/1.1 200 OK
{"question":"Explain JWT","answer":"...","usage":{"requests_remaining":9,"budget_remaining_usd":1.6e-05}}

### 429 — request thứ 11 trong cùng 60 giây
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
retry-after: 58
{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":58}}
```

---

## Part 5: Scaling & Reliability (CP4)

Code mẫu trong `05-scaling-reliability/` đã có sẵn `/health`, `/ready`, lifespan và Redis session (không có TODO). Theo CHECKPOINTS, tôi chạy và kiểm chứng code có sẵn, không viết lại. Các thử nghiệm sửa code đều chạy trên bản copy ngoài repo.

### Exercise 5.1: Health checks (`develop/app.py`)

- **`/health` — liveness** (dòng 104–144): process còn trả lời là 200. Có thêm check RAM bằng `psutil`: trên 90% thì `status: "degraded"`, nhưng HTTP vẫn 200.
- **`/ready` — readiness** (dòng 147–168): trả **503** khi `_is_ready = False` (startup chưa xong hoặc đang shutdown), 200 khi sẵn sàng.

Kết quả chạy:
```
GET /health → 200 {"status":"ok","uptime_seconds":5.4,"version":"1.0.0",...,"checks":{"memory":{"status":"ok","used_percent":85.3}}}
GET /ready  → 200 {"ready":true,"in_flight_requests":1}     # đếm cả chính request /ready
```

**Liveness khác readiness ở đâu:**
- Liveness fail → platform **restart** container.
- Readiness fail → load balancer **ngừng gửi traffic** vào instance đó nhưng không restart.

Vì vậy `/health` không nên phụ thuộc Redis (Redis chết thì restart agent không giải quyết được gì, chỉ gây restart loop), còn `/ready` thì nên kiểm tra Redis.

### Exercise 5.2: Graceful shutdown

**Cơ chế thật sự:**
- Uvicorn tự bắt SIGTERM: ngừng nhận kết nối mới, chờ request đang chạy xong (`timeout_graceful_shutdown=30`), sau đó mới chạy phần shutdown của `lifespan` (đặt `_is_ready = False`).
- Log cho thấy `handle_sigterm` của app chạy **sau** dòng `Finished server process`. Nghĩa là uvicorn thay handler trong lúc chạy và chỉ trả lại handler cũ khi đã tắt xong, nên handler này không tham gia vào quá trình shutdown.
- Vòng lặp "Waiting for N in-flight requests" trong lifespan không bao giờ in ra, vì uvicorn đã chờ xong trước đó.

**Cách test:** Windows không có `kill -TERM`, nên tôi dùng `docker stop` (gửi SIGTERM vào PID 1, giống platform thật) và so sánh với `docker kill` (SIGKILL).
- Client Python chạy trong container cùng network để đo chính xác.
- Gửi 20 request `/ask` đồng thời, tắt server sau 1 giây.
- Mock trong `develop/utils/mock_llm.py` có `delay=3.0` giây (cố ý giả lập "long task").

| Kịch bản | Code gốc (`async def ask_agent`) | Bản copy sửa thành `def ask_agent` |
|---|---|---|
| A. Không tắt server | 40,1 s; 12 × 200, 8 × timeout (40 s) | 3,1 s; 20 × 200 |
| B. `docker stop` (SIGTERM) sau 1 s | 6 × 200, 14 × ConnectionReset; `docker stop` mất 17,9 s; exit 0 | **20 × 200**; `docker stop` mất 2,8 s; exit 0 |
| C. `docker kill` (SIGKILL) sau 1 s | 0 × 200, 20 lỗi kết nối; exit 137 | (không chạy lại) |

Log server khi SIGTERM (code gốc):
```
INFO:     Shutting down
INFO:     Waiting for connections to close. (CTRL+C to force quit)
INFO:     Waiting for application shutdown.
INFO 🔄 Graceful shutdown initiated...
INFO ✅ Shutdown complete
INFO:     Finished server process [1]
INFO Received signal 15 — uvicorn will handle graceful shutdown
```

**Kết luận:**
- So với SIGKILL (mất cả 20), SIGTERM cho request đang chạy hoàn thành. Graceful shutdown hoạt động.
- Nhưng với code gốc vẫn mất 14/20 request. Nguyên nhân: `async def ask_agent` (dòng 94) gọi hàm **blocking** `ask()` (dùng `time.sleep`), làm chặn cả event loop. Request bị xử lý tuần tự, khoảng 3 s mỗi cái. Lúc nhận SIGTERM, uvicorn chưa kịp đọc 14 request đang xếp hàng nên đóng kết nối của chúng.
- Chỉ đổi thành `def` (FastAPI chạy hàm trong threadpool) thì 20 request chạy song song và không mất request nào khi shutdown.
- Cách sửa: dùng `def`, hoặc `await asyncio.to_thread(ask, question)`. Không sửa trong repo vì CHECKPOINTS yêu cầu không viết lại code mẫu.
- **`/health` cũng bị chặn theo** (đã đo với code repo, mock delay 3 s): lúc không tải `/health` trả 200 sau **0,07 s**; khi có 5 request `/ask` đang xếp hàng thì `/health` phải chờ **14,63 s**. Healthcheck của stack 05 đặt `timeout: 5s`, nên một container vẫn khỏe nhưng đang bận sẽ bị đánh dấu unhealthy, và platform có thể restart nó, làm mất luôn các request đang chạy.
- Lưu ý Docker: phải dùng dạng exec (`CMD ["python", ...]` hoặc `exec python ...`). Nếu PID 1 là `sh -c`, shell không chuyển SIGTERM xuống Python, và container chỉ bị SIGKILL sau timeout. `production/Dockerfile` đã dùng dạng exec.

### Exercise 5.3: Stateless design (`production/app.py`)

- Code đã stateless: session lưu trong Redis dưới key `session:{id}` (JSON, `SETEX` TTL 3600 s). Instance nào cũng đọc được session của user.
- Anti-pattern vẫn còn trong code: nếu không kết nối được Redis lúc khởi động, app **tự fallback** sang dict `_memory_store` trong RAM.

**Chứng minh vì sao state trong RAM hỏng khi scale:** tôi chạy lại stack 3 instance với `REDIS_URL` trỏ tới host không tồn tại (file override ngoài repo), rồi chạy `test_stateless.py`.
```
Request 1..5 → instance-8b69fb, -22491a, -915ad6, -8b69fb, -22491a
Total messages: 2          ← mong đợi 10; instance trả lời GET chỉ có lượt nó tự xử lý
/ready  → 200 {"ready":true,...}        (cả 3 instance)
/health → 200 {"status":"ok","storage":"in-memory","redis_connected":"N/A"}
```
Mỗi instance có RAM riêng, nên session bị chia mảnh theo instance nào xử lý request.

**Lỗi phát hiện:**
1. **Readiness báo sai:** khi fallback sang RAM thì `/ready` bỏ qua bước kiểm tra Redis và vẫn trả 200. Load balancer tiếp tục route vào instance đang làm mất state. Nên fail-fast lúc khởi động, hoặc trả 503 khi chạy nhiều instance mà không có Redis.
2. **`test_stateless.py` pass giả:** script vẫn in `✅ Session history preserved ... via Redis!` dù chỉ còn 2/10 message, vì nó không assert gì.
3. **Race condition khi ghi history:** `append_to_history` đọc → sửa → ghi lại cả session, không nguyên tử. Thử 10 lần, mỗi lần 8 request đồng thời cùng session (mong đợi 18 message): `[17, 17, 18, 18, 18, 18, 18, 18, 18, 18]`, tức **2/10 lần mất message**. Sửa: dùng Redis list (`RPUSH` + `LTRIM` + `EXPIRE` trong pipeline), đúng như ví dụ "Correct" với `lrange` trong đề.
4. **`turn` lệch 1:** code tính `turn` sau khi đã thêm câu hỏi hiện tại rồi còn `+ 1`, nên message đầu tiên của session trả `turn = 2`.

### Exercise 5.4: Load balancing

```
$ cd 05-scaling-reliability/production
$ docker compose -p k5-day14-scaling up -d --build --scale agent=3
k5-day14-scaling-agent-1   Up (healthy)   8000/tcp      172.19.0.3
k5-day14-scaling-agent-2   Up (healthy)   8000/tcp      172.19.0.5
k5-day14-scaling-agent-3   Up (healthy)   8000/tcp      172.19.0.4
k5-day14-scaling-nginx-1   Up             0.0.0.0:8080->80/tcp
k5-day14-scaling-redis-1   Up (healthy)   6379/tcp
```
(Cần tạo `.env.local` — file nằm trong `.gitignore`. Nginx publish port **8080**, không phải 80 như lệnh test trong đề.)

10 request qua Nginx, header `X-Served-By`:
```
req 1  172.19.0.3   req 2  172.19.0.5   req 3  172.19.0.4   req 4  172.19.0.3   req 5  172.19.0.5
req 6  172.19.0.4   req 7  172.19.0.3   req 8  172.19.0.5   req 9  172.19.0.4   req 10 172.19.0.3
```
Nginx chia **round-robin** đều qua 3 instance. Tên `agent:8000` trong upstream được Docker DNS phân giải thành IP của 3 replica.

Lưu ý: lệnh test trong đề gọi `POST /ask`, nhưng app này trả **404** vì endpoint là `POST /chat`.

### Exercise 5.5: Test stateless

`python test_stateless.py` với stack có Redis:
```
Request 1: [instance-ab41a5]   Request 2: [instance-552b76]   Request 3: [instance-191225]
Request 4: [instance-ab41a5]   Request 5: [instance-552b76]
Instances used: {'instance-191225', 'instance-ab41a5', 'instance-552b76'}
Total messages: 10
```
**Giải thích:** 5 request rơi vào cả 3 instance, nhưng history đủ 10 message (5 user + 5 assistant), vì mọi instance đọc và ghi cùng một key trong Redis. Không instance nào giữ state riêng.

**Kill instance giữa cuộc hội thoại.** Đề nói script này "kill random instance", nhưng thực tế script không kill gì. Tôi tự làm bước này bằng script riêng: chat 2 lượt, `docker kill` agent-1, rồi chat tiếp 6 lượt.
```
turn 1 → 200 (ab41a5)    turn 2 → 200 (552b76)
--- killed k5-day14-scaling-agent-1 (172.19.0.3)
turn 3 → TimeoutError (client chờ 15 s)
turn 4..8 → 200, chỉ còn ab41a5 và 552b76 phục vụ
history count = 14 (mong đợi 16 — mất đúng lượt 3)
nginx: connect() failed (113: Host is unreachable) while connecting to upstream "http://172.19.0.3:8000/chat"
container bị kill: exited, restarts=0
```
- Session **không mất**: các lượt trước và sau vẫn nằm trong Redis, instance còn lại tiếp tục được.
- Nhưng request đang được route tới instance vừa chết thì treo rồi mất, vì Nginx không có health check chủ động và `proxy_connect_timeout` mặc định 60 s. Sau lần lỗi đó Nginx mới bỏ instance khỏi vòng round-robin.
- Cải thiện: đặt `proxy_connect_timeout` ngắn (khoảng 2 s) để `proxy_next_upstream error timeout` chuyển request sang instance khác kịp thời; client retry.
- Container không tự khởi động lại sau `docker kill` dù có `restart: unless-stopped`. Thử riêng với hai container `python:3.11-slim` cùng `--restart unless-stopped`:
  ```
  bị docker kill               → status=exited  exit=137  restarts=0
  process tự thoát lỗi (exit 1) → status=running            restarts=3 (trong 10 s)
  ```
  Docker coi `docker kill` là **dừng thủ công**, nên không áp dụng restart policy; restart policy chỉ chạy khi process tự chết. Như vậy thí nghiệm kill ở trên mô phỏng việc tắt một instance, chưa phải một lần crash. Nếu là crash thật thì Docker tự khởi động lại instance, nhưng Nginx vẫn mất một request trong lúc phát hiện lỗi như đã thấy.

Đã dọn stack bằng `docker compose -p k5-day14-scaling down`.

---

## Part 6: Final Project (CP5)

### Kết quả `check_production_ready.py`

Chạy đầy đủ (có Docker) trong `06-lab-complete/`:
```
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```
Một số dòng chi tiết: image **273 MB**; `docker stop` → exit code 0 sau 1,1 s; 429 sau 5 request (`RATE_LIMIT_PER_MINUTE=5`); restart agent vẫn bị 429 (state trong Redis); Redis mất kết nối → `/ready` 503, `/health` 200; SIGTERM lúc có request → request vẫn 200, exit code 0.

**Môi trường chạy script chấm:** trên Windows, script tự đánh ⚠️ mục "SIGTERM khi đang có request" ("Windows không gửi được SIGTERM"), mà ⚠️ cũng tính là chưa đạt. Chạy trực tiếp trên Windows cho kết quả 11/12 tiêu chí, 42/42 check, chỉ thiếu đúng mục đó. Kết quả `PASS 12/12` ở trên chạy **trong container Linux** (`python:3.11-slim` + Docker CLI, dùng chung Docker daemon), không sửa script chấm:
```
docker run --rm --network host -v /var/run/docker.sock:/var/run/docker.sock \
  -v "<repo>:/repo" -w /repo/06-lab-complete <image python3.11 + docker cli> python check_production_ready.py
```

### Thiết kế và các bài học từ Part 1–5 được áp dụng

| Thành phần | Cách làm | Lý do (bài học trước) |
|---|---|---|
| `config.py` | Mọi giá trị đọc từ env; `ENVIRONMENT=production` mà thiếu `AGENT_API_KEY` thì dừng ngay lúc khởi động | Part 1: secret hardcode; Part 4: `JWT_SECRET` mặc định cho phép tự ký token admin |
| Log (`logging_setup.py`) | Formatter tự viết bằng `json.dumps`, chỉ gắn vào logger `agent` (`propagate=False`), không đụng root logger | Part 1: `basicConfig` thành no-op vì root logger bị cấu hình trước nên log JSON bị mất |
| `auth.py` | `X-API-Key` so sánh bằng `hmac.compare_digest`; thiếu, sai, hoặc server chưa đặt key → 401 | An toàn mặc định: chưa cấu hình key thì không mở API |
| `rate_limiter.py` | Sliding window trên Redis sorted set, kiểm tra + ghi trong **một Lua script** (nguyên tử); key Redis là SHA-256 của API key; 429 kèm `Retry-After` | Part 5: đọc → sửa → ghi không nguyên tử thì mất dữ liệu khi chạy song song; Part 4: rate limit trong RAM mất khi restart hoặc khi có nhiều instance |
| `cost_guard.py` | Chi phí cộng vào Redis theo key `cost:day:YYYY-MM-DD` và `cost:month:YYYY-MM` (UTC), có TTL; vượt budget ngày hoặc tháng → 402 | Part 4: biến tổng toàn hệ thống không bao giờ reset |
| Redis lỗi | `/ready` → 503; `/ask` → 503 (fail closed: không đếm được thì không cho gọi LLM); app vẫn khởi động khi chưa có Redis | Part 5: fallback âm thầm sang RAM làm hỏng state mà `/ready` vẫn báo 200 |
| `/ask` | Hàm `def` (FastAPI chạy trong threadpool) | Part 1/5: `async def` gọi hàm blocking chặn event loop, làm `/health` treo 14,6 s và mất request khi shutdown |
| Graceful shutdown | Không tự đăng ký handler SIGTERM, để uvicorn xử lý; `--timeout-graceful-shutdown 8` (< 10 s của `docker stop`); lifespan đánh dấu đang tắt để `/ready` trả 503 | Part 1: handler của app bị uvicorn thay thế; thiếu timeout thì bị SIGKILL (exit 137) |
| Dockerfile | Multi-stage (venv ở stage builder), `python:3.11-slim`, user `agent` không phải root, `HEALTHCHECK`, `CMD ["sh","-c","python -c 'import app.config' && exec uvicorn ... --port ${PORT:-8000}"]` | Part 2: dạng exec để uvicorn là PID 1 và nhận SIGTERM; `PORT` do platform cấp; kiểm tra config trước để config sai thì container thoát ngay (xem Part 3) |

Kiểm tra thêm với stack Compose (`ENVIRONMENT=production`): 4 lệnh tự kiểm của CP6 cho `200 / 200 / 401 / 200`; `/docs` trả 404 khi production; 12 request liên tiếp với giới hạn 10/phút → 9 × 200 rồi 429 (1 request đã dùng ở bước tự kiểm); log agent dạng `{"ts": ..., "lvl": "INFO", "logger": "agent", "event": "request", "request_id": ..., "status": 429, "ms": 2.7}`.

**Giới hạn đã biết:** `check_budget` và `record_cost` là hai bước riêng. Khi nhiều request chạy song song lúc chi phí sắp chạm ngưỡng, tổng có thể vượt budget một chút (tối đa khoảng số request đồng thời × chi phí 1 request).

---

## Part 7: Benchmark & Observability (CP7, CP8)

Chi tiết số liệu và phân tích: [`BENCHMARK_REPORT.md`](BENCHMARK_REPORT.md). Tóm tắt:

- **Exercise 7.1:** thêm metric `agent_question_length_chars` (Histogram, bucket 20…2000 ký tự, không dùng label vì độ dài có vô số giá trị) vào `develop/app.py`; đã kiểm tra trên `/metrics`. URL lạ (`/wp-admin`, `/.env`, `/a1b2c3`) đều gom vào **một** series `route="unmatched"`; nếu dùng `request.url.path` thì mỗi URL bot quét là một time series mới → cardinality bùng nổ, Prometheus hết RAM.
- **Exercise 7.2:** 4 mức concurrency + 3 mức `MOCK_SLOW_RATE` → `develop/reports/load_v2_*.json`. RPS gần tuyến tính tới 10, sau đó chậm lại; avg tăng ×1,65 còn p95 ×3,7 khi request chậm tăng lên 10 %.
- **Exercise 7.3:** v1 4,3 % → v2 91,3 % → v2 sau khi thêm 2 entry `KNOWLEDGE_BASE` 100 %, 0 regression. Job CI `.github/workflows/eval.yml` dùng exit code của `run_eval.py` để chặn merge.
- **Exercise 7.4–7.7:** stack Docker (`-p k5-day14-observability`), Locust headless 1 vs 3 instance (`production/benchmark-results/scale_{1,3}_stats.csv`), trace chậm / trace lỗi kèm log cùng `trace_id`, thí nghiệm alert, ảnh trong `screenshots/`.
- **Lỗi của lab tìm thấy khi làm:** `production/Dockerfile` thiếu `PYTHONUSERBASE` nên container agent crash (`No module named 'uvicorn'`) — đã sửa 1 dòng; `docker compose run locust` làm đổi số instance (dùng `--no-deps`); `run_eval.py` ghi file rỗng trên Windows (dùng `PYTHONUTF8=1`); Jaeger 2.23 chỉ còn API `/api/v3`.

---

## AI log

- **Đã làm gì bằng AI:** nhờ Claude Code đọc đề, chạy các lệnh của Part 1, 2, 4 và 5 trên máy, viết `budget_guard.py` theo đề và soạn file này.
- **Số đo và output:** lấy từ lệnh thực tế trong phiên (kích thước image bằng `docker images` / `docker image inspect`, output curl, kết quả test Redis, các thử nghiệm shutdown/failover/race của Part 5).
- **Part 5:** các script thử nghiệm (client 20 request đồng thời, kill instance, race) và bản copy sửa `async def` → `def` chỉ chạy ngoài repo; code mẫu trong `05-scaling-reliability/` không bị sửa.
- **Part 1:** các thử nghiệm container (bind localhost, `.env`, graceful shutdown SIGTERM/SIGKILL) chạy trên code repo hoặc bản copy ngoài repo; code mẫu trong `01-localhost-vs-production/` không bị sửa.
- **Part 3:** phần so sánh `railway.toml` / `render.yaml` và Exercise 3.3 dựa trên đọc file; riêng `startCommand` của Railway đã chạy thử trên máy. Chưa deploy (cần Part 6 và tài khoản cloud).
- **Part 4 bổ sung:** token hết hạn/giả được tạo bằng PyJWT; test 402/503/reset ngày gọi trực tiếp class `CostGuard` với budget nhỏ, không sửa code repo.
- **Part 6:** Claude Code viết code các TODO trong `06-lab-complete/` (thiết kế dựa trên lỗi đo được ở Part 1–5), chạy `check_production_ready.py` (Windows và container Linux) tới `PASS 12/12`, giả lập môi trường Railway và tìm/sửa lỗi fail-fast với `--workers 2`. Script chấm không bị sửa.
- **Part 3 (deploy):** người làm bài tự tạo service trên Render; Claude Code commit + push code, chạy các lệnh tự kiểm và `--public-url`, viết `DEPLOYMENT.md`. Lệnh `/ask` có key do người làm bài tự chạy (key không đi qua AI).
- **Part 7:** Claude Code chạy load test, eval, sửa `KNOWLEDGE_BASE`, stack Docker, Locust, thí nghiệm alert bằng script đo thời gian qua API Prometheus, lấy trace qua API Jaeger, chụp ảnh UI bằng Chromium headless, viết `BENCHMARK_REPORT.md`; sửa 1 dòng `production/Dockerfile` để stack chạy được. Mọi số trong báo cáo lấy từ file JSON/CSV đã nộp hoặc truy vấn Prometheus/Jaeger lúc chạy.
- **Cần người làm kiểm tra lại:** các câu trả lời lý thuyết (đặc biệt so sánh Part 3, pipeline Cloud Run, nhận xét trong `BENCHMARK_REPORT.md`) trước khi nộp; đảm bảo hiểu từng đoạn code trong `06-lab-complete/app/` và `budget_guard.py` (Lab Coach có thể hỏi bất kỳ đoạn nào — RULES.md mục 1).
