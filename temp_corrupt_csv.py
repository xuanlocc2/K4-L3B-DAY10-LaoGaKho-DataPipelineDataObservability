"""Corrupt the CSV by removing the second data row (paper 10.1145/3637528.3671802)."""
import csv
import shutil

src = 'data/clean/papers_clean.csv'
backup = 'data/clean/papers_clean.csv.pretest.bak'

# Read all rows
with open(src, 'r', encoding='utf-8') as f:
    reader = csv.reader(f)
    rows = list(reader)

print(f'Original rows (including header): {len(rows)}')
print(f'Header: {rows[0][:3]}')
print(f'First data row: {rows[1][0]}')
print(f'Second data row (will delete): {rows[2][0]}')

# Remove the second data row (index 2, after header at index 1)
corrupted_rows = [rows[0]] + rows[2:]  # keep header + rows[3:]

print(f'Corrupted rows (including header): {len(corrupted_rows)}')
print(f'Data rows: {len(corrupted_rows) - 1}')

# Write corrupted CSV
with open(src, 'w', encoding='utf-8', newline='') as f:
    writer = csv.writer(f)
    writer.writerows(corrupted_rows)

print(f'Written corrupted CSV: {src}')
