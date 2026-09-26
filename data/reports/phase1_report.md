# Phase 1 Baseline Report

## Source

| Field | Value |
| --- | --- |
| Source | Crossref REST API |
| Query | agentic retrieval augmented generation large language model |
| Filter | from-pub-date:2026-03-30,has-abstract:true |
| Clean records | 24 |
| Run at | 2026-09-26T04:28:24.480604+00:00 |

## Baseline metrics

| Metric | Value |
| --- | ---: |
| Samples | 10 |
| Retrieval hit rate | 1.0000 |
| Mean Token F1 | 0.8000 |
| Judge accuracy | 0.7000 |
| Mean judge score | 3.8000 |

## Data quality and freshness

| Signal | Value |
| --- | --- |
| Great Expectations pass | True |
| Quality gate pass | True |
| Total rows | 24 |
| Stale rows | 0 |
| Stale ratio | 0.0000 |
| Freshness SLA pass | True |
| Latest published | 2026-09-15 |
| Oldest published | 2026-04-01 |

## Notes

- Ragas: `{'skipped': 'Set RUN_RAGAS=1 to enable the slower Ragas pass.'}`
- This report is generated from pipeline artifacts; do not edit metric values manually.
