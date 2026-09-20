# Decision Scoring Spec

Nous is an Open Intelligence Runtime.

## Dimensions

Initial scoring dimensions:

- expected quality
- reliability
- capability fit
- privacy fit
- information gain
- reversibility
- cost
- latency
- risk
- uncertainty

## Normalization

Scores are bounded to `[0.0, 1.0]`.

Cost, latency, risk, and uncertainty are negative dimensions. Lower values produce better normalized scores.

Unknown values default to neutral normalized value and receive an uncertainty penalty.

NaN and Infinity are rejected into neutral bounded values and cannot appear in output scores.

## Ranking

Ranking is deterministic:

1. eligible candidates before rejected candidates
2. higher normalized score first
3. lower uncertainty penalty first
4. stable candidate ID tie-break

## Pareto Reduction

Pareto reduction can be enabled or disabled per request.

Dominated candidates record `PARETO_DOMINATED`.

Candidates with unique capability advantages are preserved.

Fallback-only candidates can be preserved by configuration.
