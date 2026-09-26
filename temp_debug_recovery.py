import sys
sys.path.insert(0, 'src')

import pandas as pd, json, tempfile
from pathlib import Path
from datetime import UTC, datetime
from core.utils import read_json, write_json, ensure_parent
from observability.diff import dataset_fingerprint, diff_datasets, normalize_field_diff
from ingestion.crossref import load_raw_records
from ingestion.cleaning import build_clean_dataframe
from ingestion.crossref import PaperRecord

# Step 1: Load source
source_records_raw = read_json('data/raw/crossref_records.json')
print(f"Source records: {len(source_records_raw)}")

# Step 2: Load corrupted CSV
df_csv = pd.read_csv('data/clean/papers_clean.csv')
current_records = df_csv.to_dict(orient='records')
print(f"Current records from CSV: {len(current_records)}")

# Step 3: Diff
fp_source = dataset_fingerprint(source_records_raw)
fp_current = dataset_fingerprint(current_records)
print(f"Source fp: {fp_source['row_count']} rows")
print(f"Current fp: {fp_current['row_count']} rows")

changes = diff_datasets(source_records_raw, current_records)
print(f"Changes: {len(changes)}")
for c in changes:
    print(f"  {c['change_type']}: {c['paper_id']} sev={c['severity']}")

# Step 4: Merge
source_ids = {r.get('paper_id', '') for r in source_records_raw}
current_ids = {r.get('paper_id', '') for r in current_records}
merged = {r.get('paper_id', ''): r for r in source_records_raw if r.get('paper_id')}
for rec in current_records:
    pid = rec.get('paper_id', '')
    if pid and pid not in merged:
        merged[pid] = rec

restored = list(merged.values())
print(f"\nMerged records: {len(restored)}")

# Step 5: Rebuild computed columns for CSV target
run_date = datetime.now(UTC)
paper_records = [
    PaperRecord(
        paper_id=r.get('paper_id', ''),
        title=r.get('title', ''),
        summary=r.get('summary', ''),
        authors=r.get('authors', []),
        categories=r.get('categories', []),
        primary_category=r.get('primary_category', ''),
        published=r.get('published', ''),
        updated=r.get('updated', ''),
        abs_url=r.get('abs_url', ''),
        pdf_url=r.get('pdf_url', ''),
        comment=r.get('comment', ''),
    )
    for r in restored
    if r.get('paper_id')
]
df_computed = build_clean_dataframe(paper_records, run_date)
print(f"Computed df rows: {len(df_computed)}")
print(f"Computed columns: {list(df_computed.columns)}")

# Step 6: Write to temp CSV
tmp_path = Path('data/clean/papers_clean_recovery_test.csv')
df_computed.to_csv(tmp_path, index=False, encoding='utf-8')
df_verify = pd.read_csv(tmp_path)
print(f"\nWritten CSV rows: {len(df_verify)}")
print(f"Written CSV columns: {len(df_verify.columns)}")
print(f"First paper_id: {df_verify['paper_id'].iloc[0] if len(df_verify) > 0 else 'NONE'}")
print(f"Last paper_id: {df_verify['paper_id'].iloc[-1] if len(df_verify) > 0 else 'NONE'}")
