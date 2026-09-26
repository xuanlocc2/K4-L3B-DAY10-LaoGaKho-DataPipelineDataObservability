"""Live RAG Dashboard with Recovery Observability.

Reads all state from real artifacts (data/live/*, data/quality/*, data/results/*).
Uses st.fragment(run_every=...) for real auto-refresh.
Sections organized into 5 tabs:
  Tab 1: System Status + Active Incident
  Tab 2: Recovery Detail (affected records, field changes, validation)
  Tab 3: Recovery Pipeline stages (real timestamps from latest recovery report)
  Tab 4: Event Timeline (last 50 events JSONL)
  Tab 5: Baseline/Corrupted/Repaired comparison + Recent Papers + Live RAG Query
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_DIR / "data"
LIVE_DIR = DATA_DIR / "live"
CHROMA_DIR = DATA_DIR / "chroma"
COLLECTION_NAME = "papers-live"
LIVE_DATASET_CSV = DATA_DIR / "clean" / "papers_clean.csv"
LIVE_DATASET_JSON = DATA_DIR / "clean" / "papers_clean.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            return __import__("json").loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _load_json_list(path: Path) -> list:
    if not path.exists():
        return []
    try:
        return __import__("json").loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _load_lines_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    lines = []
    for line in path.read_text(encoding="utf-8").strip().split("\n"):
        if line.strip():
            try:
                lines.append(__import__("json").loads(line))
            except Exception:
                pass
    return lines


def _load_state() -> dict:
    return _load_json(LIVE_DIR / "state.json")


def _load_manifest() -> dict:
    return _load_json(LIVE_DIR / "index_manifest.json")


def _load_events() -> list[dict]:
    return _load_lines_jsonl(LIVE_DIR / "events" / "events.jsonl")


def _load_quality_reports() -> list[dict]:
    quality_dir = LIVE_DIR / "quality"
    if not quality_dir.exists():
        return []
    reports = []
    for f in sorted(quality_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        data = _load_json(f)
        data["_file"] = f.name
        reports.append(data)
    return reports


def _load_recovery_reports() -> list[dict]:
    recovery_dir = LIVE_DIR / "recovery"
    if not recovery_dir.exists():
        return []
    reports = []
    for f in sorted(recovery_dir.glob("recovery_*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        data = _load_json(f)
        data["_file"] = f.name
        reports.append(data)
    return reports


def _load_latest_recovery_normalized() -> dict:
    """Load latest recovery report with full normalization via diff.py helpers."""
    try:
        from observability.diff import load_latest_recovery
        return load_latest_recovery(PROJECT_DIR)
    except Exception:
        return {}


def _get_chroma_stats() -> dict:
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        collection = client.get_collection(name=COLLECTION_NAME)
        count = collection.count()
        last_manifest = _load_manifest()
        return {
            "collection_name": COLLECTION_NAME,
            "doc_count": count,
            "last_update": last_manifest.get("timestamp", "Unknown"),
            "last_run_id": last_manifest.get("run_id", "None"),
            "error": None,
        }
    except Exception as e:
        return {
            "collection_name": COLLECTION_NAME,
            "doc_count": 0,
            "last_update": "Error",
            "last_run_id": "Error",
            "error": str(e),
        }


def _get_groq_status() -> dict:
    try:
        from retrieval.llm import build_llm
        from core.config import load_settings
        t0 = time.time()
        settings = load_settings(PROJECT_DIR)
        llm = build_llm(settings=settings, temperature=0.1)
        response = llm.invoke("Respond with exactly: PONG")
        latency_ms = int((time.time() - t0) * 1000)
        content = getattr(response, "content", str(response)).strip()
        return {"status": "UP", "latency_ms": latency_ms, "response": content[:50], "model": settings.groq_model}
    except Exception as e:
        return {"status": "DOWN", "error": str(e)[:100], "latency_ms": 0, "response": ""}


def _rag_query(query: str, top_k: int = 4) -> dict:
    try:
        import chromadb
        from retrieval.embeddings import MiniLMEmbeddings
        from core.config import load_settings

        settings = load_settings(PROJECT_DIR)
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        collection = client.get_collection(name=COLLECTION_NAME)

        embeddings = MiniLMEmbeddings(settings.embedding_model)
        query_embedding = embeddings.embed_query(query)

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        papers = []
        for doc, metadata, distance in zip(
            results.get("documents", [[]])[0],
            results.get("metadatas", [[]])[0],
            results.get("distances", [[]])[0],
        ):
            if doc and metadata:
                summary = metadata.get("summary", "")
                papers.append({
                    "rank": 0,
                    "paper_id": metadata.get("paper_id", ""),
                    "title": metadata.get("title", ""),
                    "score": round(1.0 - float(distance or 0.0), 4),
                    "abs_url": metadata.get("abs_url", ""),
                    "summary": (summary[:300] + "..." if len(summary) > 300 else summary),
                    "authors": metadata.get("authors_joined", ""),
                    "published": metadata.get("published", ""),
                })
        return {"success": True, "papers": papers, "query": query}
    except Exception as e:
        return {"success": False, "error": str(e), "papers": [], "query": query}


def _call_groq(question: str, context: str) -> str:
    try:
        from retrieval.llm import build_llm
        from core.config import load_settings

        settings = load_settings(PROJECT_DIR)
        prompt = f"""Based on the following context from research papers, answer the question.

Context:
{context}

Question: {question}

Provide a clear and concise answer based on the context above."""

        llm = build_llm(settings=settings, temperature=0.1)
        response = llm.invoke(prompt)
        return getattr(response, "content", str(response))
    except Exception as e:
        return f"Error calling LLM: {e}"


def _load_recent_papers() -> list[dict]:
    for candidate in [LIVE_DATASET_JSON, LIVE_DATASET_CSV]:
        if candidate.exists():
            try:
                if candidate.suffix == ".csv":
                    df = pd.read_csv(candidate)
                    return df.to_dict(orient="records")[:20]
                else:
                    return _load_json_list(candidate)[:20]
            except Exception:
                pass
    return []


def _get_live_config() -> dict:
    try:
        poll = int(os.getenv("LIVE_POLL_INTERVAL_SECONDS", "15"))
    except Exception:
        poll = 15
    return {
        "poll_interval": poll,
        "dashboard_refresh": int(os.getenv("DASHBOARD_REFRESH_SECONDS", "15")),
        "stale_threshold": int(os.getenv("STALE_STATE_SECONDS", "60")),
    }


def _build_human_readable_summary(report: dict) -> str:
    try:
        from observability.diff import safe_get
    except Exception:
        def safe_get(d, *keys, default=None):
            current = d
            for k in keys:
                if not isinstance(current, dict):
                    return default
                current = current.get(k, default)
                if current is default:
                    return default
            return current

    issues = safe_get(report, "issues", default=[]) or []
    repair = safe_get(report, "repair", default={}) or {}
    source = safe_get(report, "recovery_source", default={}) or {}
    validation = safe_get(report, "validation", default={}) or {}
    index = safe_get(report, "index", default={}) or {}

    n_removed = sum(1 for i in issues if safe_get(i, "issue_type") in ("missing_record", "blanked_field"))
    n_issues = len(issues)
    paper_ids = [safe_get(i, "paper_id", default="") for i in issues[:3]]
    n_restored = repair.get("records_restored", 0)
    n_fields = repair.get("fields_restored", 0)
    n_emb = safe_get(report, "embedding", "recomputed", default=0) or 0
    n_vectors = (index.get("vectors_added", 0) + index.get("vectors_updated", 0))
    gx_pass = safe_get(validation, "gx_after", "success", default=False)

    parts = []
    if n_removed > 0:
        parts.append(f"{n_removed} record(s) were removed/missing from the clean dataset.")
    if n_issues > 0:
        parts.append(f"{n_issues} data-quality issue(s) were detected.")
    if paper_ids and n_restored > 0:
        parts.append(f"The affected record(s) {paper_ids} were restored from {source.get('type', 'source')}.")
    if n_fields > 0:
        parts.append(f"{n_fields} field(s) were restored.")
    if n_emb > 0:
        parts.append(f"{n_emb} embedding(s) were regenerated.")
    if n_vectors > 0:
        parts.append(f"{n_vectors} Chroma vector(s) were updated.")
    parts.append(f"Post-repair validation: {'PASS' if gx_pass else 'FAIL'}.")
    return " ".join(parts) if parts else "No issues detected. System is healthy."


def _is_state_stale(state: dict, threshold_seconds: int) -> bool:
    last_poll = state.get("last_poll_at") or state.get("last_poll_time")
    if not last_poll:
        return True
    try:
        last_time = datetime.fromisoformat(last_poll.replace("Z", "+00:00"))
        age = (datetime.now() - last_time.replace(tzinfo=None)).total_seconds()
        return age > threshold_seconds
    except Exception:
        return True


# ---------------------------------------------------------------------------
# Main fragment (auto-refresh)
# ---------------------------------------------------------------------------

@st.fragment(run_every=int(os.getenv("DASHBOARD_REFRESH_SECONDS", "15")))
def main_fragment():
    st.set_page_config(
        page_title="Live RAG Pipeline Dashboard",
        page_icon="📊",
        layout="wide",
    )
    st.title("📊 Live RAG Pipeline Dashboard with Recovery Observability")

    # Load all data
    state = _load_state()
    manifest = _load_manifest()
    chroma_stats = _get_chroma_stats()
    quality_reports = _load_quality_reports()
    events = _load_events()
    recovery_reports = _load_recovery_reports()
    latest_recovery = _load_latest_recovery_normalized()
    recent_papers = _load_recent_papers()
    live_config = _get_live_config()

    # Resolve authoritative dataset path
    live_dataset_path = LIVE_DATASET_CSV
    if not live_dataset_path.exists():
        live_dataset_path = LIVE_DATASET_JSON
    live_dataset_display = str(live_dataset_path.resolve())

    # Determine current stage
    if latest_recovery:
        started = latest_recovery.get("started_at", "")
        completed = latest_recovery.get("completed_at", "")
        stage = "IDLE" if completed else "RECOVERING"
    else:
        stage = state.get("stage", "IDLE")

    # Determine record count from live dataset
    live_record_count = 0
    if live_dataset_path.exists():
        try:
            if live_dataset_path.suffix == ".csv":
                df = pd.read_csv(live_dataset_path)
                live_record_count = len(df)
            else:
                live_record_count = len(_load_json_list(live_dataset_path))
        except Exception:
            live_record_count = 0
    else:
        live_record_count = state.get("record_count", 0)

    # Determine fingerprint display
    fp = state.get("dataset_fingerprint", "")
    fp_display = (fp[:12] + "...") if fp and len(fp) > 12 else (fp or "none")

    # State staleness
    is_stale = _is_state_stale(state, live_config["stale_threshold"])

    # Tabs
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "🖥️ System Status + Incident",
        "🔧 Recovery Detail",
        "🔧 Recovery Pipeline Stages",
        "📜 Event Timeline",
        "📊 Comparison + RAG",
    ])

    # ================================================================
    # TAB 1: System Status + Active Incident
    # ================================================================
    with tab1:
        # --- A. Live System Status panel ---
        st.subheader("🔔 Live System Status")

        # Show stale banner if needed
        if is_stale:
            st.warning(
                f"⚠️ STALE LIVE STATE — Last poll was {state.get('last_poll_at', state.get('last_poll_time', 'Never'))}. "
                f"Run `python script/run_live_pipeline.py` to start monitoring."
            )

        # Primary info cards
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("LIVE DATASET", live_dataset_display)
            st.metric("Source", "Crossref + raw snapshot")
            st.metric("Mode", "Near-Real-Time Polling")
        with col2:
            st.metric("Polling Interval", f"{live_config['poll_interval']}s")
            st.metric("Last Dataset SHA256", fp_display)
            last_poll = state.get("last_poll_at") or state.get("last_poll_time") or "Never"
            st.metric("Last Poll", str(last_poll)[:25])
        with col3:
            st.metric("Last Run ID", str(state.get("last_run_id", "None"))[:30])
            st.metric("Record Count", live_record_count)
            st.metric("Stage", stage)
        with col4:
            gx_s = state.get("gx_status", "UNKNOWN")
            st.metric("GX Status", gx_s)
            fr_s = state.get("freshness_status", "UNKNOWN")
            st.metric("Freshness", fr_s)
            st.metric("Chroma Docs", chroma_stats.get("doc_count", 0))

        st.divider()

        # --- B. Active Incident alert ---
        issues = latest_recovery.get("issues", []) or []
        det = latest_recovery.get("detection", {}) or {}
        high_sev = [i for i in issues if i.get("severity") == "high"]
        if issues:
            st.error(
                f"🚨 ACTIVE INCIDENT | Records: {det.get('records_before', '?')} → {det.get('records_after', '?')} | "
                f"{len(high_sev)} high-severity issue(s)"
            )
        else:
            st.success("✅ System Healthy — No active data quality incidents")

        st.divider()

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("🔗 Source & Ingestion")
            st.write(f"**API:** Crossref REST API")
            st.write(f"**Mode:** Near-Real-Time Polling")
            st.write(f"**Authoritative Dataset:** `{live_dataset_display}`")
            st.write(f"**Last Poll:** {state.get('last_poll_time', 'Never')}")
            st.write(f"**Last Success:** {state.get('last_successful_run', 'Never')}")
            last_error = state.get("last_error")
            if last_error:
                st.error(f"**Last Error:** {last_error}")
            else:
                st.success("**Last Error:** None")

        with col2:
            st.subheader("📥 Ingestion Stats")
            st.write(f"**Seen:** {state.get('records_seen', 0)}")
            st.write(f"**New:** {state.get('records_new', 0)}")
            st.write(f"**Updated:** {state.get('records_updated', 0)}")
            st.write(f"**Rejected:** {state.get('records_rejected', 0)}")
            st.write(f"**Last Run ID:** {state.get('last_run_id', 'None')}")

        st.divider()

        # Freshness
        st.subheader("⏰ Freshness")
        if quality_reports:
            latest_q = quality_reports[-1]
            fresh = latest_q.get("is_fresh")
            if fresh is None:
                fresh = latest_q.get("statistics", {}).get("is_fresh")
            fresh_label = ("✅ PASS" if fresh else ("❌ FAIL" if fresh is False else "—"))
            st.write(f"**Status:** {fresh_label}")
            st.write(f"**Threshold:** {latest_q.get('threshold_days', 180)} days")
            st.write(f"**Stale Ratio:** {latest_q.get('stale_ratio', 0.0):.2%}")
        else:
            st.info("No freshness data yet")

        st.divider()

        # Incidents from quarantine + failed events
        st.subheader("🚨 Incidents & Self-Healing")
        incidents = []
        quarantine_dir = LIVE_DIR / "quarantine"
        if quarantine_dir.exists():
            for f in sorted(quarantine_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:20]:
                data = _load_json(f)
                if data:
                    incidents.append({
                        "Paper ID": data.get("paper_id", ""),
                        "Reason": data.get("reason", ""),
                        "Action": "Quarantined",
                        "Result": "Pending",
                        "Timestamp": data.get("timestamp", ""),
                    })
        for event in events[-20:]:
            if event.get("result") == "failed":
                incidents.append({
                    "Paper ID": event.get("paper_id", ""),
                    "Reason": event.get("event_type", ""),
                    "Action": event.get("action", ""),
                    "Result": event.get("result", ""),
                    "Timestamp": event.get("timestamp", ""),
                })
        if incidents:
            st.dataframe(pd.DataFrame(incidents), use_container_width=True)
        else:
            st.success("No incidents recorded")

        st.divider()

        # Run Detection Cycle Now
        if st.button("🔄 Run Detection Cycle Now", key="run_detection"):
            with st.spinner("Running detection cycle..."):
                try:
                    from live.monitor import run_monitoring_cycle
                    from core.config import load_settings
                    from live.config import LiveConfig
                    settings_d = load_settings(PROJECT_DIR)
                    live_c = LiveConfig.from_env()
                    result = run_monitoring_cycle(settings_d, live_c)
                    changed = result.get("changed", False)
                    if changed:
                        diff = result.get("diff", {})
                        st.warning(
                            f"Change detected! Rows: {diff.get('row_count_before', '?')} → {diff.get('row_count_after', '?')}"
                        )
                    else:
                        st.success("No change detected.")
                except Exception as e:
                    st.error(f"Detection cycle failed: {e}")

    # ================================================================
    # TAB 2: Recovery Detail
    # ================================================================
    with tab2:
        st.subheader("🔍 Affected Records (Latest Recovery)")

        if issues:
            # Canonical issue table
            issues_data = []
            for issue in issues:
                severity_icon = ("🔴 HIGH" if issue.get("severity") == "high"
                                else "🟡 MED" if issue.get("severity") == "medium"
                                else "🟢 LOW")
                # Fields: always list of dicts — join field names safely
                raw_fields = issue.get("fields", []) or []
                if raw_fields and isinstance(raw_fields[0], dict):
                    field_names = ", ".join(f.get("field", "?") for f in raw_fields[:5])
                elif raw_fields and isinstance(raw_fields[0], str):
                    field_names = ", ".join(str(f) for f in raw_fields[:5])
                else:
                    field_names = ""

                issues_data.append({
                    "Paper ID": issue.get("paper_id", ""),
                    "Change Type": issue.get("change_type", ""),
                    "Issue": issue.get("issue_type", ""),
                    "Severity": severity_icon,
                    "Fields": field_names,
                })
            st.dataframe(pd.DataFrame(issues_data), use_container_width=True)

            # Field-level change view
            st.subheader("📋 Field-Level Change View")
            pid_options = [i.get("paper_id", "") for i in issues if i.get("paper_id")]
            if pid_options:
                selected_pid = st.selectbox(
                    "Select Paper ID to inspect:", options=pid_options, key="field_pid_select"
                )
                if selected_pid:
                    issue = next((i for i in issues if i.get("paper_id") == selected_pid), None)
                    raw_fields = (issue.get("fields", []) or []) if issue else []
                    if raw_fields:
                        field_rows = []
                        for f in raw_fields:
                            if isinstance(f, dict):
                                before_v = str(f.get("before", ""))[:100]
                                after_v = str(f.get("after", ""))[:100]
                                action = f.get("action", "RESTORED")
                                field_rows.append({
                                    "Field": f.get("field", "?"),
                                    "Before": before_v,
                                    "After": after_v,
                                    "Action": action,
                                })
                            elif isinstance(f, str):
                                field_rows.append({"Field": f, "Before": "", "After": "", "Action": "N/A"})
                        st.dataframe(pd.DataFrame(field_rows), use_container_width=True)
                    else:
                        st.info("No field-level changes for this record.")
        else:
            st.success("✅ No recovery issues detected")

        st.divider()

        # Index Update Summary
        st.subheader("📦 Index Update Summary")
        emb_data = latest_recovery.get("embedding", {}) or {}
        idx_data = latest_recovery.get("index", {}) or {}
        ic1, ic2, ic3 = st.columns(3)
        with ic1:
            st.metric("Embeddings Recomputed", emb_data.get("recomputed", 0))
        with ic2:
            st.metric("Embeddings Unchanged", emb_data.get("unchanged", 0))
        with ic3:
            st.metric("Rebuild Mode", idx_data.get("rebuild_mode", "N/A"))
        ic4, ic5, ic6 = st.columns(3)
        with ic4:
            st.metric("Vectors Added", idx_data.get("vectors_added", 0))
        with ic5:
            st.metric("Vectors Updated", idx_data.get("vectors_updated", 0))
        with ic6:
            st.metric("Collection", idx_data.get("collection", COLLECTION_NAME))

        st.divider()

        # Validation Before vs After
        st.subheader("✅ Validation: Before vs After")
        val = latest_recovery.get("validation", {}) or {}
        gx_b = val.get("gx_before", {}) or {}
        gx_a = val.get("gx_after", {}) or {}
        fr_b = val.get("freshness_before", {}) or {}
        fr_a = val.get("freshness_after", {}) or {}
        rv = val.get("retrieval_validation", {}) or {}

        val_data = [
            {
                "Check": "GX Quality",
                "Before": "PASS" if gx_b.get("success") else "FAIL",
                "After": "PASS" if gx_a.get("success") else "FAIL",
                "Rows Before": gx_b.get("row_count", 0),
                "Rows After": gx_a.get("row_count", 0),
            },
            {
                "Check": "Freshness",
                "Before": "PASS" if fr_b.get("is_fresh") else "FAIL",
                "After": "PASS" if fr_a.get("is_fresh") else "FAIL",
                "Rows Before": "-",
                "Rows After": "-",
            },
            {
                "Check": "Retrieval",
                "Before": "-",
                "After": rv.get("status", "N/A"),
                "Rows Before": "-",
                "Rows After": rv.get("samples", 0),
            },
        ]
        st.dataframe(pd.DataFrame(val_data), use_container_width=True)

        st.divider()

        # Recovery Summary
        rep = latest_recovery.get("repair", {}) or {}
        det_data = latest_recovery.get("detection", {}) or {}
        st.subheader("📊 Recovery Summary")
        rs1, rs2, rs3, rs4 = st.columns(4)
        with rs1:
            st.metric("Issues Detected", det_data.get("issues_detected", 0))
        with rs2:
            st.metric("Records Restored", rep.get("records_restored", 0))
        with rs3:
            st.metric("Fields Restored", rep.get("fields_restored", 0))
        with rs4:
            gx_ok = gx_a.get("success", False) if gx_a else False
            st.metric("Validation", "✅ PASS" if gx_ok else "❌ FAIL")

        st.divider()

        # Human-readable explanation
        st.subheader("💬 Human-Readable Explanation")
        explanation = _build_human_readable_summary(latest_recovery)
        st.info(explanation)

    # ================================================================
    # TAB 3: Recovery Pipeline Stages
    # ================================================================
    with tab3:
        st.subheader("🔧 Recovery Pipeline (Latest Run)")

        if latest_recovery:
            started = latest_recovery.get("started_at", "")[:19]
            completed = latest_recovery.get("completed_at", "")[:19]
            status = latest_recovery.get("status", "unknown")

            pipeline_stages = [
                ("1. Detect", "DETECTION_STARTED", det_data.get("records_before", 0), det_data.get("records_after", 0)),
                ("2. Diagnose", "DATA_CHANGE_DETECTED", det_data.get("issues_detected", 0), "issue(s)"),
                ("3. Quarantine", "QUARANTINE_CREATED", "—", "snapshot saved"),
                ("4. Restore Source", latest_recovery.get("recovery_source", {}).get("type", "raw_snapshot"), "—", "source resolved"),
                ("5. Rebuild Clean", "CLEAN_REBUILD_COMPLETED", rep.get("records_restored", 0), "record(s) restored"),
                ("6. Recompute Embeddings", "EMBEDDING_REBUILD_COMPLETED", emb_data.get("recomputed", 0), "embeddings"),
                ("7. Update Chroma", "CHROMA_UPDATE_COMPLETED", "—", idx_data.get("rebuild_mode", "N/A")),
                ("8. Validate", "VALIDATION_COMPLETED", "—", status),
            ]

            stage_data = []
            run_id_prefix = latest_recovery.get("run_id", "")[:20]
            for stage_name, event_type, value, note in pipeline_stages:
                matching = [
                    e for e in events
                    if e.get("event_type") == event_type
                    and run_id_prefix in e.get("run_id", "")
                ]
                ts = matching[-1].get("timestamp", "")[:19] if matching else "—"
                status_icon = "✅" if status == "success" else ("⚠️" if status == "partial" else "❌")
                stage_data.append({
                    "Stage": stage_name,
                    "Event": event_type,
                    "Timestamp": ts,
                    "Status": status_icon,
                    "Value": value,
                    "Note": note,
                })

            st.dataframe(pd.DataFrame(stage_data), use_container_width=True)
            st.caption(
                f"Recovery run: {latest_recovery.get('run_id', 'N/A')} | "
                f"Started: {started} | Completed: {completed}"
            )
        else:
            st.info("No recovery runs recorded yet. Start `python script/run_live_pipeline.py` to monitor.")

        st.divider()

        # GX + Freshness from latest quality report
        st.subheader("📋 Data Quality (Latest)")
        if quality_reports:
            latest_q = quality_reports[-1]
            stats = latest_q.get("statistics", {}) or {}
            gx_status = "✅ PASS" if latest_q.get("success") else "❌ FAIL"
            st.write(f"**GX Status:** {gx_status}")
            st.write(f"**Row Count:** {stats.get('row_count', 0)}")
            st.write(f"**Null IDs:** {stats.get('null_paper_ids', 0)}")
            st.write(f"**Null Titles:** {stats.get('null_titles', 0)}")
            st.write(f"**Duplicates:** {stats.get('duplicate_paper_ids', 0)}")
        else:
            st.info("No quality reports yet")

    # ================================================================
    # TAB 4: Event Timeline
    # ================================================================
    with tab4:
        st.subheader("📜 Event Timeline (Last 50 Events)")
        if events:
            ev_data = []
            for ev in reversed(events[-50:]):
                ev_data.append({
                    "Time": ev.get("timestamp", "")[:19],
                    "Event": ev.get("event_type", ""),
                    "Run ID": str(ev.get("run_id", ""))[:25],
                    "Paper ID": str(ev.get("paper_id", ""))[:20] if ev.get("paper_id") else "—",
                    "Action": ev.get("action", ""),
                    "Result": ev.get("result", ""),
                })
            st.dataframe(pd.DataFrame(ev_data), use_container_width=True)
        else:
            st.info("No events recorded yet")

        st.divider()

        # Recent runs table
        st.subheader("📋 Recent Quality Runs")
        if quality_reports:
            runs_data = []
            for i, report in enumerate(quality_reports[-10:]):
                runs_data.append({
                    "Run": i + 1,
                    "File": report.get("_file", ""),
                    "GX Status": "PASS" if report.get("success") else "FAIL",
                    "Row Count": report.get("statistics", {}).get("row_count", 0),
                })
            st.dataframe(pd.DataFrame(runs_data), use_container_width=True)
        else:
            st.info("No runs recorded yet")

    # ================================================================
    # TAB 5: Comparison + RAG
    # ================================================================
    with tab5:
        # Baseline / Corrupted / Repaired Comparison
        st.subheader("📊 Baseline / Corrupted / Repaired Comparison")

        baseline_metrics = _load_json(DATA_DIR / "results" / "baseline_metrics.json")
        corrupted_metrics = _load_json(DATA_DIR / "results" / "corrupted_metrics.json")
        repaired_metrics = _load_json(DATA_DIR / "results" / "repaired_metrics.json")

        baseline_q = _load_json(DATA_DIR / "quality" / "baseline_quality_report.json")
        corrupted_q = _load_json(DATA_DIR / "quality" / "corrupted_quality_report.json")
        repaired_q = _load_json(DATA_DIR / "quality" / "repaired_quality_report.json")

        if any([baseline_metrics, corrupted_metrics, repaired_metrics]):
            comparison_data = []
            for label, metrics, quality in [
                ("Baseline", baseline_metrics, baseline_q),
                ("Corrupted", corrupted_metrics, corrupted_q),
                ("Repaired", repaired_metrics, repaired_q),
            ]:
                if not metrics and not quality:
                    continue
                retrieval_hit = (
                    metrics.get("retrieval_hit_rate", metrics.get("hit_rate", "-"))
                    if metrics else "-"
                )
                if isinstance(retrieval_hit, float):
                    retrieval_hit = f"{retrieval_hit:.2%}"
                row_count = quality.get("statistics", {}).get("row_count", "-") if quality else "-"
                gx_ok = "PASS" if quality.get("success") else "FAIL" if quality else "-"
                comparison_data.append({
                    "Dataset": label,
                    "GX": gx_ok,
                    "Row Count": row_count,
                    "Retrieval Hit Rate": retrieval_hit,
                    "GX Success": metrics.get("gx_success", "-") if metrics else "-",
                })

            if comparison_data:
                st.dataframe(pd.DataFrame(comparison_data), use_container_width=True)
            else:
                st.info("Run `python script/run_corruption_flow.py` first to generate benchmark data.")
        else:
            st.info("Run `python script/run_corruption_flow.py` first to generate benchmark data.")

        st.divider()

        # Recent Papers
        st.subheader("📚 Recent Papers (Live Clean)")
        if recent_papers:
            papers_data = []
            for p in recent_papers[:20]:
                title = p.get("title", "")[:60]
                if len(p.get("title", "")) > 60:
                    title += "..."
                papers_data.append({
                    "Paper ID": p.get("paper_id", ""),
                    "Title": title,
                    "Authors": p.get("authors_joined", p.get("authors", ""))[:40],
                    "Published": p.get("published", ""),
                })
            st.dataframe(pd.DataFrame(papers_data), use_container_width=True)
        else:
            st.info("No recent papers yet")

        st.divider()

        # Live RAG Query
        st.subheader("💬 Live RAG Query")
        query = st.text_input("Ask a question about the research papers:", key="rag_query_input")
        top_k = st.slider("Number of results", 1, 10, 4, key="rag_top_k")

        if query:
            with st.spinner("Searching..."):
                results = _rag_query(query, top_k=top_k)

            if results.get("success"):
                st.success(f"Found {len(results['papers'])} relevant papers")

                for paper in results["papers"]:
                    paper["rank"] = results["papers"].index(paper) + 1
                    with st.expander(f"📄 {paper['title']} (Score: {paper['score']:.4f})"):
                        st.write(f"**Paper ID:** {paper['paper_id']}")
                        st.write(f"**Authors:** {paper['authors']}")
                        st.write(f"**Published:** {paper['published']}")
                        st.write(f"**Summary:** {paper['summary']}")
                        if paper["abs_url"]:
                            st.write(f"**URL:** [{paper['abs_url']}]({paper['abs_url']})")

                if results["papers"]:
                    context = "\n\n".join([
                        f"Title: {p['title']}\nSummary: {p['summary']}"
                        for p in results["papers"][:3]
                    ])

                    if st.button("🤖 Ask Groq", key="rag_ask_groq"):
                        with st.spinner("Getting answer from Groq..."):
                            answer = _call_groq(query, context)
                        st.markdown("### Answer:")
                        st.info(answer)
            else:
                st.error(f"Search failed: {results.get('error', 'Unknown error')}")

    st.divider()
    st.caption(
        f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | "
        f"Dashboard reads real artifacts only | "
        f"Authoritative dataset: `{live_dataset_display}`"
    )


# ---------------------------------------------------------------------------
# Bootstrap (outside fragment — sets up page config and title only)
# ---------------------------------------------------------------------------

def main():
    main_fragment()


if __name__ == "__main__":
    main()
