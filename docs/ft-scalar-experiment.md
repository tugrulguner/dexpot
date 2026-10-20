# Isolated FT scalar-response experiment

This candidate extracts only flat checked-response preparation from draft #116 onto
main at `e703edf18d1526ebc2a91398f18c9e808e5cf5aa`. Main's connection ownership,
SO_REUSEPORT listeners, queueing, deadlines and GIL startup binding remain unchanged.
The earlier combined-runtime measurements do not qualify these isolated bytes.

## Mechanism and boundary

Only an incumbent native whole-codec preparer is considered for replacement; an
existing graph preparer is retained by identity, without a scalar wrapper. Under the
current runtime policy this targets FT Darwin's native compatibility path, not the
GIL/Linux graph paths. The Linux screen did not earn replacement of that graph.

Eligible exact Struct instances contain only required unconstrained primitive fields,
with no defaults/factories, tags, array-like or dict-enabled layout, custom metaclasses,
or custom instance attribute access. Registration captures original slot descriptors and emits direct primitive
checks and public-field projection. Each serving thread binds its own function/globals
from the canonical code. The normal JSON encoder remains in use.

Other schemas and values retain the incumbent preparer. Changed descriptors or attribute
access, deleted slots, subclasses and primitive mismatches return to that same runtime's
fallback. Float values must remain finite. Capturing validated fields does not promise
an atomic snapshot under concurrent application mutation.

The optimization is selected from actual GIL state at endpoint registration; this is
separate from scheduler binding at `serve()`. A later GIL change does not rebuild the
registered response strategy. Standard GIL registration retains the exact incumbent
preparer, without a new request-path wrapper. No new public setting is introduced.

## Acceptance

First require unchanged semantic suites on standard and genuine unforced FT Python,
plus direct activation, fallback and actual HTTP recovery checks. Then compare frozen
installed baseline/candidate artifacts under unchanged clients, validators, workloads
and declared resource limits. Keep all earlier #116 failures and new adverse trials.
A focused screen is not the complete cross-platform qualification and does not justify
merging or a speed claim. No client experiments or system-setting changes are included.

## Retained focused screens

The [macOS screen](../benchmarks/scalar_response/isolated-screen.json) and
[Linux-container screen](../benchmarks/scalar_response/linux-screen.json) both
measured `92e8561aa96f7e799279b89c9c9453834f9e0cda`, before the native-only
selection correction. Neither passed. All eight declared records per platform,
including the two Linux timeout-invalid records, remain represented. Short codec,
reduced-concurrency and tracing diagnostics do not replace their adverse results.

The correction retains an existing graph by identity and has a red-before/green-after
registration regression. It does not claim to fix macOS HTTP tails. Earlier figures
do not qualify the corrected source; final installed-artifact and performance gates
remain open. The independent source review of `92e8561` found no demonstrated
contract regression but did not approve performance or the later selection delta.
