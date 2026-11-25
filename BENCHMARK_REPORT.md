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

> _Đang chạy thí nghiệm — điền sau._

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
