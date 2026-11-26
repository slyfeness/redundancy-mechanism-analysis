# LedgerCredit v2.2

The `C_W` preset uses behavioural uptake and two-pass event gating. The
`C_W_v211` ablation uses the legacy Q3 adoption verdicts and disables
`route_errors`, `e3_diagnostic`, and `gate_two_pass`. The other presets keep
their utility and allocation modes and use v2.2 events where they use a ledger.

## Ledger

The v13.5 ledger layers uptake and route labels over the existing v13.4
bookkeeping. A fact is taken up if its object is targeted by the current or
next search, is on the answer chain, or is named in the next reasoning or
query. At the last step, the submitted answer is also eligible. The provider
extracts this text from the trajectory. A fact that meets one of these
criteria later gets a late uptake entry on that step.

The eligible route labels are 知错不改, 坚持无据候选, and 沿限定走. They represent
persisting in a refuted route, holding an unsupported candidate, and repeatedly
searching under a self-imposed restriction. The default run lengths are
`k_hold=3` and `k_restrict=2`. Unsupported assertions are diagnostics.

In v13.5.1, an unsupported hold advances only when the query names the
candidate or an object linked to it. A restriction run advances only when
the target is still unknown and the query names no object already in the
ledger. A query that checks a known object's attributes resets that run.

## Providers and credit

- The online provider runs Q1, Q2, Q4, and Q5 as needed with the frozen
  prompts. Q1 early stopping still applies. Passes a and b use separate Q2
  caches. The default `q3_audit_rate=0.1` samples whole groups, with Q3 output
  stored under `q3_audit` on pass a.
- The recorded provider reprojects v13.4 records with behavioural uptake and
  retains the original adoption verdicts for audit. It loads a matching
  second pass when available. For the v2.1.1 ablation, it uses the original
  v13.4 records and derived rows directly.
- Recorded v13.5 ledgers use the configured route thresholds. Replay keeps
  receipts for each pass separate. An incomplete supplied pass triggers
  outcome-only credit for the group. Saved ledgers sent straight to the
  trainer must match the preset's uptake method.
- A route error is charged to the unit that chose the search. Each unit
  takes at most one charge, with successive charges drawn from one
  geometrically decaying error budget. The failure-trajectory waste discount
  applies to waste events.
- With both passes available, a negative event is kept if pass b has an event
  of the same family on the same unit. Positive events come from pass a.
  Preset `D` shuffles eligible roles and weights using the existing
  procedure, including those induced by route errors.

The credit metrics include route-label unit counts, negative events dropped
by family, and the number of facts marked as unadopted by the program.
