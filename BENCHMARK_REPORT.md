# Benchmark & Observability Report — Day 14

**Họ tên:** Nguyễn Văn Huy (2A202603432)
**Ngày chạy:** 2026-11-25
**Môi trường:** Laptop Windows 11, Intel Core i5-1035G1 (8 logical CPU), RAM 7,8 GB; Docker Desktop 29.9.2 (VM 8 CPU / 3,7 GB). Bước 1 chạy agent + `load_test.py` trực tiếp trên Windows (Python 3.11); một số lượt so sánh chạy trong container Linux (ghi rõ bên dưới). Bước 2 chạy stack Docker Compose `-p k5-day14-observability`.

> Mọi con số lấy từ file đã nộp: `06-lab-complete/benchmark-observability/develop/reports/*.json`, `production/benchmark-results/*.csv`, ảnh trong `screenshots/`, và truy vấn Prometheus / Jaeger trong lúc chạy.

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Mock LLM mất ~150–210 ms/câu; 500 ms là mặc định của `load_test.py`, đủ chỗ cho retrieval + hàng đợi nhẹ. Đặt theo p95 (không theo avg) để thấy tail latency. Alert dùng ngưỡng lỏng hơn (p95 > 1 s trong 2 phút) để tránh báo động vì spike ngắn |
| Error rate `/ask` | < 2 % | Upstream LLM tự lỗi ~1 % (`MOCK_ERROR_RATE=0.01`); 2 % chừa error budget gấp đôi mức nền. Alert ở > 5 % trong 1 phút |
| Accuracy trên golden dataset | ≥ 85 % | Ngưỡng quality gate trong CI (`--min-accuracy 0.85`) **và** không có regression so với baseline. Bản v2 sau khi sửa đạt 100 % |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

300 request mỗi mức, `--url http://localhost:8002` trên Windows (file `reports/load_v2_c{1,10,50,100}.json`):

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.35 | 202.0 | 233.9 | 1683.8 | 1.00 % | ✅ PASS |
| 10 | 38.13 | 194.8 | 254.8 | 1718.9 | 0.33 % | ✅ PASS |
| 50 | 82.17 | 249.9 | 1241.7 | 1994.7 | 0.33 % | ❌ FAIL (p95) |
| 100 | 38.70 | 1218.5 | 5407.0 | 5672.4 | 1.00 % | ❌ FAIL (p95) |

Đo lại cùng lệnh trong container Linux (agent và client mỗi bên 1 container, cùng network — `reports/load_v2_c*_linux.json`):

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.27 | 190.0 | 221.7 | 1690.1 | 1.00 % | ✅ |
| 10 | 35.38 | 192.4 | 223.7 | 1700.4 | 0.67 % | ✅ |
| 50 | 103.42 | 199.7 | 318.7 | 1718.9 | 1.33 % | ✅ |
| 100 | 41.26 | 1070.6 | 5080.5 | 5709.0 | 1.00 % | ❌ |

**Nhận xét:**
- **1 → 10: gần tuyến tính** (4,35 → 38,13 RPS, ×8,8). Agent dùng `asyncio.sleep` nên chờ LLM không chặn nhau; theo định luật Little, RPS ≈ concurrency / latency ≈ 10 / 0,23 s ≈ 43.
- **50: dưới tuyến tính** (lý thuyết ~200 RPS, đo được 82 trên Windows, 103 trên Linux). Trên Linux p95 vẫn đạt SLO, trên Windows thì không → một phần chậm do môi trường Windows.
- **100: RPS còn giảm** (38,7) và p95 lên 5,4 s, **ở cả Windows lẫn Linux**. Tôi tìm nguyên nhân bằng cách so latency phía client với histogram của chính agent (Linux, concurrency 100):

  | | p50 | p95 |
  |---|---|---|
  | Client (`load_test.py`) | 1083 ms | 5367 ms |
  | Agent `http_request_duration_seconds` | ≈ 216 ms | ≈ 294 ms |
  | Agent `llm_request_duration_seconds` | ≈ 151 ms | ≈ 196 ms |

  Thời gian **trong agent gần như không đổi** so với concurrency 50 (p95 ≈ 292 ms). ~5 s còn lại nằm **ngoài phần xử lý của agent** (thiết lập kết nối / connection pool của client httpx). Đo thêm trên Windows: agent chỉ dùng ≤ 4 % một core, client ≤ 54 % → không phải nghẽn CPU. Tôi chưa xác định được chính xác bước nào bên ngoài agent gây chờ. Bài học: metric của một service chỉ thấy phần việc của chính nó — cần đo cả ở phía client / load balancer.
- Đo concurrency 50/100 bằng `127.0.0.1` thay cho `localhost` (Windows phân giải `localhost` ra `::1` trước) cho kết quả dao động 41–66 RPS ở mức 100 (`reports/load_v2_c*_ipv4.json`), nên không kết luận được IPv6 là nguyên nhân.

### 2.2 Tail latency

v2 khởi động lại với từng giá trị `MOCK_SLOW_RATE`, `--requests 300 --concurrency 20` (`reports/load_v2_slow_*.json`):

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 219.2 | 459.5 | 495.8 |
| 0.03 (mặc định) | 259.3 | 477.6 | 1701.6 |
| 0.1 | 361.6 | 1695.2 | 1722.3 |

**Nhận xét:**
- Từ 0 → 0.1: avg chỉ tăng **×1,65**, còn p95 tăng **×3,7** và p99 **×3,5**. Với 3 % request chậm, **p99 nhạy nhất** (496 → 1702 ms) trong khi p95 và avg gần như không đổi; khi lên 10 %, request chậm vượt qua mốc 95 % nên p95 cũng nhảy.
- Average trộn 90 % request nhanh với 10 % request rất chậm thành một con số "trung bình" mà **không người dùng nào thật sự gặp**: người gặp request chậm chờ ~1,7 s. SLO đặt theo avg (vd < 400 ms) vẫn PASS ở `MOCK_SLOW_RATE=0.1` trong khi 1/10 người dùng chờ gần 2 s → SLO phải đặt theo p95/p99.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3 % (1/23) | 91.3 % (21/23) | 100 % (23/23) |
| Avg tokens / câu | 57.0 | 108.7 | 115.0 |
| Tổng cost (USD) | 0.000403 | 0.000756 | 0.000802 |
| Cost / câu đúng (USD) | 0.00040335 | 0.00003599 | 0.00003488 |
| Quality gate | FAIL (≥ 80 %) | PASS (≥ 80 %, 0 regression so với v1) | PASS (≥ 100 %, 0 regression so với v2) |

File: `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json`. Lệnh eval cuối: `python eval/run_eval.py --url http://localhost:8002 --min-accuracy 1.0 --baseline reports/eval_v2.json --out reports/eval_v2_fixed.json` → `Quality gate (accuracy ≥ 100%, không regression): ✅ PASS`.

**Những câu v2 trả lời sai ban đầu và cách sửa:**

| ID | Keyword bị thiếu | Đã sửa gì |
|---|---|---|
| security-02 ("JWT khác gì API key…") | `token`, `hết hạn`, `chữ ký` | Thêm vào `KNOWLEDGE_BASE` entry từ khoá `["jwt", "api key"]`: API key cố định, không tự hết hạn; JWT là token có chữ ký số, chứa claims và thời điểm hết hạn |
| scaling-03 ("Kubernetes HPA scale dựa trên…") | `cpu`, `memory`, `custom metrics` | Thêm entry `["kubernetes", "hpa", "autoscal"]`: HPA scale theo CPU, memory hoặc custom metrics |

Trước khi thêm, tôi kiểm tra cả 23 câu hỏi: các từ khoá mới chỉ xuất hiện trong đúng 2 câu đó, nên không câu nào khác bị đổi tài liệu retrieve → 0 regression. Không sửa `golden_dataset.jsonl`.

**Quality gate trong CI** (`.github/workflows/eval.yml`): mỗi pull request chạy agent v2 (`MOCK_ERROR_RATE=0` để lỗi ngẫu nhiên của mock không làm fail oan) rồi `run_eval.py --min-accuracy 0.85 --baseline reports/eval_v2_fixed.json`. `run_eval.py` trả exit code 1 khi accuracy dưới ngưỡng hoặc có regression → step fail → PR bị chặn (khi bật branch protection "require status checks"). Đã chạy thử đúng các lệnh của job trong container Linux: v2 → exit 0; v1 → exit 1 (22 câu regression). Chạy tay v1 với baseline v2: exit 1, 20 câu regression.

**Trade-off v1 / v2:** v2 tốn **gấp ~1,9 lần token mỗi câu** (prompt dài hơn vì có context) và tổng cost gần gấp đôi, latency thêm bước retrieval (~20 ms), nhưng **cost / câu đúng rẻ hơn ~11 lần** (0.000403 → 0.000036 USD) vì v1 gần như không trả lời đúng câu nào. Chỉ nhìn "cost / câu" sẽ chọn nhầm v1; "cost / câu đúng" phản ánh đúng giá trị nhận được.

**Lỗi gặp khi chạy eval trên Windows:** `run_eval.py` ghi report bằng `Path.write_text(json.dumps(..., ensure_ascii=False))` không chỉ định encoding → trên Windows (cp1252) lỗi `UnicodeEncodeError` giữa chừng, để lại file `eval_v1.json` rỗng (0 byte) và lượt eval v2 sau đó crash khi đọc baseline. Chạy với `PYTHONUTF8=1` (không sửa code) thì bình thường.

---

## 4. Observability stack (production)

Stack: `docker compose -p k5-day14-observability up -d --build` (agent + nginx + prometheus + grafana + jaeger + locust). Unit test alert rules: `promtool test rules /p/alert_rules_test.yml` → `SUCCESS`.

**Lỗi của lab khi bật stack:** container agent crash liên tục (`ModuleNotFoundError: No module named 'uvicorn'`). `production/Dockerfile` copy package vào `/home/agent/.local` nhưng user `agent` có home là `/app` (`useradd -d /app`), nên Python tìm package ở `/app/.local`. Sửa bằng 1 dòng `ENV PYTHONUSERBASE=/home/agent/.local` (giống Dockerfile của Part 5).

### 4.1 Screenshot

Chụp bằng Chromium headless trỏ thẳng vào UI của stack đang chạy (thư mục `screenshots/`):

- [x] Dashboard Grafana khi đang có tải — `grafana-dashboard.png` (lượt scale_3: 60.8 req/s, error 0.96 %, p95 366.67 ms, 3 instance up)
- [x] Một trace chậm trong Jaeger — `jaeger-slow-trace.png`
- [x] Một trace lỗi trong Jaeger — `jaeger-error-trace.png` (thấy span lỗi và HTTP 503; nội dung event `exception` nằm trong panel phải bấm mở trên UI, nên ghi lại ở mục 4.3 từ API Jaeger)
- [x] Trang Alerts của Prometheus có alert đang **firing** — `prometheus-alert-firing.png`: `AgentHighErrorRate` và `AgentInstanceDown` **cùng firing** (nhóm `agent-slo`: FIRING (2))
- Thêm: `grafana-during-AD.png` (trong lúc thí nghiệm A + D), `grafana-during-C.png` (thí nghiệm C)

**Câu hỏi Exercise 7.4** (đọc khi chạy tải Locust):
1. **p95 và avg:** lượt scale_3 (Locust) p95 = 470 ms, avg = 260 ms, p50 = 200 ms. Khoảng cách p95/avg ≈ 1,8 lần cho thấy phân bố có **đuôi dài**: phần lớn request ~200 ms, một nhóm nhỏ (3 % request chậm của mock, +1,5 s) kéo p95/p99 lên trong khi avg vẫn thấp.
2. **Nginx có chia đều không:** có. `X-Served-By` xoay vòng `.8 → .9 → .4 → .8 → …`; khi chạy scale_3, CPU mỗi instance 0.12 / 0.12 / 0.13 core và panel "Requests/s theo instance" có 3 đường gần trùng nhau (~20 req/s mỗi instance).
3. **Vì sao input tokens/s > output tokens/s:** baseline đo được input 1146 tokens/s, output 609 tokens/s. Prompt gồm system prompt + tài liệu retrieve được + câu hỏi, còn câu trả lời của mock chỉ là nội dung tài liệu → input dài hơn output. Bản v1 (không retrieval) giảm input còn 676 tokens/s.
4. **`curl http://localhost:8080/metrics`** → `404`. `nginx.conf` có `location = /metrics { return 404; }`: metric lộ thông tin nội bộ (route, lưu lượng, version) nên không public ra ngoài; Prometheus scrape thẳng từng agent `agent:8000/metrics` trong mạng Docker nội bộ, không đi qua Nginx.

### 4.2 Thí nghiệm "phá hệ thống"

Locust 30 users chạy suốt, 2 agent. Thời gian đo bằng script đọc `GET /api/v1/alerts` mỗi 2 s, tính từ lúc ghi `.env` mới và `docker compose up -d` (T0):

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` (error rate đo được 21.2 %) | `AgentHighErrorRate` | pending 29 s → **firing 90 s** (`for: 1m`) | Error rate (đỏ), Requests/s theo status code (503 tăng), LLM calls error |
| B | `MOCK_SLOW_RATE=0.3` (p95 = 1.91 s, avg = 0.61 s) | `AgentHighLatencyP95` | pending 35 s → **firing 154 s** (`for: 2m`) | Latency p95 và biểu đồ p50/p95/p99/avg (p95 ×3 avg) |
| C | `LLM_MODEL=mock-llm-large` (cost $1.25 → $9.46/giờ) | `LLMCostBurnRateHigh` | pending 37 s → **firing 252 s** (`rate[5m]` + `for: 2m`) | Cost burn rate (USD/giờ), LLM cost (1h), LLM latency p95 (p95 HTTP lên 1.64 s) |
| D | `docker pause` agent-1 (trong lúc A vẫn bật) | `AgentInstanceDown` | pending 13 s → **firing 44 s** (`for: 30s`); `up{job="agent"}` = 0 và 1 | Instances up (giảm còn 1) |
| E | `AGENT_VERSION=v1` | **Không có** (theo dõi 180 s) | — | Tokens/s giảm (input 1146 → 676/s, output 609 → 366/s), Retrieval hit ratio mất dữ liệu (v1 không retrieve), bảng "Phiên bản đang chạy" |

Quan sát thêm:
- **Mỗi lần đổi cấu hình**, container agent được tạo lại → `AgentInstanceDown` lên `pending` 10–15 s rồi tự hết. Nhờ `for: 30s` nên không firing nhầm — ví dụ thực tế cho việc vì sao alert cần `for`.
- **`LLMCostBurnRateHigh` đã firing ngay từ benchmark scaling (100 users, model nhỏ, ~60 req/s ≈ $2.7/giờ)**, trước khi đổi gì. Alert cost theo $/giờ tuyệt đối phản ánh cả traffic tăng, không chỉ việc đổi sang model đắt. Phải đợi nó hết (về $1.25/giờ với 30 users) mới đo được thí nghiệm C.
- Thí nghiệm C: cost/giờ tăng ×7,5 chứ không ×16 như giá token, vì model lớn chậm hơn 2,5 lần nên với tải vòng kín (Locust) số request/giây giảm, và `rate[5m]` lúc đo còn lẫn dữ liệu trước khi đổi.

**Thí nghiệm E không làm alert nào firing. Phát hiện loại sự cố này trong production bằng cách nào?**
Đổi về v1 làm accuracy rơi từ 100 % xuống 4,3 % (mục 3) nhưng latency, error rate, instance đều xanh — metric hạ tầng không đo **độ đúng**. Cần:
- **Quality gate trước deploy:** job CI chạy `run_eval.py` (exit 1 → chặn merge) — đã chạy thử: v1 so với baseline bị chặn với 22 câu regression.
- **Eval định kỳ trên production:** chạy golden dataset (hoặc LLM-as-judge trên mẫu traffic thật) theo lịch, đẩy accuracy thành metric và alert khi giảm.
- **Metric chất lượng gián tiếp:** alert khi retrieval hit ratio giảm đột ngột, hoặc khi tokens/câu giảm bất thường; theo dõi feedback người dùng (👍/👎).
- **Đối chiếu version:** bảng `agent_info` cho thấy version đang chạy — deploy nhầm version là thấy ngay nếu có alert khi version ≠ version mong đợi.

### 4.3 Debug bằng trace

Lấy từ API Jaeger v2 (`/api/v3/traces`, 1000 trace `POST /ask` gần nhất trong 15 phút, lượt scale_3):

- `trace_id`: `f999deace79bb9a0100476750bc647e1`
- Tổng thời gian: **1725.8 ms**
- Span chiếm nhiều thời gian nhất: `chat mock-llm-small` (**1693.8 ms, 98.1 %**) — `agent.retrieve_context` chỉ 24.7 ms (1.4 %). Request chậm vì **LLM upstream** (thuộc nhóm 3 % request chậm của mock), không phải do code agent hay retrieval.
- Dòng log tương ứng (`docker compose -p k5-day14-observability logs agent | grep f999deace79bb9a0100476750bc647e1`):

```json
{"ts": "2026-11-25T09:46:28.749406+00:00", "level": "INFO", "service": "observable-agent", "instance": "3167aff10dd7", "event": "llm_call", "trace_id": "f999deace79bb9a0100476750bc647e1", "span_id": "bcbf7f81d0a03a76", "request_id": "214216f0cdb2", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 83, "output_tokens": 44, "cost_usd": 3.9e-05, "llm_ms": 1693.0}
{"ts": "2026-11-25T09:46:28.750574+00:00", "level": "INFO", "service": "observable-agent", "instance": "3167aff10dd7", "event": "http_request", "trace_id": "f999deace79bb9a0100476750bc647e1", "span_id": "bcbf7f81d0a03a76", "request_id": "214216f0cdb2", "method": "POST", "route": "/ask", "status": 200, "ms": 1724.1}
```

**Trace lỗi:** `trace_id` `31fc441a43422503acdad942a4eac9b7`, 848.0 ms, HTTP 503. Span `agent.run` và `chat mock-llm-small` có status lỗi và event `exception`: `type=utils.mock_llm.LLMError`, `message=Upstream LLM error: 503 Service Unavailable (mock)`. Log cùng `trace_id`:

```json
{"ts": "2026-11-25T09:46:33.340385+00:00", "level": "INFO", "service": "observable-agent", "instance": "12d476d6335c", "event": "llm_error", "trace_id": "31fc441a43422503acdad942a4eac9b7", "span_id": "ae6f7ede78d7c77e", "request_id": "070168f1c810", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
{"ts": "2026-11-25T09:46:33.341069+00:00", "level": "INFO", "service": "observable-agent", "instance": "12d476d6335c", "event": "http_request", "trace_id": "31fc441a43422503acdad942a4eac9b7", "span_id": "ae6f7ede78d7c77e", "request_id": "070168f1c810", "method": "POST", "route": "/ask", "status": 503, "ms": 847.1}
```

Ghi chú: Jaeger 2.23 không còn API cũ `/api/traces` (trả 404), phải dùng `/api/v3/traces` (định dạng OTLP; lỗi nằm ở `status.code` chứ không phải tag `error=true`).

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Số liệu từ `production/benchmark-results/scale_1_stats.csv` và `scale_3_stats.csv`, dòng `/ask`:

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 53.35 | 210 | 1600 | 2000 | 80 / 6328 (1.26 %, đều 503 từ mock LLM) |
| 3 | 59.11 | 200 | 470 | 1700 | 72 / 7054 (1.02 %, đều 503 từ mock LLM) |

Truy vấn Prometheus giữa mỗi lượt chạy:

| | CPU mỗi instance | `agent_in_flight_requests` | p95 HTTP (agent) | p95 LLM |
|---|---|---|---|---|
| 1 instance (09:43 UTC) | 0.35 core (giới hạn `cpus: "0.5"`) | 41 | 1189 ms | 198 ms |
| 3 instance (09:45 UTC) | 0.12 / 0.12 / 0.13 core | 12 | 375 ms | 198 ms |

**Giải thích kết quả:**
- **p95 cải thiện mạnh** (1600 → 470 ms). p95 của LLM giữ nguyên 198 ms ở cả hai lượt, nên phần chậm thêm ở 1 instance là **thời gian xếp hàng trong agent**: một container bị giới hạn 0,5 CPU, xử lý mỗi request còn tốn CPU cho JSON log, OpenTelemetry span, metrics → 41 request đồng thời chờ nhau. 3 instance chia tải → mỗi cái 0,12 core, 12 request in-flight, hết hàng đợi. **Nút thắt ở 1 instance là CPU của agent, không phải LLM.**
- **RPS chỉ tăng nhẹ** (53 → 59) vì Locust là tải **vòng kín**: 100 user, mỗi user nghỉ 0,5–2 s giữa các request → trần ≈ 100 / (1,25 s + latency) ≈ 60–65 RPS. Khi latency giảm thì RPS chỉ tiến sát trần đó. Muốn đo throughput tối đa phải tăng số user hoặc bỏ thời gian nghỉ.
- Ở 3 instance, p95 còn lại (~375–470 ms) chủ yếu là latency LLM + 3 % request chậm của mock → nếu scale tiếp, nút thắt sẽ là LLM.

**Bẫy khi chạy lệnh benchmark:** lệnh `docker compose run --rm locust ...` (như trong CHECKPOINTS/README) tự khởi động lại các service phụ thuộc (locust → nginx → agent) theo `replicas: 2` trong compose file. Lượt `scale_1` đầu tiên của tôi vì vậy chạy với **2** agent (Prometheus xác nhận 2 target `up`, cả hai cùng nhận ~28 req/s), còn lượt `scale_3` đầu tiên thì bị kéo từ 3 về 2 agent. Kết quả trên là lượt chạy lại với `docker compose run --rm --no-deps locust ...`; đã kiểm tra số container agent trước và sau mỗi lượt (1 → 1, 3 → 3).

---

## 6. Kết luận

- 3 điều học được về benchmark & observability:
  1. **Average che giấu người dùng bị chậm.** 10 % request chậm làm avg tăng ×1,65 nhưng p95 ×3,7; SLO và alert phải đặt theo percentile.
  2. **Đo ở nhiều tầng mới tìm được nút thắt.** Ở concurrency 100, client thấy p95 5,4 s nhưng histogram của agent chỉ ~0,3 s; ở benchmark scaling, p95 LLM không đổi còn p95 HTTP giảm 3 lần → nhờ so các lớp metric mới biết chậm nằm ở đâu (ngoài agent, hoặc hàng đợi CPU trong agent) thay vì đoán là "LLM chậm".
  3. **Phải kiểm chứng điều kiện thí nghiệm, không chỉ đọc kết quả.** Lệnh `compose run` âm thầm đổi số instance, `run_eval.py` âm thầm ghi file rỗng trên Windows — cả hai cho ra con số trông hợp lý nhưng sai. Truy vấn Prometheus (`count(up)`) và kiểm tra file đã cứu bài benchmark.
- Nếu đưa agent này lên production thật, tôi sẽ thêm:
  - **Alert chất lượng**: eval định kỳ trên golden dataset (hoặc LLM-as-judge trên mẫu traffic thật), alert khi accuracy giảm — loại sự cố như đổi về v1 không làm metric hạ tầng nào đỏ.
  - **Alert retrieval hit ratio** giảm đột ngột (dấu hiệu knowledge base / vector DB hỏng) và **alert saturation**: `agent_in_flight_requests` hoặc CPU throttling của container cao kéo dài (nút thắt thấy ở benchmark 1 instance).
  - **Giám sát ở tầng load balancer / synthetic check** từ bên ngoài: lỗi 504 của Nginx và latency phía client không hiện trong metric của agent.
  - **Error budget burn-rate alert** (đa cửa sổ, vd 5 m + 1 h) thay vì ngưỡng cố định, và alert cost theo **cost / request** hoặc theo budget ngày (alert `LLMCostBurnRateHigh` hiện tại firing chỉ vì traffic tăng — xem mục 4.2).
