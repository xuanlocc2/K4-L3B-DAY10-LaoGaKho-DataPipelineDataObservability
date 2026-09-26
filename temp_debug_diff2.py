import sys
sys.path.insert(0, 'src')

import pandas as pd, json
from observability.diff import dataset_fingerprint, diff_datasets

# Load source from crossref_records.json (like _resolve_recovery_source does)
from core.utils import read_json
source_data = read_json('data/raw/crossref_records.json')
print(f"Source type: {type(source_data)}, len: {len(source_data)}")
print(f"Source[0] type: {type(source_data[0])}")
print(f"Source[0] keys: {list(source_data[0].keys())}")
print(f"Source paper_ids: {[r.get('paper_id', 'NO_ID') for r in source_data[:5]]}")

# Load corrupted CSV
df = pd.read_csv('data/clean/papers_clean.csv')
current_records = df.to_dict(orient='records')
print(f"\nCurrent records: {len(current_records)}")
print(f"Current[0] type: {type(current_records[0])}")
print(f"Current paper_ids: {[r.get('paper_id', 'NO_ID') for r in current_records[:5]]}")

# Fingerprints
fp_source = dataset_fingerprint(source_data)
fp_current = dataset_fingerprint(current_records)
print(f"\nSource fp row_count: {fp_source['row_count']}, sha256: {fp_source['file_sha256'][:20]}")
print(f"Current fp row_count: {fp_current['row_count']}, sha256: {fp_current['file_sha256'][:20]}")

# Diff
changes = diff_datasets(source_data, current_records)
print(f"\nDiff changes: {len(changes)}")
for c in changes:
    print(f"  {c['change_type']}: {c['paper_id']} sev={c['severity']}")
