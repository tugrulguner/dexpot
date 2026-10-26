# Placement diagnostic hypothesis ledger

Scope: unblock trustworthy performance measurement for Dexpot paired lifecycle #148 without changing production code, native client source, validation, or acceptance budgets. This diagnostic is not candidate qualification.

Retained evidence:
- Hosted macOS control40273301400: full12 A/A,7 pass/5 regression; candidate/enabled skipped.
- Hosted Linux control40273425118: full12 A/A,10 pass/2 FT tail regression; candidate/enabled skipped.
- Single-CPU control40275333243: all12 comparisons invalid. Raw FT records have timeout counters8 or9 and p99 roughly384–693ms; GIL records have bad-response counters1–3 except one valid side. Completed response counts do not erase these failures. No causal explanation inferred from these counters.
- Prior isolated lifecycle mechanism ablations, thread-local encoders, plan ownership, Darwin-policy changes and longer A/B campaigns did not establish a cause/cure. Do not repeat them without new predictions.

## Focused result and distinct full calibration

Hosted run40330478747 at diagnostic5c464791f2d8e5574636042fc399742b68222007 completed8/8 valid records. Disjoint/overlap goodput ratios: GIL1.150219/1.164634; FT1.445424/1.445381. Adjusted-p99 ratios: GIL0.865442/0.857709; FT0.261173/0.398449. This is scoped placement evidence, not feature qualification or a complete control cohort. Full raw evidence is preserved under `~/Projects/dexpot-evidence/paired-lifecycle/placement-40330478747/`.

The next distinct campaign freezes all12 original cells with adjacent15-second identical-main left/right sides (24 trials), side order reversed on odd cell indices, server CPUs[0,1] and client CPUs[2,3] selected from the four allowed runner CPUs. Per-process CPU counts, native client, validator, workload and numerical/resource budgets remain as declared. Shared per-mode launchers preserve identical A/A fingerprints; each launch attests its effective affinity and actual serving PID membership. No candidate/enabled workload runs in this campaign. Every pair must pass; any adverse/invalid pair leaves the full calibration failed. No retries or replaced trials.

## Staged current-candidate campaign after complete calibration

Complete disjoint calibration40331334595 at diagnostic2d46b1cb1abd9d3c33958ef0fc5458229b2e226c passed all12/12 pairs and24/24 valid trials with9,151,390 exact successful replies. It remains calibration-only and does not qualify a feature. This evidence supports the next distinct staged campaign, not retries of any losing cells.

The staged campaign pins mainca4979a6339e533f11ad135bc760aa081f3f60ab and current PRbfebdd64305460631d493b4f2006753cb67db4bf. Both artifacts build/install before timing. On a fresh four-CPU Linux runner, process-local wrappers give each server CPUs[0,1] and each native client CPUs[2,3], with unchanged unrestricted controller placement. It first completes all12 same-main A/A pairs, then only if all pass all12 unused-feature candidate/main pairs, then only if all pass all12 paired-lifecycle/manual-context pairs using identical harness bytes. All sides15s, adjacent reversed order on odd cell indices, unchanged original workload/client/validator/resource budgets and0.90 goodput/1.25 p99 limits. No retries, dropped cells or changed thresholds. Effective masks are attested before exec and checked against all observed serving PIDs. Any missing/wrong attestation invalidates the final verdict. Every adverse and invalid record remains retained. Earlier campaign failures remain failed; this narrower placement environment cannot establish macOS or unrestricted-CPU qualification.

Ranked hypotheses:
1. Client/server CPU overlap amplifies competition. Prediction: with the same two-CPU mask per server/client, separating masks reduces adverse FT flat tails/invalid counters in two order-reversed pairs. Smallest next test: frozen main only, GIL+FT flat, overlap/disjoint/disjoint/overlap,15s each,8 records. Controller mask remains unchanged and is recorded. This tests a placement effect, not lifecycle overhead or general stability.
2. Tail variation remains within the server or host even with disjoint masks. Prediction: the disjoint sides remain unstable or invalid; do not run a larger candidate cohort or infer placement cured it.
3. Control-only topology alters client/server behavior rather than improving representativeness. Prediction: response/transport/preflight or runtime/resource checks fail. Preserve invalid results and inspect those exact failures; do not loosen checks or use a favorable ratio.

Protocol:
- Native wrk executable, validator, handler/models and base wheel are unchanged. Script wrappers set only their own process affinity before exec, and attest every effective mask. Server has two CPUs in every side; client has two CPUs in every side. Original pool16, connections16, client threads4, FT cap32 and resource/numeric budgets retained.
- Fresh installed main artifact at ca4979a6339e533f11ad135bc760aa081f3f60ab, CPython3.14.7 GIL/FT, msgspec0.22.0. Unforced server lifecycle checks plus unsupported-extension FT negative controls before timing.
- Eight predeclared15s trials, no retries, no changed cells after observation. Every trial checks exact successful responses, zero errors, installed artifact/runtime, resources, overload/churn and cleanup.
- Ratios are disjoint/overlap. Report both pairs per mode, every adverse/invalid side, and actual masks. Never describe this as complete A/A cohort or promotion.
- If scoped placement benefit is not demonstrated, stop this hypothesis rather than starting another long hosted cohort. If it is, propose and freeze a distinct full-control protocol; do not relabel these eight trials as qualification.
