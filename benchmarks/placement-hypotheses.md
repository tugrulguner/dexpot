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

## Post-failure localization, not another qualification retry

Staged run40333073633 completed all12A/A passing and11/12A/B passing. The retained FTmixed1 loss was p99candidate18608us/base11962us (ratio1.555593) withgoodput1.038772. Enabled cohort skipped. All48 timed records had9,443,298 exactgood replies, nobad/transport counters; effective masks passed. Nothing clears this failure.

A direct source check found21 base versus24 candidate Dex initialization attributes, below a hypothesized30-key boundary; it establishes no dictionary representation transition. In the losing pair, completedroute shares were main flat0.3455/nested0.2686/cpu0.2856/io0.1004 versuscandidate0.3697/0.2518/0.2854/0.0930. These counters alone do not identify the p99 cause.

Next discriminating probe: separately instrument FTmixed1 in main/pr/pr/main order,30s each, same two-CPU disjoint placement and unchanged native client/validation/concurrency. Sample one in32 server requests into thread-local records, up to4000 records/thread; preserve sampled/dropped totals. Measure exclusive read (includes receive), match, handler (nested flat calls excluded), EndpointPlan.encode, send, and remaining residual wall/threadCPU. Every sampled request must prove each intended hook ran exactly once; preserve codec dispatch markers. Native client latencies and sampled server intervals are distinct. If time is concentrated in one non-socket stage, narrow that boundary next; if the extra wall time is spread or the instrumented workload no longer shows the failure, record that limit instead of blaming GC/scheduling or promoting an optimization. No candidate-qualified verdict or enabled cohort can arise from this diagnostic.

Local real-HTTP hook preflight: GIL and FT installed candidate consumers each returned512 checked replies spanning allfour routes. Allfive actual stage hooks were verified exactly once perselected request, no overlapping-span report, clean teardown. Unit/controller protocol tests20passed; Actionlint and offline pedanticZizmor clean. No production code changed.

## Stage-probe result and retained reporting failure

Run40339357155 at diagnostic0c58bbbd875011848df2e13568641fd0806e69eb completed four valid timed recordings but its final comparator failed: `glob('*.json')` mistook diagnostic `stage-report-PID.json` sidecars for trial records without cell identifiers. Original controller verdict remains diagnostic-invalid. No timing was rerun or replaced. An offline derived view copies only the original byte-identical manifest/trial/preflight inputs; the unchanged runner then validates and compares both pairs. Derived goodput ratios1.012653/1.032944 and p99ratios0.952954/1.031073 do not reproduce the acceptance loss under instrumentation and cannot clear it.

Across four recordings:5,186,203 exactgood responses;158,755 retained sampled intervals;3,283 additional samples dropped by declared per-thread caps. All retained sampled requests prove allfive hooks executed once, with no overlapping-span flags. Of223 retained intervals at least10ms,215 were dominated by route matching, in BOTH main and candidate. Capped periodic samples do not establish a population percentile or candidate-specific cause. Parent analysis/checksums69files are retained in `~/Projects/dexpot-evidence/paired-lifecycle/stage-40339357155/`, including the original invalid verdict and interrupted analysis attempt.

A TDD regression isolates sidecars under `stage-probes/`, outside the flat trial inventory. Corrected GIL/FT real-HTTP hook smoke and12 focused tests pass. Future hosted runs require an explicit `benchmarks/stage-run-request.json` change so a reporting-only repair cannot accidentally repeat timings. No production fix or performance clearance is demonstrated. Independent source/hypothesis review is pending.

## Routing ownership microprobe

A new routing-only local macOS FT microprobe completed eight ordered rounds (original, bound-shared, local-proxy, local-dict, then reverse),16 persistent serving-style worker threads,1,572,864 identity/capture-checked route lookups. Each path was fresh percall. Shared binding removed repeated self/plan/router attribute reads but retained one shared immutable mapping. Local proxy preserved the same mappingproxy type and route-value identities but allocated one route dictionary perthread. Actual identities verified1 shared mapping versus16 distinct local proxies.

Local-proxy/bound-shared summed threadCPU ratios were0.138264 and0.159583; batch-wall-p99 ratios0.060098/0.073397. This is a scoped microprobe of a plausible shared lookup mechanism, NOT HTTP latency or a candidate-specific lifecycle cause. Original `elapsed_ns` includes warmup/barrier synchronization; do not use it as pure lookup throughput. The exact measured source was reconstructed from the three subsequent non-timed edits and verified against its predeclared SHA256; all12 evidence files are preserved/checksummed at `~/Projects/dexpot-evidence/paired-lifecycle/route-lookup-microprobe-local/`. The current helper labels the aggregate wall interval explicitly.

Four RED/GREEN parity/fallback tests cover immutable mapping ownership, identical route values, literal hit,404,405, dynamic capture and an explicit original fallback to avoid recursive diagnostic wrappers. Next discriminating test is native ordinary HTTP on a frozen main artifact, original/bound-shared/local-proxy and reversed order, under the validated disjoint Linux placement. No production change is authorized for promotion by this microprobe; sustained HTTP, resources, all-contract correctness and original candidate gates remain required. Preparation of that bounded HTTP fixture/driver is delegated; no hosted timing has been launched.

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
