# Chạy pipeline · PostgreSQL + pgvector

Pipeline trong `src/` đọc PDF, chuẩn hóa, chia chunk, tạo embedding, lưu vector và đánh giá truy xuất. Bản hiện tại chạy **Python 3.12, BAAI/bge-m3 trên CPU, PostgreSQL 16 + pgvector**. Cấu hình cố định ở [configs/lab.json](../configs/lab.json), dữ liệu ở root `data/`.

## 1. Cài môi trường local

Cần Python **3.12**, Docker Engine/Desktop + Compose và [uv](https://docs.astral.sh/uv/getting-started/installation/). Python 3.12 là phiên bản đã kiểm tra với lock hiện tại; lần cài dependencies và tải model đầu cần mạng. Các lệnh sau chạy từ `starter/`:

```bash
cd starter
python3.12 -m venv .venv
source .venv/bin/activate
uv pip sync --python .venv/bin/python --torch-backend cpu requirements-local.lock
```

Trên Windows PowerShell: dùng `py -3.12 -m venv .venv`, kích hoạt bằng `.venv\Scripts\Activate.ps1`, thay đường dẫn Python trong lệnh uv bằng `.venv\Scripts\python.exe`.

`requirements-local.lock` ghi các phiên bản môi trường CPU đã dùng; `requirements-local.txt` là đầu vào để tạo lock. `requirements.txt` chứa thư viện đọc PDF/database.

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

`check_corpus.py` đọc lại PDF bằng mã ingestion, kiểm tra checksum, số trang, phân loại chọn/loại, số ký tự từng trang và tổng manifest. Kỳ vọng: `PASS`, **5 tài liệu / 83 trang vật lý / 67 trang được chọn / 95.535 ký tự**. Bốn trang rỗng đều bị loại; không có trang được chọn bị lỗi. Ý nghĩa nội dung và căn cứ quyền được ghi riêng trong [data/README.md](../data/README.md).

## 3. Kiểm tra database và model

```bash
docker compose -p day6_student_starter up -d --wait
python scripts/check_setup.py
python scripts/check_embeddings.py
```

Database mở tại `127.0.0.1:55433`, volume `pg_data` lưu bền vững. Kỳ vọng `Setup OK` cùng phiên bản PostgreSQL/pgvector. Nếu cổng bận, sửa đồng thời port trong Compose và `DATABASE_URL`. `init.sql` chỉ chạy khi khởi tạo volume; không xóa volume đang có dữ liệu để sửa lỗi setup.

Vector và metadata nằm trong bảng `stroke_chunks`, khóa chính `(strategy, chunk_id)`. Cả bốn cấu hình dùng cosine exact search với toán tử `<=>`; C thêm điều kiện lọc `publication_year` trước khi xếp hạng. Không dùng index ANN. Đường dẫn embedding trong repo được lưu tương đối với root để có thể chuyển thư mục bài làm.

Model check kỳ vọng `BAAI/bge-m3`, CPU, **1.024 chiều** và `PASS`. Kiểm tra này dùng câu mẫu và giới hạn mặc định của model; pipeline thí nghiệm dùng **512 token**, FP32, batch 4 và vector chuẩn hóa theo `configs/lab.json`.

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

Xem các lệnh thực tế:

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

Phiên bản benchmark hiện tại dùng 20 dev / 5 test (`q21–q25`). Test cũ `q16–q20` đã chuyển sang dev sau khi được xem. Lượt hiện tại đã chạy đủ dev và test; C được chốt trên dev trước khi chạy test. Kết quả cũ nằm riêng dưới prepared ID cũ.

Cấu hình hiện tại gồm **A/B/C và semantic D**. D đo khoảng cách cosine giữa embedding các cửa sổ câu (buffer 1), dùng ngưỡng percentile 90 trên corpus, tối thiểu 100 ký tự trước khi cắt do ngữ nghĩa và giới hạn 500 ký tự/overlap 0 như B. D không áp dụng filter; B–C vẫn chỉ thay filter. Model, corpus, gold và cách chia dev/test giữ nguyên; xem `strategy_extension` trong `benchmark/protocol.json`.

`prepare` chạy thêm BGE-M3 trên CPU để xác định ranh giới semantic từ nguồn, không dùng câu hỏi/gold. Model phải có sẵn hoặc tải được. `semantic_D.json` và `semantic_D.npz` trong thư mục prepared lưu cửa sổ/offset, khoảng cách, ngưỡng, vector nguồn và thời gian thực chạy. Chi phí bước này được ghi riêng với embedding các chunk dùng truy xuất. Ranh giới câu dùng regex, câu quá dài có thể bị chia để giữ giới hạn; không bảo đảm mọi chunk trọn ý.

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

`--output` phải là thư mục chưa tồn tại; trên Windows chọn một đường dẫn mới phù hợp. Script sao chép code, cấu hình, benchmark và các vector thật đã lưu sang thư mục riêng, tạo database tạm trên cùng PostgreSQL rồi chạy `ingest` → `dev` → `select` → `test`. Sau đó đối chiếu toàn bộ chỉ số, ID top-3 và lựa chọn cấu hình với kết quả đã nộp. Database tạm được xóa; kết quả tái lập giữ tại `--output`, không ghi đè index hay kết quả gốc. Tài khoản database cần quyền tạo database; cấu hình Docker mặc định của lab có quyền này.

Lệnh này không mã hóa lại và không cần tải PDF/model; danh tính/checksum của bộ vector được kiểm tra trước khi dùng. Đây là tái chạy cùng thí nghiệm đã cố định, không phải tập test độc lập mới. Để tái tạo từ PDF và mã hóa lại, lấy corpus theo mục 2 rồi chạy luồng đầy đủ ở mục 4 trong thư mục làm việc mới chỉ chứa code, config, benchmark và dữ liệu.

Các quy định về corpus, benchmark, AI và bài nộp vẫn theo [GUIDE.md](../GUIDE.md), [RULES.md](../RULES.md) và [SUBMISSION.md](../SUBMISSION.md).
