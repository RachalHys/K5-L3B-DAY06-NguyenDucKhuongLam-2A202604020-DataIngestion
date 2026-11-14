# Báo cáo cá nhân — Day 06

**Học viên:** Nguyễn Đức Khương Lam · **MSSV:** 2A202604020 · **Lớp:** K5/L3B

**Chủ đề:** Kiến thức về đột quỵ từ tài liệu NINDS/NIH

## Dữ liệu và pipeline

Bộ dữ liệu gồm 5 PDF tiếng Anh của NINDS/NIH về nhận biết, phòng ngừa và phục hồi sau đột quỵ. Trong 83 trang, có 67 trang nội dung được sử dụng sau khi loại bìa, mục lục, trang trống và danh bạ liên hệ. Số trang truy nguồn tính theo trang PDF, bắt đầu từ 1.

Phần văn bản do NINDS biên soạn thuộc public domain; bài làm chỉ xử lý văn bản, không trích xuất hình ảnh. Nguồn, quyền sử dụng và các trang được chọn có trong [manifest](../../data/manifest.json). PDF gốc được giữ ngoài Git; cách lấy dữ liệu và tình trạng truy cập nguồn được ghi tại [data/README.md](../../data/README.md).

Pipeline dùng `pypdf` để đọc tài liệu, chuẩn hóa Unicode NFC và gộp khoảng trắng trước khi chia chunk. Cả 67 trang được chọn đều trích xuất được văn bản, không cần OCR. Văn bản vẫn còn header/footer và một số lỗi khoảng cách do bố cục PDF.

Mỗi chunk lưu ID tài liệu, nguồn, trang và vị trí ký tự để truy vết. Metadata bổ sung gồm năm xuất bản, loại tài liệu, chủ đề, ngôn ngữ và quốc gia. Năm xuất bản lấy từ thông tin in trong PDF; chủ đề là nhãn phân loại theo tiêu đề. Trường `publication_year` được dùng để lọc khi câu hỏi yêu cầu một năm cụ thể.

Embedding sử dụng **BAAI/bge-m3**, 1.024 chiều, chạy local trên CPU, FP32, tối đa 512 token và chuẩn hóa L2. Vector được lưu bằng **PostgreSQL 16.16 + pgvector 0.8.7**, truy xuất theo cosine exact search. Dữ liệu được giữ sau khi khởi động lại database; nạp lại cùng phiên bản không tạo bản ghi trùng. Phiên bản model và môi trường được ghi trong [log embedding](../../artifacts/embeddings/embedding_run.json).

## Cấu hình và benchmark

| Cấu hình | Cách chia chunk | Giới hạn / overlap | Filter |
|---|---|---|---|
| A | Cửa sổ cố định | 500 / 50 ký tự | Không |
| B | Ưu tiên đoạn và câu | 500 / 0 ký tự | Không |
| C | Giữ nguyên chunk và vector của B | Giống B | Năm xuất bản |
| D | Semantic, chọn ranh giới theo độ thay đổi ngữ nghĩa giữa các cửa sổ câu | 500 / 0 ký tự | Không |

D dùng cùng model BGE-M3, buffer 1, ngưỡng percentile 90 và tối thiểu 100 ký tự trước khi cắt theo ngữ nghĩa. Cách làm tham khảo [SemanticChunker](https://github.com/langchain-ai/langchain-experimental/blob/main/libs/experimental/langchain_experimental/text_splitter.py), với phần triển khai giữ trang và vị trí nguồn. Tham số đầy đủ nằm trong [cấu hình](../../configs/lab.json).

[Benchmark](../../benchmark/questions.json) gồm **20 câu dev và 5 câu test**, có câu hỏi trực tiếp, diễn đạt lại và kèm điều kiện. Trong 7 câu yêu cầu lọc theo năm, 5 câu thuộc dev và 2 câu thuộc test. Đáp án và bằng chứng đã được đối chiếu với trang nguồn; nội dung đưa vào embedding chỉ gồm câu hỏi.

Năm câu test cũ đã được xem trong quá trình thử nghiệm nên được chuyển sang dev, thay bằng `q21–q25`. Cấu hình được chọn theo dev Hit@3, sau đó Hit@1, số chunk ít hơn và ID cấu hình. **C được chốt trước khi chạy test mới.** Lịch sử thay đổi và lựa chọn được lưu trong [protocol](../../benchmark/protocol.json) và [selection](../../results/c5d3358834ca1f25c699/selection.json).

## Kết quả

Hit@1 và Evidence Hit@3 yêu cầu một chunk đúng nguồn, đúng trang và chứa đủ bằng chứng. Grounding xét khả năng trả lời từ toàn bộ top-3.

| Cấu hình | Dev Hit@1 | Dev Hit@3 | Test Hit@1 | Test Hit@3 | Số chunk |
|---|---|---|---|---|---:|
| A | 13/20 | 17/20 | 3/5 | 3/5 | 241 |
| B | 17/20 | 17/20 | 5/5 | 5/5 | 252 |
| C | 17/20 | 18/20 | 5/5 | 5/5 | 252 |
| D | 15/20 | 17/20 | 5/5 | 5/5 | 273 |

Coherence được chấm trên cùng 10 vị trí nguồn cho mỗi cấu hình. Metadata được kiểm tra trên top-3 của 5 câu test; grounding chấm 5 câu này theo thang 0–2. Mỗi mẫu đều có điểm và lý do đối chiếu.

| Cấu hình | Coherence /2 (10 mẫu) | Metadata đủ và đúng | Tuân thủ filter | Grounding: số câu điểm 0 / 1 / 2 | Trung bình /2 |
|---|---:|---|---|---|---:|
| A | 1,00 | 15/15 | 1/2 | 0 / 0 / 5 | 2,00 |
| B | 1,80 | 15/15 | 1/2 | 0 / 0 / 5 | 2,00 |
| C | 1,80 | 15/15 | 2/2 | 0 / 0 / 5 | 2,00 |
| D | 1,80 | 15/15 | 1/2 | 0 / 0 / 5 | 2,00 |

A vẫn đạt grounding 2 ở `q22` và `q23` vì ghép hai chunk có thể trả lời đủ, dù từng chunk riêng bị thiếu bằng chứng. Vì vậy, điểm grounding này không làm thay đổi Hit@3.

Kết quả và trace nằm trong [dev](../../results/c5d3358834ca1f25c699/dev/) và [test](../../results/c5d3358834ca1f25c699/test/); nhãn cùng cách chọn mẫu nằm trong [audits](../../results/c5d3358834ca1f25c699/audits/).

| Cấu hình | Embedding chunk (giây) | Mã hóa thêm để chọn ranh giới (giây) |
|---|---:|---:|
| A | 94,6 | 0 |
| B | 92,3 | 0 |
| C | Dùng lại B | 0 |
| D | 96,4 | 249,2 |

Nạp vector mất khoảng 0,4 giây mỗi cấu hình; mã hóa 25 câu hỏi mất 2,4 giây. Lookup trung bình khoảng 23–24 ms/câu, chưa tính mã hóa câu hỏi. Chi phí dịch vụ là **0 USD** do chạy local, không tính điện, phần cứng và mạng. Đây là một lượt đo trên một máy; số liệu chi tiết có trong [bảng tổng hợp](../../results/c5d3358834ca1f25c699/comparison.json).

## Phân tích và kết luận

B có kết quả tốt hơn A về Hit@1 và coherence trong các mẫu đánh giá. Tuy nhiên, hai cấu hình khác cả cách chia lẫn overlap nên chưa tách được ảnh hưởng của từng yếu tố. B ưu tiên ranh giới câu nhưng vẫn có thể phải cắt câu dài để giữ giới hạn kích thước.

So với B, C chỉ thêm filter theo năm và tăng dev Hit@3 từ 17/20 lên 18/20. Mức tăng đến từ `q09`: C lấy được đủ ba mục tiêu phục hồi trong tài liệu năm 2024 mà B bỏ lỡ. Ở câu test `q21`, C cũng loại được nội dung năm 2024 khi câu hỏi yêu cầu năm 2020. Metadata đúng vẫn cần đi cùng phạm vi phù hợp với câu hỏi.

D tạo nhiều chunk hơn và cần thêm thời gian mã hóa nguồn, trong khi dev Hit@1 thấp hơn B và Hit@3 không tăng. **C là lựa chọn phù hợp cho bộ dữ liệu này**: có dev Hit@3 cao nhất, dùng lại vector của B và lọc đúng năm khi cần. Test của B/C/D đều đạt 5/5, chưa cho thấy lợi thế riêng của semantic chunking.

Hai lỗi điển hình của A:

- **q22 — apraxia, Post-Stroke Rehabilitation, trang PDF 9:** định nghĩa bị tách giữa hai chunk. Không chunk nào đủ bằng chứng riêng; B/C/D giữ được định nghĩa trong top-1.
- **q23 — vocational therapists, cùng tài liệu, trang PDF 12:** một chunk có tên chuyên gia nhưng thiếu nhiệm vụ, chunk còn lại có nhiệm vụ nhưng tên bị cắt. B/C/D giữ được cả hai phần trong một chunk.

Tập test chỉ có 5 câu, đều tập trung vào *Post-Stroke Rehabilitation* và dùng chung tài liệu với dev, nên kết quả 5/5 chưa đủ để khái quát. Mẫu coherence cũng chưa bao phủ toàn bộ dữ liệu. Việc xây benchmark và đối chiếu nhãn trong cùng quy trình có thể gây thiên lệch. Hướng cải thiện là bổ sung test trên tài liệu mới, lấy mẫu coherence rộng hơn và so sánh các cách chia với cùng overlap.

Hướng dẫn chạy và tái lập kết quả nằm trong [starter/README.md](../../starter/README.md). Codex hỗ trợ viết mã và đối chiếu nội dung; số liệu được kiểm tra từ log thực chạy, trace và trang nguồn.
