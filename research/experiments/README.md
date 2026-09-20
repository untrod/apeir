# Research Experiments

Reproducible experiment definitions. Each experiment must include:
- Hypothesis reference
- Independent variable(s)
- Dependent variable(s) (metrics)
- Controlled variables
- Sample size and statistical plan
- Ablation conditions
- Raw data location
- Analysis notebook location

## Experiment Registry

| ID | Hypothesis | Status | Last Run | Result |
|----|-----------|--------|----------|--------|
| E1 | H1: Context VM vs full history | NOT RUN | — | — |
| E2 | H2: State-aware scheduling | NOT RUN | — | — |
| E3 | H3: Durable speculation | NOT RUN | — | — |
| E4 | H4: Proof-carrying execution | NOT RUN | — | — |
| E5 | H5: Digital twin scheduling | NOT RUN | — | — |
| E6 | H6: Pareto routing vs scalar | NOT RUN | — | — |

## Experiment Template

```python
# experiment_<id>.py
"""
Hypothesis: <H#>
Independent: <what we change>
Dependent: <what we measure>
Sample: <N per condition>
Statistical test: <test name, alpha level>
"""

def run_experiment():
    baseline = run_baseline()
    treatment = run_treatment()
    result = statistical_test(baseline, treatment)
    save_result(result)
    return result
```
