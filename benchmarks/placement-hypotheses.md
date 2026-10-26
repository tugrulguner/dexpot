# Placement diagnostic hypothesis ledger

Scope: unblock trustworthy performance measurement for Dexpot paired lifecycle #148 without changing production code, native client source, validation, or acceptance budgets. This diagnostic is not candidate qualification.

Retained evidence:
- Hosted macOS control40273301400: full12 A/A,7 pass/5 regression; candidate/enabled skipped.
- Hosted Linux control40273425118: full12 A/A,10 pass/2 FT tail regression; candidate/enabled skipped.
- Single-CPU control40275333243: all12 comparisons invalid. Raw FT records have timeout counters8 or9 and p99 roughly384–693ms; GIL records have bad-response counters1–3 except one valid side. Completed response counts do not erase these failures. No causal explanation inferred from these counters.
- Prior isolated lifecycle mechanism ablations, thread-local encoders, plan ownership, Darwin-policy changes and longer A/B campaigns did not establish a cause/cure. Do not repeat them without new predictions.

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
