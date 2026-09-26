# Báo cáo cá nhân — Nguyễn Văn Xuân Lộc

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
| --- | --- |
| Họ và tên | Nguyễn Văn Xuân Lộc |
| MSSV | 2A202602870 |
| Khóa/Lớp | K4-L3B |
| Nhóm | LaoGaKho |
| Vai trò | Trưởng nhóm / Pipeline Integrator |
| Repository | `K4-L3B-DAY10-LaoGaKho-DataPipelineDataObservability` |
| Ngày cập nhật | 2026-09-26 |

## 2. Vai trò và phạm vi công việc

| Module/deliverable | File/hàm | Input | Output | Trạng thái |
| --- | --- | --- | --- | --- |
| Orchestration baseline | `src/pipelines/phase1.py` | Raw records và module phụ thuộc | Clean/index/eval/quality/report baseline | Đã có artifact |
| Corruption/repair flow | `src/pipelines/corruption_flow.py` | Baseline artifacts, raw snapshot | Corrupted/repaired artifacts và comparison report | Đã có artifact |
| Điều phối tích hợp | `core/`, `docs/TEAM.md` | Contract các module | Đường dẫn/artifact thống nhất | Đang duy trì |

## 3. Kết quả theo vai trò

- Hai entrypoint `python script/run_phase1.py` và `python script/run_corruption_flow.py` đã có artifacts tương ứng.
- `data/reports/phase1_report.md` và `data/reports/corruption_report.md` tồn tại.
- Repair dựng lại dữ liệu từ `data/raw/crossref_records.json`; repaired dataset có 24 dòng.

## 4. Giải thích kỹ thuật

Pipeline chạy theo thứ tự ingest → clean → index → test set → evaluation → quality/freshness → report. Phase 2 dùng cùng test set, index lại corrupted data, sau đó rebuild cleaned data từ raw snapshot để tạo repaired state. Contract chung là `Settings.paths`, `paper_id` DOI và JSON artifacts theo stage.

## 5. Quyết định kỹ thuật

- **Quyết định:** Dùng cùng `data/eval/test_set.json` cho baseline, corrupted và repaired.
- **Lý do:** Chỉ khi benchmark giữ nguyên mới quy kết được thay đổi metric cho dữ liệu/index thay vì cho câu hỏi khác.
- **Bằng chứng:** Ba metrics files đều có `samples=10`.

## 6. Vấn đề hoặc blocker

- **Triệu chứng:** Baseline, corrupted và repaired đều có hit rate/Token F1 bằng 0.
- **Nguyên nhân cần điều tra:** Contract giữa question, ground-truth DOI, index metadata và answer extraction chưa tạo được retrieval đúng.
- **Bước tiếp theo:** Debug từng test case trước khi kết luận về mức suy giảm RAG.

## 7. Hiểu biết end-to-end

Raw Crossref được giữ lại để lineage và repair. Cleaning tạo `text_for_embedding`; ChromaDB index văn bản; test set giữ DOI ground truth. Quality kiểm tra schema/nội dung, freshness kiểm tra độ cũ. Repair thành công khi artifact repaired dựng lại từ raw và các signal phù hợp; metric RAG chỉ là bằng chứng khi baseline hợp lệ.

## 8. Phân tích kết quả

| Signal | Baseline | Corrupted | Repaired |
| --- | ---: | ---: | ---: |
| Retrieval hit rate | 0.0000 | 0.0000 | 0.0000 |
| Mean Token F1 | 0.0000 | 0.0000 | 0.0000 |
| Stale rows | 0 | 2 | 0 |

Repair phục hồi freshness từ 2 stale rows về 0. Không tuyên bố phục hồi metric RAG vì baseline metric bằng 0.

## 9. Điều học được

1. Orchestration cần artifact contract ổn định.
2. Pipeline chạy thành công không đồng nghĩa benchmark có ý nghĩa.
3. Repair từ raw source đáng tin cậy hơn vá trực tiếp corrupted data.

## 10. Cam kết

- [x] Báo cáo phản ánh scope Pipeline Integrator.
- [x] Không ghi số liệu trái artifact.
- [x] Không chứa secret.
- [ ] Cần xác minh lại benchmark sau khi sửa baseline retrieval.

**Họ và tên:** Nguyễn Văn Xuân Lộc
**Ngày xác nhận:** 2026-09-26
