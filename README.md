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

## 🎯 Objective

Build a production-grade **Data Pipeline with Data Observability** for a RAG (Retrieval-Augmented Generation) system that:
1. Ingests research papers from **Crossref REST API** (with offline snapshot fallback)
2. Cleans and normalizes data
3. Embeds with **MiniLM** (Sentence Transformers)
4. Stores in **ChromaDB** vector database
5. Evaluates with **Token F1** and **LLM Judge**
6. Enforces **data quality gates** with Great Expectations 1.x
7. Monitors **freshness** (staleness threshold)
8. Simulates **corruption** and **self-healing repair**
9. Supports **live near-real-time polling** mode
10. Provides **live dashboard** for monitoring

---

## 🏗️ Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Crossref API   │────▶│   Ingestion      │────▶│   Cleaning      │
│  (REST + cache) │     │   crossref.py    │     │   cleaning.py   │
└─────────────────┘     └──────────────────┘     └────────┬────────┘
                                                          │
                        ┌──────────────────┐               ▼
                        │   Corruption     │◀──── Clean DataFrame
                        │   corruption.py │               │
                        └────────┬─────────┘               ▼
                                 │               ┌─────────────────┐
                                 │               │ Great Expectations│
                                 │               │   quality.py    │
                                 │               └────────┬────────┘
                                 │                        │
                                 ▼                        ▼
                        ┌──────────────────┐     ┌─────────────────┐
                        │   ChromaDB        │◀────│   Embeddings    │
                        │   Vector Store   │     │   MiniLM        │
                        └────────┬─────────┘     └─────────────────┘
                                 │
                                 ▼
                        ┌──────────────────┐     ┌─────────────────┐
                        │   LLM (Groq)      │◀────│   QA / Agent    │
                        │   RAG Answer     │     │   retrieval/    │
                        └──────────────────┘     └─────────────────┘
```

---

## 📁 Project Structure

```
K4-L3B-DAY10-LaoGaKho-DataPipelineDataObservability/
├── src/
│   ├── core/
│   │   ├── config.py         # Settings, Paths, load_settings
│   │   └── utils.py          # ensure_parent, write_json, etc.
│   ├── ingestion/
│   │   ├── crossref.py       # Crossref API + parsing
│   │   ├── cleaning.py       # Clean DataFrame builder
│   │   └── corruption.py     # 6 corruption scenarios
│   ├── evaluation/
│   │   ├── metrics.py        # Token F1, Judge, RAGAS
│   │   └── testset.py        # 10 deterministic questions
│   ├── observability/
│   │   ├── quality.py        # Great Expectations + freshness
│   │   ├── reporting.py      # Phase 1 + Corruption reports
│   │   └── diff.py           # Dataset fingerprint + diff for corruption detection
│   ├── retrieval/
│   │   ├── embeddings.py     # MiniLM embeddings
│   │   ├── index.py          # ChromaDB + upsert
│   │   ├── llm.py            # Multi-provider LLM (Groq, OpenAI, etc.)
│   │   ├── qa.py             # Question answering
│   │   └── agent.py          # LangChain agent
│   ├── pipelines/
│   │   ├── phase1.py          # Baseline pipeline
│   │   └── corruption_flow.py # Corrupt → Repair flow
│   └── live/
│       ├── __init__.py
│       ├── config.py         # LiveConfig dataclass
│       ├── state.py          # Atomic state persistence
│       ├── incremental.py     # NEW/UPDATED/UNCHANGED classification
│       ├── pipeline.py        # Single-run pipeline
│       ├── repair.py          # Self-healing quarantine/repair
│       ├── replay.py         # Replay captured raw response
│       ├── recovery.py       # Corruption detection + recovery from source
│       └── monitor.py        # Polling loop with fingerprint-based change detection
├── script/
│   ├── run_phase1.py          # python script/run_phase1.py
│   ├── run_corruption_flow.py # python script/run_corruption_flow.py
│   ├── run_live_once.py       # Single live run
│   ├── run_live_pipeline.py   # Continuous polling loop
│   ├── run_live_replay.py     # Replay captured run
│   ├── run_live_monitor.py    # Monitor loop with change detection
│   ├── run_recovery_once.py   # One-shot recovery from corruption
│   └── test_groq.py           # Test Groq connectivity
├── app/
│   └── live_dashboard.py      # streamlit run app/live_dashboard.py
├── tests/
│   └── test_pipeline.py       # pytest -q
├── data/
│   ├── raw/                   # Crossref snapshot
│   ├── clean/                 # Cleaned CSV/JSON
│   ├── embeddings/            # Embedding manifests
│   ├── eval/                  # Test set
│   ├── results/               # Metrics + answers
│   ├── quality/               # GX + freshness reports
│   ├── reports/               # Markdown reports
│   └── live/                  # Live mode artifacts
│       ├── state.json
│       ├── index_manifest.json
│       ├── raw/
│       ├── clean/
│       ├── quarantine/
│       ├── quality/
│       └── events/
├── pyproject.toml
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## ⚙️ Configuration

### Environment Variables (.env)

```bash
# LLM Provider (Groq primary)
LLM_PROVIDER=groq
GROQ_API_KEY=your_groq_api_key_here
GROQ_BASE_URL=https://api.groq.com/openai/v1
GROQ_MODEL=llama-3.1-8b-instant
GROQ_TEMPERATURE=0.1
GROQ_MAX_TOKENS=2048

# Alternative LLM Providers
GOOGLE_API_KEY=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
OPENROUTER_API_KEY=

# Crossref API
CROSSREF_MAILTO=your_email@example.com
CROSSREF_USER_AGENT=Day10-DataObservability-Lab/1.0
CROSSREF_TIMEOUT_SECONDS=20
CROSSREF_MAX_RETRIES=4

# Live Mode
LIVE_POLL_INTERVAL_SECONDS=30
LIVE_INDEX_OVERLAP_SECONDS=20
LIVE_MAX_RESULTS=50
LIVE_AUTO_REPAIR=true
```

---

## 🚀 Commands

### 1. Baseline Pipeline (Mandatory)

```bash
python script/run_phase1.py
```

This runs:
- Ingest from Crossref API (or snapshot fallback)
- Clean and normalize
- Great Expectations quality gate
- Freshness check
- Build test set (10 questions)
- Embed with MiniLM
- Build ChromaDB index
- Evaluate with Token F1 + LLM Judge
- Generate `phase1_report.md`

### 2. Corruption & Repair Experiment

```bash
python script/run_corruption_flow.py
```

This runs:
- Load clean baseline
- Apply 6 corruption scenarios
- Evaluate corrupted data
- Quality/freshness checks on corrupted
- **Self-healing repair** (re-parse from raw records)
- Evaluate repaired data
- Generate comparison report

### 3. Groq Connectivity Test

```bash
python script/test_groq.py
```

Expected output:
```
Provider: Groq
Model: llama-3.1-8b-instant
Status: SUCCESS
Latency: <ms>
Response: PONG
```

### 4. Live Mode - Single Run

```bash
python script/run_live_once.py
```

### 5. Live Mode - Continuous Polling

```bash
python script/run_live_pipeline.py
```

Press `Ctrl+C` for graceful shutdown.

### 6. Live Mode - Replay

```bash
python script/run_live_replay.py <run_id>
```

### 7. Run Tests

```bash
pytest -q
```

### 8. Live Dashboard

```bash
streamlit run app/live_dashboard.py
```

---

## 📊 Generated Artifacts

| Path | Description |
|------|-------------|
| `data/raw/crossref_response.json` | Raw Crossref API response |
| `data/raw/crossref_records.json` | Parsed PaperRecord list |
| `data/clean/papers_clean.csv` | Clean CSV |
| `data/clean/papers_clean.json` | Clean JSON |
| `data/clean/papers_clean_corrupted.csv` | Corrupted CSV |
| `data/clean/papers_clean_corrupted.json` | Corrupted JSON |
| `data/results/corruption_log.json` | Corruption scenarios log |
| `data/embeddings/papers_embeddings.json` | Baseline embeddings manifest |
| `data/embeddings/papers_embeddings_corrupted.json` | Corrupted embeddings |
| `data/eval/test_set.json` | 10 evaluation questions |
| `data/results/baseline_metrics.json` | Baseline evaluation metrics |
| `data/results/corrupted_metrics.json` | Corrupted metrics |
| `data/results/repaired_metrics.json` | Repaired metrics |
| `data/quality/baseline_quality_report.json` | GX quality report |
| `data/quality/freshness_report.json` | Freshness report |
| `data/reports/phase1_report.md` | Markdown report |
| `data/reports/corruption_report.md` | Comparison report |
| `data/live/state.json` | Live mode state |
| `data/live/index_manifest.json` | Chroma manifest |

---

## 🔬 Key Features

### Data Quality Gate (Great Expectations 1.x)
- Row count range check
- `paper_id` not null
- `paper_id` uniqueness
- `title` not null
- `summary_chars` range

### Freshness Monitoring
- Stale = `age_days > 180`
- Pass if `stale_ratio <= 0.25`

### Corruption Scenarios (6 deterministic)
1. **Drop latest records** - removes newest papers
2. **Blank summary** - empties abstract field
3. **Inject noise** - adds corrupted text markers
4. **Truncate title** - cuts to <8 characters
5. **Stale date** - pushes date 365 days back
6. **Duplicate rows** - adds exact copies

### Self-Healing Repair
- Quarantine invalid records
- Refetch from Crossref
- Re-parse and re-validate
- Upsert if clean, remain quarantined if failed

### Live Mode (Near-Real-Time Polling)
- NEW: First-time seen paper
- UPDATED: Changed timestamp
- UNCHANGED: No changes
- Incremental Chroma upserts
- Atomic state persistence

---

## 🎓 Learning Objectives

1. **Data Pipeline Engineering** - End-to-end ETL with Python
2. **Data Observability** - Quality gates, freshness, monitoring
3. **RAG Evaluation** - Token F1, LLM Judges, retrieval metrics
4. **Vector Databases** - ChromaDB with embeddings
5. **Multi-Provider LLM** - Groq, OpenAI, Gemini, Anthropic
6. **Self-Healing Systems** - Quarantine, repair, replay
7. **Streaming Dashboards** - Streamlit for real-time monitoring

---

## ⚠️ Known Limitations

1. **Groq API Key Required** - Must configure `GROQ_API_KEY` for LLM features
2. **Crossref Rate Limits** - Respect `CROSSREF_MAX_RETRIES` and Retry-After headers
3. **MiniLM Model Download** - First run downloads ~90MB model
4. **ChromaDB Persistence** - Data persists in `data/chroma/` directory
5. **No Kafka/Airflow** - Simple Python scripts, no heavy infrastructure

---

## 🔗 References

- [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)
- [Groq API](https://console.groq.com/docs)
- [Great Expectations 1.x](https://docs.greatexpectations.io/docs/)
- [Sentence Transformers](https://www.sbert.net/)
- [ChromaDB](https://docs.trychroma.com/)
- [Streamlit](https://docs.streamlit.io/)

---

## 🛡️ Data Observability & Recovery (Day 10 Upgrade)

### Source-of-Truth Hierarchy

```
A. Source of truth:   data/raw/crossref_response.json, data/raw/crossref_records.json
B. Derived datasets:   data/clean/papers_clean.json (and .csv),
                       data/embeddings/*, data/chroma/*
C. Observability:      data/quality/*, data/live/*, data/reports/*
```

**Recovery always rebuilds derived data from source (A), never from a corrupted derived dataset.**

---

### Live Polling Behavior

- Polls Crossref on a configurable interval (`LIVE_POLL_INTERVAL_SECONDS`, default 15s).
- Classifies records as **NEW / UPDATED / UNCHANGED**.
- Incremental Chroma upserts only new/updated records.
- Near-real-time: there is a polling lag (not push-based).
- State is persisted atomically in `data/live/state.json`.

---

### Corruption Detection

On every poll cycle, `monitor.py` checks the monitored clean dataset against a stored known-good fingerprint (`data/live/known_good_fingerprint.json`):

1. **Fingerprint** the current file (`dataset_fingerprint`): row count, sorted IDs, per-row SHA256, file SHA256.
2. **Diff** against stored baseline (`diff_datasets`): added, removed, modified, duplicate rows.
3. **Severity scoring**: `removed` / `duplicate` → high; critical field blanked (title/summary/authors/published) → high; other modifications → medium; additions → low.
4. **Events** written to `data/live/events/events.jsonl`.

---

### Recovery Process (8 Stages)

```
1. DETECTION_STARTED     → Identify target file, load current records
2. DATA_CHANGE_DETECTED   → Run fingerprint + diff, classify severity
3. QUARANTINE_CREATED     → Snapshot current (potentially corrupted) data to quarantine/
4. SOURCE_RESTORE_STARTED  → Resolve recovery source (raw snapshot → Crossref fallback)
5. CLEAN_REBUILD_STARTED  → Merge source records + non-conflicting extras
6. EMBEDDING_REBUILD     → Recompute MiniLM embeddings for changed paper_ids only
7. CHROMA_UPDATE         → Incremental upsert to papers-live collection
8. VALIDATION_COMPLETED   → Run GX quality + freshness checks on restored dataset
```

---

### Recovery Report Schema

Written to `data/live/recovery/recovery_<run_id>.json`:

```json
{
  "run_id": "...",
  "started_at": "ISO8601",
  "completed_at": "ISO8601",
  "status": "success|failed|partial",
  "detection": { "source_path", "records_before", "records_after",
                 "issues_detected", "changed_records", "fingerprint_before", "fingerprint_after" },
  "issues": [{ "paper_id", "issue_type", "severity", "fields" }],
  "recovery_source": { "type": "raw_snapshot|crossref", "path", "retrieved_at" },
  "repair": { "records_restored", "records_modified", "records_removed", "fields_restored" },
  "embedding": { "recomputed", "unchanged", "path" },
  "index": { "vectors_added", "vectors_updated", "vectors_deleted",
             "collection": "papers-live", "rebuild_mode": "incremental|full" },
  "validation": {
    "gx_before": { "success", "row_count" },
    "gx_after":  { "success", "row_count" },
    "freshness_before": { "is_fresh", "stale_ratio" },
    "freshness_after":  { "is_fresh", "stale_ratio" },
    "retrieval_validation": { "status", "hit_rate", "samples" }
  }
}
```

---

### Dashboard Sections

The `app/live_dashboard.py` has 4 tabs:

| Tab | Sections |
|-----|----------|
| **System Status + Incidents** | Live System Status bar, Current Incident / Data Quality Alert |
| **Recovery Detail** | Affected Records table, Field-Level Change View, Recovery Pipeline stages, Index Update Summary, Validation Before vs After, Recovery Summary, Human-readable explanation |
| **Event Timeline + Pipeline** | Event Timeline (last 50 events), Recovery Pipeline stages |
| **Comparison + RAG** | Baseline/Corrupted/Repaired Comparison, Recent Papers, Live RAG Query |

**System Status bar** shows: Source, Mode, Polling Interval, Last Run ID, Record Count, GX Status, Freshness Status, Chroma Doc Count, Groq Status, Current Stage (IDLE/MONITORING/RECOVERING).

---

### Manual Corruption Demo

1. Edit `data/clean/papers_clean.json`: drop one record or blank the `summary` field of a record, then save.
2. Run recovery:
   ```bash
   python script/run_recovery_once.py --target data/clean/papers_clean.json
   ```
3. Watch the dashboard (next poll cycle or `streamlit run app/live_dashboard.py`) update.
4. The recovery report at `data/live/recovery/recovery_*.json` shows the detected issue, quarantine path, records restored, and post-repair validation.

---

### Automated Benchmark Commands

```bash
# Baseline pipeline
python script/run_phase1.py

# Corruption + repair flow
python script/run_corruption_flow.py

# Groq connectivity test
python script/test_groq.py

# Single live run
python script/run_live_once.py

# Live monitor loop (polls every LIVE_POLL_INTERVAL_SECONDS)
python script/run_live_pipeline.py

# One-shot recovery
python script/run_recovery_once.py --target data/clean/papers_clean.csv

# Run all tests
pytest -q
```

---

## Live Pipeline

The live pipeline has two separate entry points:

| Script | Purpose |
|--------|---------|
| `python script/run_live_pipeline.py` | **Dataset monitor loop** — polls `data/clean/papers_clean.csv` for changes; triggers recovery if corrupted. Primary demo script. |
| `python script/run_live_ingest.py` | **Crossref ingest loop** — polls Crossref for new papers (original polling behavior preserved). |
| `python script/run_recovery_once.py --target data/clean/papers_clean.csv` | One-shot recovery without polling loop. |

### Authoritative Live Dataset

The single monitored dataset is:

```
data/clean/papers_clean.csv
```

This path is defined as `LIVE_DATASET_PATH_KEY = "data/clean/papers_clean.csv"` in `src/live/config.py` and resolves to the absolute path at runtime.

### Polling Behavior (Dataset Monitor)

On each cycle (`LIVE_POLL_INTERVAL_SECONDS`, default 15s), `run_live_pipeline.py`:
1. Computes SHA256 of `papers_clean.csv` content (not mtime — same bytes → same sha256).
2. Compares against stored fingerprint in `data/live/state.json`.
3. If different: triggers `detect_and_recover()` → diagnose → quarantine → restore from `data/raw/crossref_records.json` → rebuild → re-embed → update Chroma → validate.
4. Writes event types to `data/live/events/events.jsonl`: `LIVE_POLL_STARTED`, `DATA_CHANGE_DETECTED`, `NO_CHANGE`, `RECOVERY_TRIGGERED`.

### Recovery Source Priority

1. `data/raw/crossref_records.json` (primary — DO NOT modify during recovery)
2. Most recent `data/live/raw/<run_id>.json`
3. Crossref re-fetch via `fetch_source_records()`
4. Failure if all unavailable

### Dashboard

```bash
streamlit run app/live_dashboard.py --server.headless true --server.port 8501
```

Dashboard auto-refreshes every `DASHBOARD_REFRESH_SECONDS` (default 15s) using `streamlit.fragment(run_every=...)`. It shows real data from `data/live/state.json`, `data/live/recovery/recovery_*.json`, `data/live/events/events.jsonl`, and the live Chroma collection.

### Manual Corruption Demo

1. `python script/run_live_pipeline.py` (keep running)
2. Edit `data/clean/papers_clean.csv`: delete one row or blank a `summary` field.
3. Wait for next poll cycle (or trigger "Run Detection Cycle Now" in dashboard).
4. Watch recovery: quarantine file appears in `data/live/quarantine/`, CSV is restored to 24 rows, `data/live/recovery/recovery_*.json` shows the issue and field-level diff.

### Limitations

- **Polling not push**: detection lag of at least `LIVE_POLL_INTERVAL_SECONDS`.
- **Chroma full rebuild on recovery**: for safety, recovery does a full Chroma rebuild rather than incremental upsert.
- **Crossref fallback**: if `data/raw/crossref_records.json` is absent and Crossref is unreachable, recovery cannot proceed.
- **No secret scanning in logs**: API keys are never logged.
- **Windows path handling**: all paths use `pathlib.Path` only.
- **`run_corruption_flow.py` is separate**: this is a reproducible benchmark script, not part of the live monitoring demo.
