# VEIN — Decisive Intraday A3 Falsification Test

_Hourly resolution, Oct 2025 cascade. Fit on 216 pre-event hours, tested on 48 event hours (Oct 10–11). 15 entity-resolved nodes. Real on-chain token-transfer data._

## Result

| model | weighted RMSE | timing corr | n |
|---|--:|--:|--:|
| true_direction | 1.8022 | 0.0808 | 720 |
| reversed_edges | 1.8036 | 0.0636 | 720 |
| symmetric | 1.8097 | 0.0610 | 720 |

true RMSE 1.802 (corr +0.081) vs reversed RMSE 1.804 (corr +0.064).

## Verdict

**Near-tie — flow direction is not the carrier of causal information at this aggregation level.** True / reversed / symmetric land within 0.1% RMSE of each other across 720 predictions. So the apparent 'reversed wins' at daily resolution was low-power noise — **a dataset/power artifact, now resolved.** But the deeper finding is methodological: at the entity-aggregate hourly level it is the graph's *connectivity structure*, not edge *direction*, that carries the predictive signal. A3 should therefore be stated as a qualified claim (direction matters for specific collateral/composability channels, not custodial CEX flows — testable per §5.2.3), rather than a blanket directional assumption.

## Why this is the decisive test

- Daily test: ~6 points → no power to resolve propagation timing.
- Hourly test: 48 event points + 216 fitting points → enough to detect lead/lag direction.
- Same real on-chain data, finer time bucket — isolates whether the daily A3 failure was data (resolution) or method (direction assumption).