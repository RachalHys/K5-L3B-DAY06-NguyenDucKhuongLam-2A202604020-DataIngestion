# Corpus NINDS/NIH

## Chủ đề và nguồn

Chủ đề: kiến thức về đột quỵ — nhận biết, phòng ngừa, phục hồi chức năng và tìm hiểu/tham gia nghiên cứu. Corpus tiếng Anh, ngữ cảnh Hoa Kỳ, do **National Institute of Neurological Disorders and Stroke (NINDS), National Institutes of Health (NIH)** xuất bản.

[manifest.json](manifest.json) ghi URL nguồn từng tài liệu, ngày truy cập 2026-11-14, đường dẫn local, SHA-256, ngày xuất bản, trang chọn/loại, lý do loại và số ký tự từng trang. Có thể tra cứu ấn phẩm trong [danh mục NINDS](https://www.ninds.nih.gov/publications). Năm 2020/2024 lấy từ thông tin in trong PDF, không lấy từ năm trong URL tải lên.

| Tài liệu | Xuất bản | Trang vật lý | Trang được chọn (trang vật lý từ 1) |
|---|---|---:|---|
| Stroke: Hope Through Research | 02/2020 | 56 | 5–51: 47 trang |
| Post-Stroke Rehabilitation | 04/2020 | 24 | 3–19: 17 trang |
| Know Stroke: See the Signs. Act F.A.S.T. | 05/2024 | 1 | 1 |
| Know Stroke: Take Preventive Action | 05/2024 | 1 | 1 |
| Know Stroke: Recovery Through Rehabilitation | 05/2024 | 1 | 1 |
| **Tổng** | | **83** | **67** |

## Quyền sử dụng

Căn cứ: [NINDS Publications Help — Copyright and Use of NINDS Materials](https://www.ninds.nih.gov/publications/publications-help). Thông tin do NINDS chuẩn bị thuộc public domain; hình ảnh có hướng dẫn quyền sử dụng riêng. Trang 2 của *Stroke: Hope Through Research* cũng có thông báo public domain cho phần thông tin.

PDF gốc tải từ URL NINDS trong manifest, chỉ lưu local và không commit. Repo gồm manifest, script và văn bản đã xử lý, có ghi nguồn NINDS/NIH. Pipeline không lấy hình ảnh.

## Lấy lại dữ liệu

Từ root repo, script tải chỉ cần thư viện chuẩn Python:

```bash
python3 starter/scripts/fetch_data.py
```

Script đọc URL và đường dẫn từ manifest, tải file còn thiếu rồi kiểm tra SHA-256. File local đúng checksum được dùng lại; file sai không bị ghi đè. Script không tự sửa manifest nếu nguồn thay đổi.

Lần kiểm tra ngày 14/11/2026, cả 5 URL trả HTTP 403 nên chưa kiểm tra được việc tải lại PDF. Nếu gặp lỗi này, tìm tài liệu trong [danh mục NINDS](https://www.ninds.nih.gov/publications); ba factsheet có trang [nhận biết](https://www.ninds.nih.gov/health-information/stroke/signs-and-symptoms), [phòng ngừa](https://www.ninds.nih.gov/health-information/stroke/prevention) và [phục hồi](https://www.ninds.nih.gov/health-information/stroke/recovery). Lưu PDF đúng tên vào `data/raw/stroke-awareness/`, rồi kiểm tra:

```bash
python3 starter/scripts/fetch_data.py --verify-only
```

Checksum của 5 PDF local đã khớp manifest. Nếu nguồn trả phiên bản khác, bước kiểm tra sẽ báo lỗi.

Sau khi cài môi trường theo [starter/README.md](../starter/README.md), từ root:

```bash
starter/.venv/bin/python starter/scripts/check_corpus.py
```

Trên Windows dùng `python starter/scripts/check_corpus.py` với môi trường đã kích hoạt.

## Quy tắc tính và truy vết trang

- Số trang là **trang PDF vật lý, từ 1**, không phải số in ở chân trang sách.
- Loại bìa, mục lục, trang thông báo xuất bản/quyền, trang trống và danh bạ chỉ có thông tin liên hệ. Manifest ghi lý do từng trang.
- Đếm trang nội dung thực liên quan đến chủ đề; không nhân bản hoặc chia lại PDF để đủ số lượng. Điều kiện 1.500 ký tự trong GUIDE dành cho cách chia nguồn không phân trang, không áp dụng cho từng trang PDF.
- Trích xuất bằng `pypdf`, sau đó chuẩn hóa Unicode NFC, gộp khoảng trắng trong đoạn và giữ ngắt đoạn trống. Tổng **95.535 ký tự**, bao gồm header/footer.
- Bốn trang rỗng: overview trang 55; rehabilitation trang 2, 22, 23. Tất cả đều bị loại. 67 trang được chọn có text đọc được; không dùng OCR.

Trang 50–51 của *Stroke: Hope Through Research* được giữ vì có nội dung hướng dẫn tra cứu và tham gia nghiên cứu đột quỵ, dù kèm thông tin liên hệ.

## Metadata

Mỗi trang/chunk giữ `document_id`, `source`, trang vật lý; chunk có offset ký tự. `publication_year` là số nguyên lấy từ ngày in trong PDF, có giá trị 2020/2024 và dùng để lọc khi câu hỏi nêu năm. `document_type` phân biệt booklet/fact sheet; `topic` là nhãn phân loại theo tiêu đề do tác giả gán. Các trường còn lại: `language=en`, `country_context=US`.

Các tài liệu có nội dung giao nhau; nguy cơ trùng chủ đề giữa dev/test được ghi trong `benchmark/protocol.json`.
