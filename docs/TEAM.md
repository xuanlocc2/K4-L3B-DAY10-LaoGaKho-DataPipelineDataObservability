# Danh Sách Thành Viên & Báo Cáo Phân Công Nhóm

- **Tên Nhóm:** `LaoGaKho`
- **Mã Nhóm / Lớp:** `K4-L3-DAY10`
- **Tên Repository Nộp Bài:** `K4-L3B-DAY10-LaoGaKho-DataPipelineDataObservability`

---

## # Thành viên

| STT | Họ và tên | MSSV | Email | Vai trò & Phân công công việc | Báo cáo cá nhân |
|---:|---|---|---|---|---|
| 1 | Nguyễn Văn Xuân Lộc | 2A202602870 | | Trưởng nhóm / Pipeline Integrator (`core/`, `phase1.py`, `corruption_flow.py`) | `report/2A202602870_NguyenVanXuanLoc.md` |
| 2 | Bùi Hải Nam | 2A202602636 | | Data Foundation & Recovery (`crossref.py`, `cleaning.py`, raw data) | `report/2A202602636_BuiHaiNam.md` |
| 3 | Nguyễn Xuân Thành | 2A202602666 | | Observability & Reporting (`src/observability/quality.py`, `reporting.py`, `diff.py`) | `report/individual_report_3.md` |
| 4 | Lê Đức Hùng | 2A202602849 | | Retrieval & Evaluation (`src/retrieval/`, `src/evaluation/`) | `report/individual_report_4.md` |

*(Nếu nhóm có 3 hoặc 5-6 thành viên, xem bảng phân công chi tiết theo vai trò trong file `CHECKPOINTS.md`)*.

---

## # Cá nhân

### ## Nguyễn Văn Xuân Lộc - 2A202602870
- **Vai trò:** Trưởng nhóm & Điều phối Pipeline.
- **Công việc chi tiết đã hoàn thành:**
  - Thiết lập cấu hình hệ thống `core/config.py` và đường dẫn artifacts `core/utils.py`.
  - Kết nối luồng thực thi trong `src/pipelines/phase1.py` và `src/pipelines/corruption_flow.py`.
  - Kiểm tra tính nhất quán của các artifacts và theo dõi Contributor tracking trên GitHub nhánh `main`.
- **Điều học được / Đóng góp chính:**
  - Hiểu sâu sắc về thiết kế Idempotent Pipeline và quản lý trạng thái luồng dữ liệu đa tầng.

### ## Bùi Hải Nam - 2A202602636
- **Vai trò:** Phụ trách Ingestion, Làm sạch & Phục hồi dữ liệu.
- **Công việc chi tiết đã hoàn thành:**
  - Xây dựng module thu thập Crossref API với cơ chế Fallback offline trong `src/ingestion/crossref.py`.
  - Chuẩn hóa schema, tính toán trường `age_days` và `text_for_embedding` trong `src/ingestion/cleaning.py`.
  - Thực thi cơ chế Idempotent Repair phục hồi dữ liệu từ raw snapshot.
- **Điều học được / Đóng góp chính:**
  - Kỹ thuật truy vết nguồn gốc dữ liệu (Data Lineage) và bảo toàn raw snapshot trước khi biến đổi.

### ## Nguyễn Xuân Thành - 2A202602666
- **Vai trò:** Observability & Reporting.
- **Phạm vi:** `src/observability/quality.py`, `src/observability/reporting.py`, `src/observability/diff.py`.
- **Đầu ra:** Kiểm tra Great Expectations và freshness, so sánh chất lượng giữa các stage, tạo báo cáo Markdown khớp artifacts.
- **Trạng thái:** Đã phân công; cập nhật kết quả thực hiện và commit sau khi hoàn tất.

### ## Lê Đức Hùng - 2A202602849
- **Vai trò:** Retrieval & Evaluation.
- **Phạm vi:** `src/retrieval/` và `src/evaluation/` (index, QA, test set, metrics).
- **Đầu ra:** Kiểm tra luồng truy xuất và trả lời, căn chỉnh test set/ground truth với DOI trong index, tạo metrics baseline/corrupted/repaired có thể diễn giải.
- **Trạng thái:** Đã phân công; cập nhật kết quả thực hiện và commit sau khi hoàn tất.
