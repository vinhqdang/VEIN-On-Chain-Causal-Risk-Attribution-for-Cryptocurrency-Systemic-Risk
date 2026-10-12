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

**No direction effect detected**: the RMSE gap is within the tie threshold or the paired CI includes 0. This is a statement about these data and this test only; it does not identify why the daily result differed, and it does not show that connectivity rather than direction carries the signal. RMSE true 1.8022, reversed 1.8036, symmetric 1.8097 over 720 predictions; relative RMSE gap reversed vs true +0.08% (tie threshold 2%). Paired squared-error difference, reversed minus true +0.0066, 95% CI [-0.0035, +0.0166]; symmetric minus true +0.0127, 95% CI [+0.0003, +0.0250] (circular blocks of 24 h over 48 event hours).

## Why this is the decisive test

## Design

- Daily test: ~6 event points. Hourly test: 48 event hours x 15 entities = 720 cells, fitted on 216 pre-event hours.
- Same on-chain data at a finer time bucket. The 48 event hours form two 24-hour blocks, so bootstrap intervals are indicative.