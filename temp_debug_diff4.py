import sys
sys.path.insert(0, 'src')
import pandas as pd, json
from observability.diff import _normalize_value

# Load source
source_data = json.load(open('data/raw/crossref_records.json', encoding='utf-8'))
src_record = next(r for r in source_data if r.get('paper_id') == '10.1145/3637528.3671802')

# Load current
df = pd.read_csv('data/clean/papers_clean.csv')
cur_records = df.to_dict('records')
cur_record = next(r for r in cur_records if r.get('paper_id') == '10.1145/3637528.3671802')

# Compare all fields
all_fields = sorted(set(list(src_record.keys())))
print(f"Source keys: {all_fields}")
csv_keys = sorted(set(list(cur_record.keys())))
print(f"CSV keys: {csv_keys}")
print()
for field in all_fields:
    sv = src_record.get(field)
    cv = cur_record.get(field)
    sn = _normalize_value(sv)
    cn = _normalize_value(cv)
    if sn != cn:
        print(f"DIFFER: {field}")
        print(f"  source: {repr(sv)[:80]}")
        print(f"  csv:    {repr(cv)[:80]}")
        print(f"  norm source: {repr(sn)[:80]}")
        print(f"  norm csv:    {repr(cn)[:80]}")
    else:
        print(f"SAME:   {field}")
