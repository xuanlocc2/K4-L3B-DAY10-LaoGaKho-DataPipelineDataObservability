from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from core.utils import ensure_parent, write_json
from ingestion.cleaning import _build_text_for_embedding


def corrupt_clean_dataframe(
    df: pd.DataFrame,
    output_log_path,
    seed: int = 42,
) -> pd.DataFrame:
    """Simulate 6 deterministic data corruption scenarios.
    
    1. Drop latest records
    2. Blank summary
    3. Inject noise
    4. Truncate title to <8 chars
    5. Stale date (push published into the past)
    6. Duplicate rows
    """
    random.seed(seed)
    
    df = df.copy()
    
    log_entries = []
    affected_paper_ids = []
    run_id = f"corrupt_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    
    num_rows = len(df)
    if num_rows == 0:
        return df
    
    scenario_num = 1
    
    if num_rows >= 3:
        drop_count = min(2, num_rows // 4)
        drop_indices = df.tail(drop_count).index.tolist()
        drop_ids = df.loc[drop_indices, "paper_id"].tolist()
        df = df.drop(index=drop_indices)
        affected_paper_ids.extend(drop_ids)
        log_entries.append({
            "scenario": scenario_num,
            "scenario_name": "drop_latest_records",
            "affected_paper_ids": drop_ids,
            "before_count": num_rows,
            "after_count": len(df),
            "run_id": run_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })
        scenario_num += 1
    
    if len(df) >= 2:
        blank_indices = random.sample(df.index.tolist(), min(2, len(df)))
        blank_ids = []
        for idx in blank_indices:
            affected_paper_ids.append(df.loc[idx, "paper_id"])
            blank_ids.append(df.loc[idx, "paper_id"])
            before_snippet = df.loc[idx, "summary"][:50] if df.loc[idx, "summary"] else ""
            df.at[idx, "summary"] = ""
            df.at[idx, "summary_chars"] = 0
        log_entries.append({
            "scenario": scenario_num,
            "scenario_name": "blank_summary",
            "affected_paper_ids": blank_ids,
            "before_snippet": before_snippet,
            "run_id": run_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })
        scenario_num += 1
    
    if len(df) >= 2:
        noise_indices = random.sample(df.index.tolist(), min(2, len(df)))
        noise_ids = []
        for idx in noise_indices:
            affected_paper_ids.append(df.loc[idx, "paper_id"])
            noise_ids.append(df.loc[idx, "paper_id"])
            before_text = df.loc[idx, "summary"][:50] if df.loc[idx, "summary"] else ""
            noise = " XXXCORRUPTED_ENTRY_PLEASE_IGNORE_XXX "
            if df.loc[idx, "summary"]:
                insert_pos = random.randint(0, len(df.loc[idx, "summary"]))
                new_summary = (
                    df.loc[idx, "summary"][:insert_pos]
                    + noise
                    + df.loc[idx, "summary"][insert_pos:]
                )
            else:
                new_summary = noise
            df.at[idx, "summary"] = new_summary
            df.at[idx, "summary_chars"] = len(new_summary)
        log_entries.append({
            "scenario": scenario_num,
            "scenario_name": "inject_noise",
            "affected_paper_ids": noise_ids,
            "before_snippet": before_text,
            "run_id": run_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })
        scenario_num += 1
    
    if len(df) >= 1:
        truncate_idx = random.choice(df.index.tolist())
        affected_paper_ids.append(df.loc[truncate_idx, "paper_id"])
        before_title = df.loc[truncate_idx, "title"]
        df.at[truncate_idx, "title"] = before_title[:7] if len(before_title) > 7 else before_title
        log_entries.append({
            "scenario": scenario_num,
            "scenario_name": "truncate_title",
            "affected_paper_ids": [df.loc[truncate_idx, "paper_id"]],
            "before_title": before_title,
            "after_title": df.loc[truncate_idx, "title"],
            "run_id": run_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })
        scenario_num += 1
    
    if len(df) >= 2:
        stale_indices = random.sample(df.index.tolist(), min(2, len(df)))
        stale_ids = []
        for idx in stale_indices:
            affected_paper_ids.append(df.loc[idx, "paper_id"])
            stale_ids.append(df.loc[idx, "paper_id"])
            before_date = df.loc[idx, "published"]
            try:
                if before_date:
                    old_date = datetime.fromisoformat(before_date)
                    new_date = old_date - timedelta(days=365)
                    df.at[idx, "published"] = new_date.strftime("%Y-%m-%d")
                    df.at[idx, "age_days"] = df.loc[idx, "age_days"] + 365
            except (ValueError, TypeError):
                df.at[idx, "published"] = "2020-01-01"
                df.at[idx, "age_days"] = 2000
        log_entries.append({
            "scenario": scenario_num,
            "scenario_name": "stale_date",
            "affected_paper_ids": stale_ids,
            "before_date": before_date,
            "run_id": run_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })
        scenario_num += 1
    
    if len(df) >= 1:
        dup_idx = random.choice(df.index.tolist())
        dup_row = df.loc[[dup_idx]].copy()
        dup_row["paper_id"] = df.loc[dup_idx, "paper_id"] + "_DUP"
        affected_paper_ids.append(dup_row["paper_id"].iloc[0])
        before_count = len(df)
        df = pd.concat([df, dup_row], ignore_index=True)
        log_entries.append({
            "scenario": scenario_num,
            "scenario_name": "duplicate_row",
            "affected_paper_ids": [df.loc[dup_idx, "paper_id"]],
            "new_duplicate_id": dup_row["paper_id"].iloc[0],
            "before_count": before_count,
            "after_count": len(df),
            "run_id": run_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })
        scenario_num += 1
    
    affected_paper_ids = list(set(affected_paper_ids))
    affected_mask = df["paper_id"].isin(affected_paper_ids)
    
    for idx in df[affected_mask].index:
        row = df.loc[idx].to_dict()
        df.at[idx, "text_for_embedding"] = _build_text_for_embedding(row)
    
    for idx in df.index:
        row = df.loc[idx].to_dict()
        text_val = df.at[idx, "text_for_embedding"]
        if pd.isna(text_val) or text_val == "" or str(text_val).strip() == "":
            df.at[idx, "text_for_embedding"] = _build_text_for_embedding(row)
    
    ensure_parent(output_log_path)
    write_json(output_log_path, {
        "run_id": run_id,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "scenarios": log_entries,
        "total_affected": len(affected_paper_ids),
        "affected_paper_ids": affected_paper_ids,
    })
    
    return df
