# Individual Report 4 — Retrieval & Evaluation

## 1. Thông tin cá nhân

| Trường | Nội dung |
|---|---|
| Họ và tên | Nguyễn Xuân Thành |
| MSSV | 2A202602666 |
| Nhóm | LaoGaKho |
| Dự án | Data Pipeline & Data Observability |
| Vai trò được phân công | Retrieval & Evaluation |
| Ngày cập nhật | 26/9/2026 |

## 2. Phạm vi công việc

Phụ trách truy xuất tài liệu và đánh giá kết quả RAG. Scope này sở hữu các module trong `src/retrieval/` và `src/evaluation/`; pipeline orchestration do trưởng nhóm tích hợp.

| Module/deliverable | Tệp | Input | Output |
|---|---|---|---|
| Embedding và ChromaDB index | `src/retrieval/embeddings.py`, `index.py` | Clean DataFrame, embedding settings | Embeddings, collections và document metadata |
| Retrieval và trả lời | `src/retrieval/agent.py`, `qa.py`, `llm.py` | Câu hỏi và retrieved context | Retrieved document IDs và câu trả lời |
| Ground truth | `src/evaluation/testset.py` | Clean DataFrame | 10 câu hỏi cùng answer/doc ID chuẩn |
| Metrics | `src/evaluation/metrics.py` | Test set, retrieved IDs, answers | Hit rate, Token F1 và judge metrics |

## 3. Mục tiêu và tiêu chí hoàn thành

- Đảm bảo DOI trong `ground_truth_doc_ids` khớp đúng định dạng ID/metadata của tài liệu lưu trong ChromaDB.
- Kiểm tra từng test case: câu hỏi, ground truth, retrieved IDs và answer extraction.
- Dùng cùng một test set và cấu hình retrieval cho baseline, corrupted, repaired.
- Xác minh baseline có kết quả có ý nghĩa trước khi dùng các metric để tuyên bố suy giảm hoặc phục hồi.
- Ghi lại metric theo stage và nêu rõ khi evaluation chưa đủ cơ sở kết luận.

## 4. Kết quả/artifact hiện có

Repository có `data/eval/test_set.json` với 10 câu hỏi, cùng các file `data/results/baseline_metrics.json`, `corrupted_metrics.json`, `repaired_metrics.json` và embedding/index artifacts. Metrics hiện có đều ghi `retrieval_hit_rate=0.0` và `mean_token_f1=0.0`; judge accuracy cũng bằng 0.0.

Với baseline bằng 0, chưa thể dùng ba trạng thái để kết luận corruption làm giảm chất lượng RAG hay repair đã phục hồi chất lượng. Đây là lỗi/giới hạn ưu tiên cần chẩn đoán trong scope này.

## 5. Kế hoạch triển khai

1. Theo dõi một câu hỏi qua test set, query embedding, ChromaDB retrieval và answer generation.
2. So khớp `ground_truth_doc_ids` với document IDs thực tế và kiểm tra metadata mapping.
3. Rà soát test set: trường ground truth cho từng dạng summary/authors/date/categories có đúng với record nguồn hay không.
4. Rà soát Token F1 và judge input/normalization; thêm ghi vết giải thích được cho từng câu hỏi nếu cần.
5. Chạy baseline trước, xác nhận metrics hợp lý rồi mới so sánh corrupted/repaired.

## 6. Kiểm thử và bằng chứng cần lưu

| Kiểm tra | Bằng chứng cần có |
|---|---|
| Retrieval cho từng test case | Question, expected DOI, retrieved IDs và hit/miss |
| Ground truth | DOI và câu trả lời khớp raw/clean paper record |
| Token F1 | Answer, normalized tokens, precision/recall/F1 |
| So sánh ba stage | Ba metrics JSON dùng cùng test set/configuration |
| Tái lập | Lệnh chạy, exit code và artifact metrics sau lần chạy |

Chưa ghi nhận kiểm thử mới do cá nhân thực hiện trong báo cáo này. Sau khi sửa hoặc xác minh, bổ sung log per-case và metrics artifacts thực tế.

## 7. Kết quả pipeline liên quan

| Metric hiện có | Baseline | Corrupted | Repaired |
|---|---:|---:|---:|
| Samples | 10 | 10 | 10 |
| Retrieval hit rate | 0.0 | 0.0 | 0.0 |
| Mean token F1 | 0.0 | 0.0 | 0.0 |
| Judge accuracy | 0.0 | 0.0 | 0.0 |

Các con số này được ghi lại để làm hiện trạng debug. Không diễn giải chúng là hiệu năng thực tế của mô hình hoặc bằng chứng thành công của repair.

## 8. Phối hợp và ranh giới sở hữu

- Data Foundation & Recovery cung cấp clean records và schema `paper_id`/`text_for_embedding`.
- Observability & Reporting cung cấp quality/freshness signals và báo cáo stage.
- Pipeline Integrator cung cấp thứ tự chạy, settings và artifact paths.
- Scope này chịu trách nhiệm retrieval, test set và evaluation metrics; báo lỗi tích hợp qua owner pipeline thay vì sửa orchestration ngoài phạm vi.

## 9. Bài học kỹ thuật

Retrieval hit rate trả lời liệu hệ thống có tìm thấy tài liệu đúng, còn Token F1 phản ánh độ trùng khớp câu trả lời theo token. Hai metric cần ground truth đáng tin và ID nhất quán từ test set đến vector index. Một pipeline chạy hết các bước vẫn có thể tạo benchmark vô nghĩa nếu contract này lệch.

## 10. Checklist cá nhân

- [ ] Đã tự điền và xác nhận họ tên, MSSV.
- [x] Scope Retrieval & Evaluation đã được phân công trong `docs/TEAM.md`.
- [ ] Đã kiểm tra từng test case từ query đến retrieved document.
- [ ] Đã xác minh/sửa ground truth và metrics bằng bằng chứng.
- [ ] Đã chạy lại đủ baseline, corrupted, repaired với cùng benchmark.
- [ ] Đã cập nhật commit và bằng chứng đóng góp cá nhân.
- [ ] Không kết luận vượt quá artifacts; không đưa secret vào report.
