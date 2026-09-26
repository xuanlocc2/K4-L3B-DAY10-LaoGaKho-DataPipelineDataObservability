import sys
sys.path.insert(0, 'src')

import pandas as pd, json
from observability.diff import dataset_fingerprint, diff_datasets
from ingestion.crossref import load_raw_records

# Load source
source_records = load_raw_records('data/raw/crossref_records.json')
print(f"Source records: {len(source_records)}")
print(f"Source paper_ids: {[r['paper_id'] for r in source_records[:5]]}")

# Load corrupted CSV
df = pd.read_csv('data/clean/papers_clean.csv')
current_records = df.to_dict(orient='records')
print(f"\nCurrent records: {len(current_records)}")
print(f"Current paper_ids: {[r['paper_id'] for r in current_records[:5]]}")

# Fingerprints
fp_source = dataset_fingerprint(source_records)
fp_current = dataset_fingerprint(current_records)
print(f"\nSource fp row_count: {fp_source['row_count']}")
print(f"Current fp row_count: {fp_current['row_count']}")

# Diff
changes = diff_datasets(source_records, current_records)
print(f"\nDiff changes: {len(changes)}")
for c in changes:
    print(f"  {c['change_type']}: {c['paper_id']}")
