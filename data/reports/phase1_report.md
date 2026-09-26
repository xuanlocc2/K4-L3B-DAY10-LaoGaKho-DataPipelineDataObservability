# Phase 1: Baseline Pipeline Report

## Data Source
- Source: Crossref REST API
- Query: agentic retrieval augmented generation large language model
- Records ingested: 24
- Records cleaned: 24

## Baseline Evaluation
| Metric | Result |
|---|---:|
| Evaluation samples | 10 |
| Retrieval Hit Rate | 1.0000 |
| Mean Token F1 | 1.0000 |
| Judge Accuracy | 1.0000 |
| Mean Judge Score | 5.0000 |

## Data Quality
- Overall Quality Gate: **PASS**
- Great Expectations: **PASS**

## Freshness
- Status: **FRESH**
- Latest publication date: 2026-07-22
- Oldest publication date: 2026-03-28
- Stale rows: 1 / 24
- Stale ratio: 4.17%

## Artifacts
- Clean data: `data/clean/papers_clean.csv`
- Benchmark: `data/eval/test_set.json`
- Metrics: `data/results/baseline_metrics.json`
- Quality: `data/quality/baseline_quality_report.json`
