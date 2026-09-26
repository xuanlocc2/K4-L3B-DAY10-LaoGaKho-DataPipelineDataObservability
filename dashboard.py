from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from core.config import load_settings

SETTINGS = load_settings(ROOT)

st.set_page_config(
    page_title="Data Observatory | Day 10",
    page_icon=":material/query_stats:",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');
    :root {
      --ink: #173b3c;
      --muted: #667b78;
      --paper: #f4f7f4;
      --line: #d9e3df;
      --teal: #16766c;
      --coral: #ca614c;
      --gold: #bd8a32;
    }
    html, body, [class*="css"] { font-family: 'DM Sans', 'Segoe UI', sans-serif; }
    [data-testid="stAppViewContainer"] {
      background-color: var(--paper);
      background-image: linear-gradient(rgba(23,59,60,.025) 1px, transparent 1px),
                        linear-gradient(90deg, rgba(23,59,60,.025) 1px, transparent 1px);
      background-size: 32px 32px;
      color: var(--ink);
    }
    [data-testid="stHeader"] { background: transparent; }
    [data-testid="stSidebar"] { background: #173b3c; border-right: 1px solid #315657; }
    [data-testid="stSidebar"] * { color: #eaf2ef; }
    [data-testid="stSidebar"] [data-testid="stRadio"] label { font-size: .95rem; }
    [data-testid="stSidebar"] [data-testid="stRadio"] div[role="radiogroup"] { gap: .25rem; }
    .block-container { max-width: 1480px; padding-top: 2rem; padding-bottom: 3rem; }
    h1, h2, h3 { color: var(--ink); letter-spacing: 0; }
    h1 { font-size: 2.25rem; line-height: 1.1; font-weight: 700; }
    h2 { font-size: 1.35rem; font-weight: 650; margin-top: 1.2rem; }
    .mono, code, [data-testid="stMetricValue"] { font-family: 'IBM Plex Mono', Consolas, monospace !important; }
    .eyebrow { color: var(--teal); font: 600 .75rem 'IBM Plex Mono', Consolas, monospace; text-transform: uppercase; letter-spacing: .08em; }
    .lede { color: var(--muted); font-size: 1rem; margin-top: -.35rem; }
    .rule { border-top: 1px solid var(--line); margin: 1.15rem 0; }
    .stage-line { display: flex; align-items: center; gap: .65rem; color: var(--muted); font: 500 .76rem 'IBM Plex Mono', Consolas, monospace; text-transform: uppercase; }
    .stage { padding: .35rem .55rem; border: 1px solid var(--line); background: rgba(255,255,255,.6); }
    .stage-active { color: var(--teal); border-color: #95c5b9; }
    .stage-failure { color: var(--coral); border-color: #e2b2a8; }
    .stage-repaired { color: #416e4e; border-color: #a9c4a8; }
    .stage-arrow { color: #91a29e; }
    [data-testid="stMetric"] { background: rgba(255,255,255,.86); border: 1px solid var(--line); border-radius: 4px; padding: .9rem 1rem; }
    [data-testid="stMetricLabel"] { color: var(--muted); }
    [data-testid="stMetricValue"] { color: var(--ink); }
    div.stButton > button, div[data-testid="stDownloadButton"] button {
      border-radius: 4px; border: 1px solid #adc2bd; min-height: 2.65rem; font-weight: 600;
    }
    div.stButton > button[kind="primary"] { background: var(--teal); border-color: var(--teal); }
    [data-testid="stDataFrame"] { border: 1px solid var(--line); }
    [data-testid="stExpander"] { border-color: var(--line); border-radius: 4px; background: rgba(255,255,255,.55); }
    [data-testid="stAlert"] { border-radius: 4px; }
    .side-mark { font: 600 .73rem 'IBM Plex Mono', Consolas, monospace; color: #a9d4c8; letter-spacing: .08em; }
    .side-title { color: white; font-size: 1.5rem; font-weight: 700; line-height: 1.1; margin: .45rem 0 0; }
    .side-subtitle { color: #b8cdca; font-size: .85rem; margin: .35rem 0 1.2rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def read_frame(path: Path) -> pd.DataFrame:
    try:
        if path.suffix.lower() == ".csv":
            return pd.read_csv(path)
        return pd.read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return pd.DataFrame()


def load_dashboard_data() -> dict[str, Any]:
    paths = SETTINGS.paths
    return {
        "baseline": read_json(paths.baseline_metrics, {}),
        "corrupted": read_json(paths.corrupted_metrics, {}),
        "repaired": read_json(paths.repaired_metrics, {}),
        "baseline_quality": read_json(paths.baseline_quality_report, {}),
        "corrupted_quality": read_json(paths.corrupted_quality_report, {}),
        "repaired_quality": read_json(paths.quality_dir / "repaired_quality_report.json", {}),
        "baseline_freshness": read_json(paths.freshness_report, {}),
        "corrupted_freshness": read_json(paths.quality_dir / "corrupted_freshness_report.json", {}),
        "repaired_freshness": read_json(paths.quality_dir / "repaired_freshness_report.json", {}),
        "corruption_log": read_json(paths.corruption_log, {}),
        "clean": read_frame(paths.clean_json),
        "corrupted_frame": read_frame(paths.corrupted_clean_json),
        "repaired_frame": read_frame(paths.repaired_clean_json),
        "phase1_report": paths.baseline_report,
        "comparison_report": paths.comparison_report,
    }


def _format_rate(value: Any) -> str:
    return f"{float(value):.0%}" if isinstance(value, (int, float)) else "N/A"


def _format_score(value: Any) -> str:
    return f"{float(value):.3f}" if isinstance(value, (int, float)) else "N/A"


def run_script(script_path: Path) -> tuple[int, str]:
    env = os.environ.copy()
    source_path = str(ROOT / "src")
    env["PYTHONPATH"] = source_path + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    completed = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        check=False,
    )
    output = "\n".join(part for part in (completed.stdout.strip(), completed.stderr.strip()) if part)
    for name in ("GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "CUSTOM_LLM_API_KEY"):
        secret = env.get(name)
        if secret:
            output = output.replace(secret, "[REDACTED]")
    return completed.returncode, output or "No output."


def metric_table(data: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for state, label in (("baseline", "Baseline"), ("corrupted", "Corrupted"), ("repaired", "Repaired")):
        metrics = data.get(state, {})
        rows.append(
            {
                "State": label,
                "Documents": len(data.get({"baseline": "clean", "corrupted": "corrupted_frame", "repaired": "repaired_frame"}[state], [])),
                "Hit rate": metrics.get("retrieval_hit_rate"),
                "Token F1": metrics.get("mean_token_f1"),
                "Judge accuracy": metrics.get("judge_accuracy"),
            }
        )
    return pd.DataFrame(rows)


def render_header(page: str) -> None:
    st.markdown('<div class="eyebrow">K4 / L3B / DAY 10 &nbsp;·&nbsp; DATA PIPELINE OBSERVABILITY</div>', unsafe_allow_html=True)
    st.title(page)


with st.sidebar:
    st.markdown(
        '<div class="side-mark">FIELD NOTE 10 / 26</div>'
        '<div class="side-title">Data<br>Observatory</div>'
        '<div class="side-subtitle">RAG pipeline health and recovery</div>',
        unsafe_allow_html=True,
    )
    st.divider()
    page = st.radio(
        "Workspace",
        ("Overview", "Quality Gate", "Recovery Lab", "Paper Records"),
        label_visibility="collapsed",
    )
    st.divider()
    st.caption("PIPELINE STATES")
    st.markdown("Baseline &nbsp;·&nbsp; Corrupted &nbsp;·&nbsp; Repaired", unsafe_allow_html=True)
    st.caption("Snapshot: 24 Crossref records")

render_header(page)
st.markdown(
    '<div class="stage-line"><span class="stage stage-active">01 Baseline</span>'
    '<span class="stage-arrow">→</span><span class="stage stage-failure">02 Corruption</span>'
    '<span class="stage-arrow">→</span><span class="stage stage-repaired">03 Repair</span></div>',
    unsafe_allow_html=True,
)
st.markdown('<div class="rule"></div>', unsafe_allow_html=True)

control_left, control_right = st.columns([1, 1])
with control_left:
    run_baseline = st.button("Run clean baseline", type="primary", icon=":material/play_arrow:", use_container_width=True)
with control_right:
    run_recovery = st.button("Run corruption + repair", icon=":material/healing:", use_container_width=True)

if run_baseline or run_recovery:
    selected_script = ROOT / "script" / ("run_phase1.py" if run_baseline else "run_corruption_flow.py")
    label = "Baseline pipeline" if run_baseline else "Corruption and repair flow"
    with st.spinner(f"Running {label.lower()}..."):
        try:
            return_code, log_output = run_script(selected_script)
        except subprocess.TimeoutExpired:
            return_code, log_output = 124, "Pipeline timed out after 15 minutes."
    st.session_state["last_pipeline_run"] = (label, return_code, log_output)

last_run = st.session_state.get("last_pipeline_run")
if last_run:
    label, return_code, log_output = last_run
    if return_code == 0:
        st.success(f"{label} completed successfully.")
    else:
        st.error(f"{label} exited with code {return_code}.")
    with st.expander("Run output", expanded=return_code != 0):
        st.code(log_output[-12000:], language="text")

data = load_dashboard_data()
baseline = data["baseline"]
corrupted = data["corrupted"]
repaired = data["repaired"]


def render_overview() -> None:
    st.markdown('<p class="lede">One controlled failure, measured against a clean baseline, then recovered from the raw snapshot.</p>', unsafe_allow_html=True)
    values = st.columns(4)
    values[0].metric("Clean papers", len(data["clean"]) or "—")
    values[1].metric("Baseline hit rate", _format_rate(baseline.get("retrieval_hit_rate")))
    values[2].metric("Corrupted token F1", _format_rate(corrupted.get("mean_token_f1")))
    values[3].metric("Repaired token F1", _format_rate(repaired.get("mean_token_f1")))

    st.markdown("### Recovery trace")
    st.caption("The same benchmark is evaluated against each vector collection.")
    states = metric_table(data)
    st.dataframe(
        states,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Hit rate": st.column_config.NumberColumn(format="%.1%%"),
            "Token F1": st.column_config.NumberColumn(format="%.1%%"),
            "Judge accuracy": st.column_config.NumberColumn(format="%.1%%"),
        },
    )
    chart_metric = st.selectbox("Compare metric", ("Hit rate", "Token F1", "Judge accuracy"), index=1)
    chart = states.set_index("State")[[chart_metric]].dropna()
    if not chart.empty:
        st.bar_chart(chart, height=260, color=["#16766c"])
    else:
        st.info("Run Phase 1 and Phase 2 to populate the comparison chart.")

    stale = data["baseline_freshness"].get("stale_ratio")
    quality_status = data["baseline_quality"].get("success")
    st.markdown('<div class="rule"></div>', unsafe_allow_html=True)
    status_left, status_right = st.columns(2)
    with status_left:
        st.markdown("### Baseline data gate")
        if quality_status is True:
            st.success("Great Expectations and freshness SLA passed.")
        elif quality_status is False:
            st.error("Baseline quality gate failed. Inspect the Quality Gate view.")
        else:
            st.info("No quality report found yet.")
    with status_right:
        st.markdown("### Freshness window")
        if stale is not None:
            st.metric("Records older than 180 days", f"{stale:.1%}", delta="25% SLA maximum", delta_color="off")
            st.progress(min(float(stale) / 0.25, 1.0))
        else:
            st.info("Freshness report is not available yet.")


def render_quality() -> None:
    st.markdown('<p class="lede">Schema expectations and freshness SLA, reported before data enters retrieval.</p>', unsafe_allow_html=True)
    report = data["baseline_quality"]
    freshness = data["baseline_freshness"]
    gate, gx_status, fresh_status = st.columns(3)
    gate.metric("Quality gate", "PASS" if report.get("success") else "FAIL" if report else "N/A")
    gx_status.metric("Great Expectations", "PASS" if report.get("expectations_success") else "FAIL" if report else "N/A")
    fresh_status.metric("Freshness SLA", "FRESH" if freshness.get("is_fresh") else "STALE" if freshness else "N/A")

    st.markdown("### Expectation results")
    gx_results = report.get("great_expectations", {}).get("results", [])
    check_rows = []
    for result in gx_results:
        config = result.get("expectation_config", {})
        kwargs = config.get("kwargs", {})
        result_data = result.get("result", {})
        check_rows.append(
            {
                "Check": config.get("type", "Expectation").replace("expect_", "").replace("_", " ").title(),
                "Column": kwargs.get("column", "Table"),
                "Status": "PASS" if result.get("success") else "FAIL",
                "Observed": result_data.get("observed_value", result_data.get("unexpected_count", "—")),
            }
        )
    if check_rows:
        st.dataframe(pd.DataFrame(check_rows), hide_index=True, use_container_width=True)
    else:
        st.info("Run the baseline pipeline to generate expectation results.")

    st.markdown("### Freshness SLA")
    left, right = st.columns([1, 2])
    with left:
        st.metric("Stale records", f"{freshness.get('stale_rows', 0)} / {freshness.get('total_rows', 0)}")
        st.metric("Stale ratio", f"{float(freshness.get('stale_ratio', 0.0)):.2%}")
    with right:
        st.markdown(f"- Maximum allowed stale share: **{float(freshness.get('max_stale_ratio', 0.25)):.0%}**")
        st.markdown(f"- Latest publication: **{freshness.get('latest_published', 'N/A')}**")
        st.markdown(f"- Oldest publication: **{freshness.get('oldest_published', 'N/A')}**")
        st.progress(min(float(freshness.get("stale_ratio", 0.0)) / 0.25, 1.0))


def render_recovery() -> None:
    st.markdown('<p class="lede">Inspect injected faults, compare their impact, and verify recovery from the preserved raw records.</p>', unsafe_allow_html=True)
    states = metric_table(data)
    st.dataframe(states, hide_index=True, use_container_width=True)
    log = data["corruption_log"]
    operations = log.get("operations", [])
    if operations:
        st.markdown("### Injected scenarios")
        scenario_rows = [{"Scenario": item.get("name", "unknown").replace("_", " ").title(), "Rows affected": item.get("count", 0)} for item in operations]
        st.bar_chart(pd.DataFrame(scenario_rows).set_index("Scenario"), height=260, color="#ca614c")
        selected = st.selectbox("Scenario details", [item.get("name", "unknown") for item in operations])
        scenario = next(item for item in operations if item.get("name") == selected)
        st.caption(f"{scenario.get('count', 0)} row(s) affected")
        if scenario.get("affected_rows"):
            st.dataframe(pd.DataFrame(scenario["affected_rows"]), hide_index=True, use_container_width=True)
    else:
        st.info("Run the corruption + repair flow to generate the scenario log.")

    report_text = data["comparison_report"].read_text(encoding="utf-8") if data["comparison_report"].is_file() else ""
    if report_text:
        st.download_button("Download comparison report", report_text, file_name="corruption_report.md", mime="text/markdown", icon=":material/download:")


def render_records() -> None:
    st.markdown('<p class="lede">Search the clean, corrupted, or repaired corpus used by the vector index.</p>', unsafe_allow_html=True)
    state = st.selectbox("Dataset", ("Baseline clean", "Corrupted", "Repaired"))
    frame = {
        "Baseline clean": data["clean"],
        "Corrupted": data["corrupted_frame"],
        "Repaired": data["repaired_frame"],
    }[state]
    if frame.empty:
        st.info("This dataset is not available yet. Run the corresponding pipeline first.")
        return

    query = st.text_input("Find a paper", placeholder="Search title, DOI, category, or summary")
    if query.strip():
        searchable_columns = [name for name in ("paper_id", "title", "categories_joined", "summary") if name in frame.columns]
        mask = frame[searchable_columns].fillna("").astype(str).apply(
            lambda column: column.str.contains(query, case=False, regex=False)
        ).any(axis=1)
        frame = frame.loc[mask]
    display_columns = [name for name in ("paper_id", "title", "published", "categories_joined", "age_days", "summary") if name in frame.columns]
    st.caption(f"{len(frame)} record(s)")
    st.dataframe(frame[display_columns], hide_index=True, use_container_width=True, height=520)


if page == "Overview":
    render_overview()
elif page == "Quality Gate":
    render_quality()
elif page == "Recovery Lab":
    render_recovery()
else:
    render_records()

st.markdown('<div class="rule"></div><div class="eyebrow">K4 / DATA QUALITY → RETRIEVAL → RECOVERY</div>', unsafe_allow_html=True)