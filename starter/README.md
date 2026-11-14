# Chạy pipeline · PostgreSQL + pgvector

Pipeline trong `src/` đọc PDF, chuẩn hóa, chia chunk, tạo embedding, lưu vector và đánh giá truy xuất. Bản hiện tại chạy **Python 3.12, BAAI/bge-m3 trên CPU, PostgreSQL 16 + pgvector**. Cấu hình cố định ở [configs/lab.json](../configs/lab.json), dữ liệu ở root `data/`.

## 1. Cài môi trường local

Cần Python **3.12**, Docker Engine/Desktop + Compose và [uv](https://docs.astral.sh/uv/getting-started/installation/). Lock file đã được kiểm tra với Python 3.12. Cần mạng để cài dependencies và tải model lần đầu. Chạy từ root repo:

```bash
cd starter
python3.12 -m venv .venv
source .venv/bin/activate
uv pip sync --python .venv/bin/python --torch-backend cpu requirements-local.lock
```

Trên Windows PowerShell: dùng `py -3.12 -m venv .venv`, kích hoạt bằng `.venv\Scripts\Activate.ps1`, thay đường dẫn Python trong lệnh uv bằng `.venv\Scripts\python.exe`.

`requirements-local.lock` lưu phiên bản các package đã dùng trên CPU. `requirements-local.txt` dùng để tạo lock; `requirements.txt` chứa thư viện đọc PDF và kết nối database.

Nếu chưa có `.env`, copy `.env.example` thành `.env` (PowerShell: `Copy-Item .env.example .env`). Mẫu đã điền model và revision dùng trong thí nghiệm:

```dotenv
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_REVISION=5617a9f61b028005a4858fdac845db406aefb181
```

Giữ `DATABASE_URL` theo mẫu Docker local. Model CPU không cần API key. `.env` đã được Git bỏ qua; không commit key/token.

## 2. Lấy và kiểm tra corpus

Từ `starter/`, dùng môi trường đã kích hoạt:

```bash
python scripts/fetch_data.py
python scripts/check_corpus.py
```

`fetch_data.py` đọc manifest ở root, tải file thiếu vào `data/raw/stroke-awareness/`, kiểm tra SHA-256 trước khi nhận file. File local đúng được dùng lại; file sai checksum không bị ghi đè. PDF gốc chỉ giữ local và được Git bỏ qua.

Chỉ kiểm tra file có sẵn, không truy cập mạng:

```bash
python scripts/fetch_data.py --verify-only
```

Nếu nguồn trả HTTP 403 hoặc lỗi mạng, tải thủ công theo [data/README.md](../data/README.md), sau đó chạy `fetch_data.py --verify-only`.

`check_corpus.py` đọc lại PDF qua pipeline, kiểm tra checksum, trang chọn/loại và số ký tự so với manifest. Kết quả cần đạt: `PASS`, **5 tài liệu / 83 trang vật lý / 67 trang được chọn / 95.535 ký tự**. Bốn trang rỗng đều đã loại; không có trang được chọn bị lỗi. Nguồn và quyền sử dụng nằm trong [data/README.md](../data/README.md).

## 3. Kiểm tra database và model

```bash
docker compose -p day6_student_starter up -d --wait
python scripts/check_setup.py
python scripts/check_embeddings.py
```

Database mở tại `127.0.0.1:55433`, volume `pg_data` lưu bền vững. Kỳ vọng `Setup OK` cùng phiên bản PostgreSQL/pgvector. Nếu cổng bận, sửa đồng thời port trong Compose và `DATABASE_URL`. `init.sql` chỉ chạy khi khởi tạo volume; không xóa volume đang có dữ liệu để sửa lỗi setup.

Vector và metadata nằm trong bảng `stroke_chunks`, khóa chính `(strategy, chunk_id)`. Cả bốn cấu hình dùng cosine exact search với toán tử `<=>`; C thêm điều kiện lọc `publication_year` trước khi xếp hạng. Không dùng index ANN. Đường dẫn embedding trong repo được lưu tương đối với root để có thể chuyển thư mục bài làm.

Lệnh check model cần trả về `BAAI/bge-m3`, CPU, **1.024 chiều** và `PASS`. Lệnh này dùng câu mẫu với giới hạn mặc định của model. Pipeline dùng **512 token**, FP32, batch 4 và chuẩn hóa vector theo `configs/lab.json`.

Khi tài liệu thay đổi, cập nhật PDF và manifest tương ứng (checksum, trang, số ký tự, metadata), kiểm chứng lại gold rồi chạy `prepare` → `embed` → `ingest` cho phiên bản mới. `prepare` tạo ID theo hash đầu vào và mã nguồn. `ingest` thay toàn bộ dữ liệu của từng cấu hình trong một transaction, loại chunk cũ thay vì cộng dồn; nạp lại cùng phiên bản không tăng số bản ghi. Giữ kết quả phiên bản trước để truy vết, và tuân thủ quy tắc dev/test khi thay tài liệu hoặc gold.

Khi model đã tải đầy đủ vào cache, có thể kiểm tra offline trên Bash:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python scripts/check_embeddings.py
```

Dừng database và giữ dữ liệu:

```bash
docker compose -p day6_student_starter stop
```

## 4. Luồng thí nghiệm

Xem danh sách lệnh:

```bash
python -m src.run --help
```

Các lệnh dưới đây dành cho **một lần chạy mới, trên corpus/benchmark đã chốt trước thử nghiệm**, từ `starter/`:

```bash
python -m src.run prepare
python -m src.run embed --device cpu --output ../artifacts/embeddings
python -m src.run ingest --embeddings ../artifacts/embeddings
python -m src.run dev
python -m src.run select
python -m src.run test
python -m src.run audit
```

Một lượt chạy mới cần thư mục làm việc riêng không chứa `results/` của lượt đã ghi. Pipeline chặn chạy lại dev/chọn cấu hình sau khi đã có trace test; quy tắc dev/test theo [BENCHMARK.md](../BENCHMARK.md). Với repo đã có kết quả, dùng lệnh tái lập ở mục 6 để giữ nguyên bản gốc.

Sau khi dữ liệu và model đã sẵn trong cache, có thể thêm `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1` trước lệnh `prepare` và `embed` trên Bash để chạy không cần mạng.

Benchmark dùng 20 dev / 5 test (`q21–q25`). Test cũ `q16–q20` đã chuyển sang dev sau khi được xem. C được chọn trên dev trước khi chạy test mới; cả hai tập đã chạy xong.

Cấu hình gồm **A/B/C và semantic D**. D dùng embedding cửa sổ câu (buffer 1), ngưỡng percentile 90 và tối thiểu 100 ký tự trước mỗi lần cắt theo ngữ nghĩa. Giới hạn vẫn là 500 ký tự, overlap 0 như B. D không dùng filter; B–C chỉ khác filter. Chi tiết nằm trong `configs/lab.json` và `benchmark/protocol.json`.

`prepare` dùng BGE-M3 để tìm điểm chia cho D từ text nguồn, không dùng câu hỏi hay gold. Bước này cần model và có thời gian xử lý riêng. `semantic_D.json` và `semantic_D.npz` lưu cửa sổ câu, offset, vector và số liệu xử lý. Câu được tách bằng regex; câu dài vẫn có thể bị cắt để giữ giới hạn chunk.

`audit` xuất biểu mẫu chấm coherence, metadata và grounding. Sau khi điền điểm, lý do và reviewer:

```bash
python -m src.run summarize-audits
```

| Thành phần | Vị trí tính từ root repo |
|---|---|
| Manifest/quyền/trang | `data/manifest.json`, `data/README.md` |
| Cấu hình | `configs/lab.json` |
| Câu hỏi, gold, protocol | `benchmark/` |
| Trang/chunk, mẫu coherence, lỗi đọc | `artifacts/prepared/<prepared_id>/` |
| Vector và môi trường embedding | `artifacts/embeddings/` |
| Trace, metric dev/test, lựa chọn, audit | `results/<prepared_id>/` |
| Lỗi lệnh pipeline | `results/errors.jsonl` nếu có lỗi |

## 5. Kết quả thực nghiệm

Lượt hiện tại dùng 67 trang, tạo 241 chunk cho A, 252 cho B/C và 273 cho D. C được chọn trên dev; test Hit@3 của A là 3/5, B/C/D là 5/5. Các lần nạp lại giữ nguyên số bản ghi.

[Báo cáo cá nhân](../report/individual/2A202604020_NguyenDucKhuongLam.md) trình bày bảng so sánh, audit và phân tích lỗi. Chi tiết thực chạy nằm trong [log embedding](../artifacts/embeddings/embedding_run.json) và [kết quả tổng hợp](../results/c5d3358834ca1f25c699/comparison.json).

## 6. Tái lập kết quả truy xuất

Sau khi cài môi trường và khởi động PostgreSQL, từ `starter/`:

```bash
python scripts/reproduce_retrieval.py --output /tmp/day06-replay
```

`--output` phải là thư mục chưa tồn tại; trên Windows dùng một đường dẫn mới phù hợp. Script chạy `ingest` → `dev` → `select` → `test` trong thư mục và database riêng, rồi so sánh chỉ số, ID top-3 và cấu hình được chọn với kết quả gốc. Database tạm tự xóa; kết quả chạy lại nằm ở `--output`. Tài khoản cần quyền tạo database, có sẵn trong cấu hình Docker của lab.

Lệnh dùng lại vector và bộ câu hỏi đã lưu, có kiểm tra checksum, nên không cần tải PDF/model. Để chạy từ PDF và tạo embedding lại, làm theo mục 2 và 4 trong thư mục mới chỉ chứa code, config, benchmark và dữ liệu.

Các quy định về corpus, benchmark, AI và bài nộp vẫn theo [GUIDE.md](../GUIDE.md), [RULES.md](../RULES.md) và [SUBMISSION.md](../SUBMISSION.md).
