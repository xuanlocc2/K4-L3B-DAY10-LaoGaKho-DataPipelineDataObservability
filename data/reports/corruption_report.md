# Data Corruption and Repair Report

## RAG Evaluation
| Metric | Baseline | Corrupted | Repaired |
|---|---:|---:|---:|
| Retrieval Hit Rate | 1.0000 | 1.0000 | 1.0000 |
| Mean Token F1 | 1.0000 | 0.8000 | 1.0000 |
| Judge Accuracy | 1.0000 | 0.8000 | 1.0000 |
| Mean Judge Score | 5.0000 | 4.2000 | 5.0000 |

## Data Quality Gate
| State | Gate | Great Expectations | Freshness |
|---|---|---|---|
| Corrupted | FAIL | FAIL | FRESH |
| Repaired | PASS | PASS | FRESH |

## Freshness Details
- Corrupted stale rows: 4 / 21 (19.05%)
- Repaired stale rows: 1 / 24 (4.17%)

## Interpretation
Compare the corrupted metrics with baseline to observe impact, then compare repaired metrics with baseline to assess recovery. Values above are produced by the evaluation pipeline.
