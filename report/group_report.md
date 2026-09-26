# Group Report — Day 10: Data Pipeline & Data Observability

## 1. Thông tin bài nộp

| Thông tin | Nội dung |
| --- | --- |
| Khóa/Lớp | K4-L3B |
| Tên nhóm | LaoGaKho |
| Repository | `K4-L3B-DAY10-LaoGaKho-DataPipelineDataObservability` |
| Ngày chạy artifacts | 2026-09-26 |

### Thành viên và phân công

| STT | Họ và tên | MSSV | Vai trò chính | Module/deliverable sở hữu | Báo cáo cá nhân |
| --: | --- | --- | --- | --- | --- |
| 1 | Nguyễn Văn Xuân Lộc | 2A202602870 | Trưởng nhóm / Pipeline Integrator | `core/`, `src/pipelines/phase1.py`, `src/pipelines/corruption_flow.py` | `report/2A202602870_NguyenVanXuanLoc.md` |
| 2 | Bùi Hải Nam | 2A202602636 | Data Foundation & Recovery | `src/ingestion/crossref.py`, `src/ingestion/cleaning.py`, raw/clean artifacts | `report/2A202602636_BuiHaiNam.md` |
| 3 | Nguyễn Xuân Thành | 2A202602666 | Observability & Reporting | `src/observability/quality.py`, `reporting.py`, `diff.py` | `report/individual_report_3.md` |
| 4 | Lê Đức Hùng | 2A202602849 | Retrieval & Evaluation | `src/retrieval/`, `src/evaluation/` | `report/individual_report_4.md` |

## 2. Tóm tắt kết quả

Nhóm đã chạy được luồng dữ liệu từ Crossref đến raw response/raw records, cleaned dataset, embedding manifest và ChromaDB, test set, quality/freshness reports, baseline evaluation, corruption, repair và báo cáo so sánh. Baseline tạo 24 record sạch và bộ test 10 câu. Great Expectations baseline pass: 24 dòng, không null `paper_id`/title, không DOI trùng và độ dài summary trung bình 241.875 ký tự. Freshness baseline pass với 0/24 record cũ hơn ngưỡng 180 ngày.

Corruption log ghi đủ sáu scenario: drop latest records, blank summary, inject noise, truncate title, stale date và duplicate row. Repaired state được dựng lại từ raw snapshot; quality và freshness repaired đều pass, số dòng trở về 24. Tuy nhiên, baseline, corrupted và repaired đều có `retrieval_hit_rate=0.0` và `mean_token_f1=0.0`. Vì vậy artifacts hiện tại chứng minh được data pipeline, quality gate và repair flow hoạt động, nhưng chưa chứng minh định lượng được ảnh hưởng corruption đến RAG. Đây là giới hạn quan trọng cần sửa bằng cách kiểm tra test-set/ground-truth và QA/index contract trước khi kết luận về Silent Failure.

## 3. Kiến trúc và luồng dữ liệu

```text
Crossref API / offline snapshot
    -> data/raw/crossref_response.json
    -> data/raw/crossref_records.json
    -> cleaning + data modeling
    -> data/clean/papers_clean.*
    -> MiniLM embeddings + ChromaDB
    -> fixed data/eval/test_set.json
    -> baseline evaluation + quality/freshness
    -> six corruption scenarios
    -> corrupted evaluation + quality/freshness
    -> repair from raw snapshot
    -> repaired evaluation + comparison report
```

| Khối | Input | Xử lý chính | Output/artifact | Owner |
| --- | --- | --- | --- | --- |
| Ingestion | Crossref/snapshot | Fetch, retry, fallback, parse | `data/raw/` | Bùi Hải Nam |
| Cleaning | `PaperRecord` | Normalize, dedupe, `age_days`, embedding text | `data/clean/` | Bùi Hải Nam |
| Embedding/index | Clean DataFrame | MiniLM + ChromaDB collections | `data/embeddings/`, `data/chroma/` | Lê Đức Hùng |
| Evaluation | Test set + index | Retrieval hit rate, Token F1, judge metrics | `data/results/*metrics.json` | Lê Đức Hùng |
| Observability | DataFrame | GX checks, Freshness SLA, stage comparison/report | `data/quality/`, `data/reports/` | Nguyễn Xuân Thành |
| Corruption/repair | Clean/raw data | Six corruptions, rebuild from raw | Corruption log, repaired data | Pipeline Integrator |
| Orchestration | All artifacts | Baseline and Phase 2 order | `data/reports/` | Nguyễn Văn Xuân Lộc |

## 4. Cách tái hiện kết quả

### Cấu hình không chứa secret

| Biến/cấu hình | Giá trị sử dụng |
| --- | --- |
| Embedding model | `sentence-transformers/all-MiniLM-L6-v2` |
| Crossref records | 24 |
| Test questions | 10 |
| Retrieval `top_k` | 4 |
| Freshness threshold | 180 ngày |
| Ragas | Không chạy mặc định (`RUN_RAGAS` chưa bật) |

Không đưa API key hoặc nội dung `.env` vào báo cáo.

```bash
python script/run_phase1.py
python script/run_corruption_flow.py
```

| Lệnh | Trạng thái artifact hiện có | Bằng chứng |
| --- | --- | --- |
| Baseline pipeline | Thành công | `data/results/baseline_metrics.json`, `data/reports/phase1_report.md` |
| Corruption flow | Thành công | `data/results/corrupted_metrics.json`, `data/results/repaired_metrics.json`, `data/reports/corruption_report.md` |

## 5. Ingestion, cleaning và data contract

| Thuộc tính | Giá trị |
| --- | --- |
| Source | Crossref REST API, có offline snapshot |
| Query | `agentic retrieval augmented generation large language model` |
| Filter | `from-pub-date:2026-03-30,has-abstract:true` |
| Số record sạch | 24 |
| Retry/fallback | Retry API; dùng `data/raw/crossref_response.json` khi lỗi/mất mạng |

| Trường | Kiểu | Bắt buộc | Xử lý |
| --- | --- | --- | --- |
| `paper_id` | string DOI | Có | Normalize và dedupe |
| `title` | string | Có | Normalize khoảng trắng |
| `summary` | string | Có | Loại JATS/HTML, kiểm tra độ dài |
| `authors`, `categories` | list/string | Không | Join thành metadata/index text |
| `published` | ISO date | Có | Parse để tính `age_days` |
| `text_for_embedding` | string | Có | Ghép title, authors, date, categories, summary |

`text_for_embedding` là ngữ cảnh cấu trúc dùng cho embedding; DOI giữ ổn định làm document identity và `age_days` được tính từ `run_date - published`.

## 6. Evaluation setup

| Thành phần | Cấu hình thực tế |
| --- | --- |
| Số câu hỏi | 10 |
| Question types | `summary`, `authors`, `date`, `categories` |
| Ground truth | DOI trong `ground_truth_doc_ids` |
| Embedding | `sentence-transformers/all-MiniLM-L6-v2` |
| Vector store | ChromaDB local, baseline/corrupted/repaired collections |
| Retrieval `top_k` | 4 |
| Test set | `data/eval/test_set.json`, dùng chung ba trạng thái |

Giữ nguyên test set giúp mọi chênh lệch metric xuất phát từ data/index state, không phải do benchmark khác nhau.

## 7. Kết quả baseline

| Artifact | Trạng thái | Ghi chú |
| --- | --- | --- |
| Raw response/records | Có | `data/raw/` |
| Cleaned dataset | Có | 24 rows trong `data/clean/` |
| Embedding/index | Có | manifest và ChromaDB local |
| Evaluation set | Có | 10 câu |
| Baseline metrics | Có | `data/results/baseline_metrics.json` |
| Quality/freshness | Có | `data/quality/` |
| Baseline report | Có | `data/reports/phase1_report.md` |

| Metric | Giá trị | Diễn giải |
| --- | ---: | --- |
| `retrieval_hit_rate` | 0.0000 | Chưa retrieve được DOI ground truth trong artifact hiện tại |
| `mean_token_f1` | 0.0000 | Câu trả lời chưa trùng ground truth |
| `judge_accuracy` | 0.0000 | Judge fallback chấm sai toàn bộ |
| `mean_judge_score` | 1.0000 | Mức thấp nhất của judge |
| Ragas | N/A | Chưa bật `RUN_RAGAS` |

## 8. Data quality và freshness

| Check | Quality dimension | Kết quả baseline | Bằng chứng |
| --- | --- | --- | --- |
| Row count 5–5000 | Completeness | Pass, 24 rows | baseline quality report |
| `paper_id` not null/unique | Completeness/uniqueness | Pass, 0 null/duplicate | baseline quality report |
| `title` not null | Completeness | Pass, 0 null | baseline quality report |
| Summary length | Validity | Pass, average 241.875 | baseline quality report |

| Freshness signal | Giá trị |
| --- | --- |
| Latest/oldest published | 2026-07-22 / 2026-03-28 |
| Threshold | 180 ngày |
| Stale rows | 0/24 |
| Baseline status | Fresh / pass |

## 9. Corruption scenarios và repair

| Corruption | Cách tạo | Tác động ghi nhận | Cách repair |
| --- | --- | --- | --- |
| Drop latest | Bỏ 2 record mới nhất | Row count giảm | Rebuild từ raw snapshot |
| Blank summary | Xóa summary | Nội dung embedding suy giảm | Re-clean raw records |
| Inject noise | Chèn noise vào summary | Semantic content nhiễu | Re-clean raw records |
| Truncate title | Rút ngắn title | Tín hiệu title suy giảm | Re-clean raw records |
| Stale date | Lùi ngày publish | 2 stale rows, ratio 9.09% | Re-clean raw records |
| Duplicate row | Thêm dòng duplicate | Tăng duplicate dataset | Re-clean raw records |

Corruption log có tại `data/results/corruption_log.json`, ghi 6 scenarios và DOI bị tác động. Repaired data không vá dataframe lỗi; nó được xây dựng lại từ `data/raw/crossref_records.json`, nên loại bỏ mọi biến đổi corruption trong một lần tái tạo có thể lặp lại.

## 10. So sánh baseline, corrupted và repaired

| Metric/signal | Baseline | Corrupted | Repaired | Nhận xét |
| --- | ---: | ---: | ---: | --- |
| `retrieval_hit_rate` | 0.0000 | 0.0000 | 0.0000 | Không thể đo suy giảm với benchmark hiện tại |
| `mean_token_f1` | 0.0000 | 0.0000 | 0.0000 | Không thể đo suy giảm với benchmark hiện tại |
| `judge_accuracy` | 0.0000 | 0.0000 | 0.0000 | Không thể đo suy giảm với benchmark hiện tại |
| `mean_judge_score` | 1.0000 | 1.0000 | 1.0000 | Không thể đo suy giảm với benchmark hiện tại |
| GX status | Pass | Pass | Pass | Các checks hiện tại chưa bắt đủ corruption |
| Stale rows | 0 | 2 | 0 | Repair phục hồi freshness |

1. Stale-date corruption → stale rows tăng từ 0 lên 2 → freshness ratio tăng lên 9.09%; repair from raw → stale rows về 0.
2. Repair from raw snapshot → row count repaired về 24 và GX pass; tuy nhiên agent metrics không chứng minh recovery vì baseline đã bằng 0.

## 11. Vấn đề tích hợp quan trọng

- **Triệu chứng:** Baseline, corrupted và repaired đều có hit rate/Token F1 bằng 0.
- **Nguyên nhân:** Cần kiểm tra lại contract giữa test-set question/ground-truth DOI, metadata index và extraction logic của QA; artifact hiện tại chưa tạo được câu trả lời khớp benchmark.
- **Cách xử lý tiếp theo:** Chạy từng test case, so sánh `ground_truth_doc_ids` với retrieved IDs, sau đó kiểm tra answer extraction theo từng `question_type`.
- **Cách xác minh:** Baseline phải có hit rate lớn hơn 0 trước khi dùng metric để kết luận degradation/recovery.

## 12. Giới hạn và hướng cải thiện

| Giới hạn | Ảnh hưởng | Hướng cải thiện |
| --- | --- | --- |
| Baseline metrics bằng 0 | Không định lượng được Silent Failure | Sửa test-set/index/QA contract, chạy lại ba trạng thái |
| GX corrupted vẫn pass | Một số corruption chưa bị expectation bắt | Thêm checks title length, summary null/length và duplicate trực tiếp |
| Ragas chưa chạy | Thiếu semantic evaluation | Bật `RUN_RAGAS=1` với provider/credential hợp lệ |

## 13. Checklist trước khi nộp

- [x] Thông tin nhóm và repository chính xác.
- [x] Artifact baseline/corrupted/repaired tồn tại.
- [x] Baseline, corrupted và repaired dùng cùng evaluation set.
- [x] Bảng metrics khớp với các file `data/results/`.
- [x] Quality/freshness conclusions khớp với `data/quality/`.
- [x] Các đường dẫn report và artifact truy cập được.
- [x] Phân công scope cho Thành và Hùng đã được chốt.
- [ ] Mỗi thành viên đã xác nhận báo cáo vai trò của mình.
- [ ] Mỗi thành viên có commit trên `main` và tự nộp link VLearn.
- [ ] Đã chạy lại sau khi sửa baseline metrics bằng 0.
