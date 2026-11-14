# Báo cáo cá nhân — Day 06

**Học viên:** Nguyễn Đức Khương Lam · **MSSV:** 2A202604020 · **Lớp:** K5/L3B

**Chủ đề:** Kiến thức về đột quỵ từ tài liệu NINDS/NIH

## Dữ liệu và pipeline

Bộ dữ liệu gồm 5 PDF tiếng Anh của NINDS/NIH về nhận biết, phòng ngừa và phục hồi sau đột quỵ. Chọn 67 trang nội dung trong tổng số 83 trang, loại bìa, mục lục, trang trống và danh bạ liên hệ. Số trang trong kết quả tính theo trang PDF, bắt đầu từ 1.

Văn bản do NINDS biên soạn thuộc public domain. Pipeline chỉ xử lý text, không lấy hình ảnh. [Manifest](../../data/manifest.json) ghi nguồn, quyền sử dụng và các trang được chọn. PDF gốc lưu local và không đưa lên Git; cách tải nằm trong [data/README.md](../../data/README.md).

Pipeline đọc PDF bằng `pypdf`, chuẩn hóa Unicode NFC và gộp khoảng trắng trước khi chia chunk. Cả 67 trang đều đọc được text, không cần OCR. Dữ liệu vẫn còn header/footer và một số lỗi khoảng trắng do bố cục PDF.

Mỗi chunk lưu ID tài liệu, nguồn, trang và offset trên text đã chuẩn hóa để tra lại nguồn. Metadata bổ sung gồm năm xuất bản, loại tài liệu, chủ đề, ngôn ngữ và quốc gia. Năm xuất bản lấy từ thông tin in trong PDF; chủ đề được gán theo tiêu đề. Trường `publication_year` dùng làm filter khi câu hỏi nêu năm cụ thể.

Embedding dùng **BAAI/bge-m3**, vector 1.024 chiều, chạy local trên CPU với FP32, tối đa 512 token và chuẩn hóa L2. Vector lưu trong **PostgreSQL 16.16 + pgvector 0.8.7**, dùng cosine exact search. Nạp lại cùng phiên bản không tạo bản ghi trùng; dữ liệu vẫn còn sau khi khởi động lại database. Phiên bản model và môi trường nằm trong [log embedding](../../artifacts/embeddings/embedding_run.json).

## Cấu hình và benchmark

| Cấu hình | Cách chia chunk | Giới hạn / overlap | Filter |
|---|---|---|---|
| A | Cửa sổ cố định | 500 / 50 ký tự | Không |
| B | Ưu tiên đoạn và câu | 500 / 0 ký tự | Không |
| C | Giữ nguyên chunk và vector của B | Giống B | Năm xuất bản |
| D | Semantic chunking | 500 / 0 ký tự | Không |

D so sánh embedding của các cửa sổ câu liền kề, lấy percentile 90 của cosine distance làm ngưỡng chia. Cách làm tham khảo [SemanticChunker](https://github.com/langchain-ai/langchain-experimental/blob/main/libs/experimental/langchain_experimental/text_splitter.py); tham số đầy đủ nằm trong [cấu hình](../../configs/lab.json).

[Benchmark](../../benchmark/questions.json) gồm **20 câu dev và 5 câu test**, có câu hỏi trực tiếp, diễn đạt lại và kèm điều kiện. Có 7 câu dùng filter năm, gồm 5 dev và 2 test. Đáp án và evidence đã được đối chiếu với trang nguồn. Khi tạo query embedding, model chỉ nhận câu hỏi.

Năm câu test cũ đã được xem trong quá trình thử nghiệm nên được chuyển sang dev, thay bằng `q21–q25`. Quy tắc chọn cấu hình ưu tiên dev Hit@3, rồi Hit@1; nếu bằng nhau thì chọn cấu hình ít chunk hơn, cuối cùng xét ID. **C được chốt trước khi chạy test mới.** Lịch sử và lựa chọn nằm trong [protocol](../../benchmark/protocol.json) và [selection](../../results/c5d3358834ca1f25c699/selection.json).

## Kết quả

Hit@1 xét chunk đầu tiên, Evidence Hit@3 xét top-3. Một hit phải đúng nguồn, đúng trang và chứa đủ evidence trong một chunk. Grounding đánh giá bằng chứng từ toàn bộ top-3.

| Cấu hình | Dev Hit@1 | Dev Hit@3 | Test Hit@1 | Test Hit@3 | Số chunk |
|---|---|---|---|---|---:|
| A | 13/20 | 17/20 | 3/5 | 3/5 | 241 |
| B | 17/20 | 17/20 | 5/5 | 5/5 | 252 |
| C | 17/20 | 18/20 | 5/5 | 5/5 | 252 |
| D | 15/20 | 17/20 | 5/5 | 5/5 | 273 |

Coherence được chấm tại cùng 10 vị trí trong tài liệu cho mỗi cấu hình. Metadata được kiểm tra trên top-3 của 5 câu test; grounding chấm 5 câu này theo thang 0–2. Mỗi mẫu có điểm và lý do chấm.

| Cấu hình | Coherence /2 (10 mẫu) | Metadata đủ và đúng | Tuân thủ filter | Grounding: số câu điểm 0 / 1 / 2 | Trung bình /2 |
|---|---:|---|---|---|---:|
| A | 1,00 | 15/15 | 1/2 | 0 / 0 / 5 | 2,00 |
| B | 1,80 | 15/15 | 1/2 | 0 / 0 / 5 | 2,00 |
| C | 1,80 | 15/15 | 2/2 | 0 / 0 / 5 | 2,00 |
| D | 1,80 | 15/15 | 1/2 | 0 / 0 / 5 | 2,00 |

Ở `q22` và `q23`, A cần ghép hai chunk mới đủ trả lời. Hai câu này đạt grounding 2 nhưng Hit@3 vẫn bằng 0 vì không có chunk nào đủ evidence riêng.

Kết quả và trace nằm trong [dev](../../results/c5d3358834ca1f25c699/dev/) và [test](../../results/c5d3358834ca1f25c699/test/); nhãn cùng cách chọn mẫu nằm trong [audits](../../results/c5d3358834ca1f25c699/audits/).

| Cấu hình | Embedding chunk (giây) | Embedding để chia chunk (giây) |
|---|---:|---:|
| A | 94,6 | 0 |
| B | 92,3 | 0 |
| C | Dùng lại B | 0 |
| D | 96,4 | 249,2 |

Nạp vector mất khoảng 0,4 giây mỗi cấu hình; embedding cho 25 câu hỏi mất 2,4 giây. Truy xuất trung bình khoảng 23–24 ms/câu, chưa tính bước embedding câu hỏi. Chi phí dịch vụ là **0 USD** do chạy local, không tính điện, phần cứng và mạng. Thời gian được đo trong một lượt chạy trên một máy; chi tiết có trong [bảng tổng hợp](../../results/c5d3358834ca1f25c699/comparison.json).

## Phân tích và kết luận

B tốt hơn A về Hit@1 và coherence trên các mẫu đã chấm. Hai cấu hình khác cả cách chia chunk lẫn overlap nên chưa tách được ảnh hưởng của từng yếu tố. B ưu tiên chia theo đoạn và câu nhưng vẫn phải cắt câu dài nếu vượt giới hạn.

So với B, C chỉ thêm filter năm và tăng dev Hit@3 từ 17/20 lên 18/20. Khác biệt nằm ở `q09`: C lấy đủ ba mục tiêu phục hồi trong tài liệu năm 2024 mà B bỏ lỡ. Với câu test `q21` yêu cầu năm 2020, C loại được các hit năm 2024. Những hit này có metadata đúng nhưng sai phạm vi câu hỏi.

D tạo nhiều chunk hơn và tốn thêm thời gian embedding cửa sổ câu, nhưng dev Hit@1 thấp hơn B và Hit@3 không tăng. **C được chọn vì có dev Hit@3 cao nhất**, dùng lại vector của B và lọc đúng năm khi cần. B/C/D đều đạt 5/5 trên test; D chưa cho thấy cải thiện trên tập này.

Hai lỗi điển hình của A:

- **q22 — apraxia, Post-Stroke Rehabilitation, trang PDF 9:** định nghĩa bị tách giữa hai chunk. Không chunk nào đủ bằng chứng riêng; B/C/D giữ được định nghĩa trong top-1.
- **q23 — vocational therapists, cùng tài liệu, trang PDF 12:** một chunk có tên chuyên gia nhưng thiếu nhiệm vụ, chunk còn lại có nhiệm vụ nhưng tên bị cắt. B/C/D giữ được cả hai phần trong một chunk.

Test chỉ có 5 câu từ *Post-Stroke Rehabilitation*, cũng là tài liệu dùng trong dev, nên kết quả 5/5 chưa đủ để kết luận trên nguồn khác. Mẫu coherence còn ít; việc xây benchmark và chấm nhãn trong cùng quy trình cũng có thể gây thiên lệch. Có thể cải thiện bằng cách thêm test trên tài liệu mới, lấy mẫu coherence rộng hơn và so sánh các cách chia với cùng overlap.

Hướng dẫn chạy và tái lập kết quả nằm trong [starter/README.md](../../starter/README.md). Codex hỗ trợ viết mã và đối chiếu nội dung; số liệu được kiểm tra từ log thực chạy, trace và trang nguồn.
