import json
b = json.load(open('data/results/baseline_metrics.json'))
c = json.load(open('data/results/corrupted_metrics.json'))
r = json.load(open('data/results/repaired_metrics.json'))
for label, m in [('Baseline', b), ('Corrupted', c), ('Repaired', r)]:
    print(f'{label}: samples={m.get("samples")}, hit_rate={m.get("retrieval_hit_rate")}, token_f1={m.get("mean_token_f1")}, judge_acc={m.get("judge_accuracy")}, judge_score={m.get("mean_judge_score")}')
