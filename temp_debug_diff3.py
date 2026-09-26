import sys
sys.path.insert(0, 'src')
import pandas as pd, json
from observability.diff import _normalize_value

# Load source
source_data = json.load(open('data/raw/crossref_records.json', encoding='utf-8'))
src_record = next(r for r in source_data if r.get('paper_id') == '10.1145/3637528.3671802')
print("SOURCE 10.1145/3637528.3671802:")
for k, v in src_record.items():
    print(f"  {k}: {repr(v)[:80]}")

# Load current
df = pd.read_csv('data/clean/papers_clean.csv')
cur_record = next(r for r in df.to_dict('records') if r.get('paper_id') == '10.1145/3637528.3671802')
print("\nCSV 10.1145/3637528.3671802:")
for k, v in cur_record.items():
    print(f"  {k}: {repr(v)[:80]}")

# Compare
print("\nField diffs:")
for k in src_record:
    s_val = src_record.get(k)
    c_val = cur_record.get(k)
    if _normalize_value(s_val) != _normalize_value(c_val):
        print(f"  {k}: source={repr(s_val)[:60]} | csv={repr(c_val)[:60]}")
