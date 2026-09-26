# K4-L3B-Day10 — Data Pipeline & Data Observability for RAG

> **Hình thức:** Teamwork | **Thời lượng:** 240 phút  
> **Lịch học (Lớp B - Ca Sáng):** Thứ 7 (26/09/2026) 09:00 – 13:00  
> ⏰ **Hạn nộp LMS:** 23:59:59 cùng ngày

---

## 🧭 Đọc gì, theo thứ tự nào?

| # | Tài liệu | Mô tả |
|:---:|---|---|
| 1️⃣ | **Codelab trên VLearn LMS** | Hướng dẫn từng bước + nộp bài (mở trên trình duyệt) |
| 2️⃣ | [CHECKPOINTS.md](docs/CHECKPOINTS.md) | Phân bổ thời gian 240 phút & deliverables từng mốc |
| 3️⃣ | [RUBRIC.md](docs/RUBRIC.md) | Tiêu chí chấm điểm (100 chuẩn + 10 bonus) |
| 4️⃣ | [SUBMISSION.md](docs/SUBMISSION.md) | Nội quy, deadline, bảo mật & checklist nộp bài |
| 5️⃣ | [TEAM.md](docs/TEAM.md) | Điền thông tin nhóm & báo cáo cá nhân |

---

## Repo có sẵn gì? (Scaffolded Baseline)

- `data/raw/` — Snapshot offline Crossref API (`crossref_response.json`)
- `src/` — Khung pipeline thu thập, embedding MiniLM, đánh giá metrics (có `TODO(student)`)
- `script/` — Entrypoints: `run_phase1.py`, `run_corruption_flow.py`

## Học viên cần làm gì?

1. Hoàn thiện **Data Quality Gate** (Great Expectations 1.x) trong `src/observability/quality.py`
2. Tích hợp **Freshness Check** (`age_days`) vào Quality Gate
3. Chạy **Baseline → Corruption → Repair** → xuất bảng đối chiếu 3 trạng thái
4. **Live Demo** trên bảng & nộp link repo lên VLearn LMS

## Demo Dashboard

Start the local observability dashboard after syncing the project dependencies:

```powershell
uv sync
uv run streamlit run dashboard.py
```

The dashboard reads pipeline artifacts from `data/` and provides controls to run the baseline and corruption/repair flows.
