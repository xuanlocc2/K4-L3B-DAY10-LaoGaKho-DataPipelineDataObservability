# Báo cáo cá nhân — Day 10: Data Pipeline & Data Observability

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
| --- | --- |
| Họ và tên | Nguyễn Văn Xuân Lộc |
| MSSV | 2A202602870 |
| Khóa/Lớp | K4-L3B |
| Tên nhóm | LaoGaKho |
| Vai trò chính | Trưởng nhóm / Pipeline Integrator |
| Repository | https://github.com/xuanlocc2/K4-L3B-DAY10-LaoGaKho-DataPipelineDataObservability |
| Ngày hoàn thành | Chưa nghiệm thu end-to-end |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| --- | --- | --- | --- | --- |
| Core utilities | `src/core/utils.py` | DataFrame, JSON payload và đường dẫn artifact | Hàm đọc/ghi artifact dùng chung | Hoàn thành |
| Baseline orchestration | `src/pipelines/phase1.py:main` | Raw records và các module ingestion/retrieval/evaluation/observability | Toàn bộ artifact baseline | Hoàn thành code, chờ tích hợp |
| Corruption/repair orchestration | `src/pipelines/corruption_flow.py:main` | Baseline artifacts, raw records và test set dùng chung | Corrupted/repaired artifacts và comparison report | Hoàn thành code, chờ tích hợp |
| Điều phối nhóm | `docs/TEAM.md` | Thông tin thành viên và phạm vi module | Phân công owner rõ ràng | Một phần |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --- | --- | --- |
| Xác định contract tích hợp | Ingestion, retrieval, evaluation và observability | Pipeline gọi đúng chữ ký hàm có sẵn trong scaffold |
| Kiểm tra artifact paths | Toàn nhóm | Dùng tập trung các đường dẫn từ `Settings.paths`, không hardcode đường dẫn máy cá nhân |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --- | --- | --- | --- |
| Ghép baseline pipeline | `src/pipelines/phase1.py` | Luồng raw → clean → index → evaluation → quality/freshness → report | `python -m py_compile src/pipelines/phase1.py` |
| Ghép corruption/repair pipeline | `src/pipelines/corruption_flow.py` | Luồng baseline → corrupted → repaired dùng chung test set | `python -m py_compile src/pipelines/corruption_flow.py` |
| Bổ sung ghi DataFrame JSON | `src/core/utils.py:write_dataframe_json` | JSON records UTF-8, ngày ở định dạng ISO | Kiểm thử ghi/đọc bằng DataFrame mẫu |

Output cụ thể hiện tại là hai entrypoint orchestration đã được triển khai theo contract của các module thành viên. Metrics và report thực tế chỉ được bổ sung sau khi các module phụ thuộc hoàn thành và hai pipeline chạy thành công.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Pipeline có nhiều module độc lập nhưng phải chạy đúng thứ tự, dùng cùng schema, cùng đường dẫn artifact và cùng evaluation set. Vai trò tích hợp phải bảo đảm output của bước trước trở thành input hợp lệ của bước sau, đồng thời không sửa code thuộc owner khác.

### Cách triển khai

Baseline pipeline chọn fetch hoặc load raw records theo cấu hình, làm sạch và lưu CSV/JSON, build Chroma index, tạo hoặc tái sử dụng test set, chạy evaluation, quality/freshness checks rồi sinh báo cáo. Corruption flow bảo đảm baseline tồn tại, tạo dữ liệu corrupted, index và đánh giá lại, sau đó repair từ raw records đáng tin cậy và đánh giá trên chính test set ban đầu.

### Input, output và contract

| Thành phần | Mô tả |
| --- | --- |
| Input | `PaperRecord`, cleaned DataFrame, `test_set.json`, cấu hình `Settings` |
| Output | Clean/corrupted/repaired datasets, embedding manifests, metrics, answers, quality và Markdown reports |
| Module phụ thuộc | `ingestion`, `retrieval`, `evaluation`, `observability` |
| Module sử dụng output | Evaluation, reporting, demo và bước nghiệm thu |
| Điều kiện lỗi cần xử lý | Raw/clean rỗng, thiếu baseline artifact, JSON không đúng record-list contract |

### Cách xác minh

```bash
python -m py_compile src/core/utils.py src/pipelines/phase1.py src/pipelines/corruption_flow.py
python script/run_phase1.py
python script/run_corruption_flow.py
```

- **Kết quả mong đợi:** Hai flow exit code 0 và sinh đủ artifact theo `Settings.paths`.
- **Kết quả thực tế:** Kiểm tra cú pháp và unit-level hoàn thành; chạy end-to-end đang chờ các module của thành viên khác bỏ `NotImplementedError`.
- **Artifact/log:** Sẽ cập nhật sau lần chạy tích hợp chung; không ghi số liệu giả định.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Corrupted và repaired phải được so sánh công bằng với baseline.
- **Các phương án đã cân nhắc:** Sinh test set mới ở mỗi trạng thái; hoặc tái sử dụng test set baseline.
- **Phương án đã chọn:** Chỉ tạo test set trong baseline và dùng lại cùng `data/eval/test_set.json` cho corrupted/repaired.
- **Lý do:** Giữ ground truth và tập câu hỏi cố định, tránh thay đổi benchmark làm sai lệch kết luận.
- **Bằng chứng quyết định phù hợp:** Cả ba lời gọi evaluation trong orchestration cùng tham chiếu `settings.paths.eval_testset`.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** Các module `crossref.py`, `cleaning.py`, `testset.py`, `quality.py` và `reporting.py` vẫn chứa `NotImplementedError` trong thời điểm tích hợp.
- **Lệnh hoặc bước tái hiện:** `rg -n "TODO\\(student\\)|NotImplementedError" src`
- **Nguyên nhân gốc:** Nhóm triển khai song song và các owner chưa bàn giao module.
- **Cách xử lý:** Hoàn thiện orchestration theo chữ ký hàm đã thống nhất, không sửa file của owner khác.
- **Cách xác minh sau khi sửa:** Compile/import phần sở hữu độc lập; chờ merge rồi chạy hai entrypoint end-to-end.
- **Điều học được:** Tích hợp song song cần contract ổn định và phải phân biệt rõ lỗi orchestration với blocker từ module phụ thuộc.

## 7. Hiểu biết về luồng end-to-end

1. Crossref được lưu thành raw response và `PaperRecord`; cleaning chuẩn hóa schema và tạo `text_for_embedding`; embedding model biến văn bản thành vector và nạp vào ChromaDB.
2. Evaluation set giữ câu hỏi, đáp án chuẩn và `ground_truth_doc_ids`; kết quả retrieval được đối chiếu theo document ID, còn câu trả lời được đo Token F1 và judge metrics.
3. Quality checks kiểm tra tính đầy đủ, duy nhất và hợp lệ của dữ liệu; freshness monitoring tập trung vào tuổi dữ liệu và tỷ lệ record vượt SLA.
4. Dùng cùng test set giúp thay đổi metrics phản ánh thay đổi dữ liệu/index, không phải thay đổi câu hỏi.
5. Repair thành công khi dữ liệu được dựng lại từ raw source, quality/freshness phục hồi và metrics repaired tiến gần baseline trên cùng benchmark.

## 8. Phân tích kết quả

### Metrics chính

| Metric/signal | Baseline | Corrupted | Repaired | Nhận xét của cá nhân |
| --- | ---: | ---: | ---: | --- |
| `retrieval_hit_rate` | Chờ chạy | Chờ chạy | Chờ chạy | Cập nhật từ metrics artifacts |
| `mean_token_f1` | Chờ chạy | Chờ chạy | Chờ chạy | Cập nhật từ metrics artifacts |
| `judge_accuracy` | Chờ chạy | Chờ chạy | Chờ chạy | Cập nhật từ metrics artifacts |
| `mean_judge_score` | Chờ chạy | Chờ chạy | Chờ chạy | Cập nhật từ metrics artifacts |
| Quality checks | Chờ chạy | Chờ chạy | Chờ chạy | Cập nhật từ quality reports |
| Freshness status | Chờ chạy | Chờ chạy | Chờ chạy | Cập nhật từ freshness reports |

Hai chuỗi nguyên nhân–bằng chứng và phân tích corruption ảnh hưởng mạnh nhất sẽ được điền từ artifacts thực tế sau lần chạy tích hợp. Không kết luận trước khi có số liệu.

## 9. Điều học được và hướng cải thiện

### Ba điều quan trọng nhất

1. Orchestration cần contract rõ ràng về schema, đường dẫn và thứ tự thực thi.
2. Data quality và freshness là hai tín hiệu bổ sung, không thay thế lẫn nhau.
3. Đánh giá tác động dữ liệu đến RAG chỉ có ý nghĩa khi giữ cố định test set và cấu hình retrieval.

### Nếu có thêm thời gian

Bổ sung test tích hợp tự động với dependency fakes để kiểm tra orchestration mà không cần tải embedding model hoặc gọi LLM thật; đo bằng tỷ lệ test pass và coverage pipeline.

## 10. Cam kết của thành viên

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [ ] Mọi kết luận về kết quả đều có artifact hoặc metric để đối chiếu — chờ lần chạy tích hợp.
- [x] Tôi không ghi “đã chạy thành công” cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Nguyễn Văn Xuân Lộc

**Ngày xác nhận:** Chưa xác nhận nghiệm thu end-to-end
