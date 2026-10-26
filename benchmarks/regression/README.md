# Bounded regression screen

A maintainer diagnostic for installed Dexpot wheels. This is **not** a general framework
ranking, scheduled-arrival latency/SLO test, or release qualification. It changes no runtime
code. Do not close the broader benchmark-harness contributor issue on the strength of this
screen.

## Recorded diagnostic baseline

[`baseline-macos-v071.json`](baseline-macos-v071.json) records the repaired harness's macOS
v0.7.1 matrix: **12/12 valid trials and 3,709,985 exact successful replies**, with zero bad
bodies or transport errors. Both modes passed connection churn, overload and owned-listener
cleanup checks. Source/client/wheel hashes, per-trial record hashes, resource observations
and all repeat ranges are included. Its exact runner is retained in
[`baseline-macos-v071-runner.py.txt`](baseline-macos-v071-runner.py.txt); the recorded
fingerprint and measurements are unchanged. Current `run.py` additionally fails closed
on denied process-group liveness probes. Historical records do not acquire that repair
retroactively: new comparisons still require matching recorded harness fingerprints.

The earlier pool-eight generation remains invalid: two GIL mixed trials did not execute
all required route cohorts. Its failures are retained in the summary, not replaced by
successful retries. A separate pool-sixteen generation reran the entire frozen matrix;
none of the prior ten valid rows were reused.

This is traffic-valid baseline data, **not evidence of repeatability or an optimization
win**. The latest FT nested p99 range is 770–788 microseconds, but the previous valid source
generation ranged from 662 to 3,086 microseconds. Both generations are retained; no timing
improvement is attributed to the harness repairs. Extend confirmation before
using a short screen to justify promotion. Resource sampling uses a requested 100ms loop
delay, not guaranteed 100ms observation spacing; actual sample counts/spans are retained.

## Fixed first screen

`plan.json` freezes 12 cells: ordinary GIL-enabled CPython and GIL-disabled free-threaded
CPython, three workloads, two reversed-order repeats, five seconds per cell. That is 60
seconds of timed native traffic, plus startup, correctness and cleanup checks. Both modes
use one process, sixteen client connections and four native client threads. The GIL pool
has sixteen workers; FT admission permits at most 32 active connections. Every persistent
client connection must fit in the GIL pool: otherwise queued route cohorts can be starved
for the whole closed-loop trial. The runner rejects that invalid screen configuration;
overload is tested separately with explicit smaller limits.

- `flat`: fresh, schema-validated small Struct responses.
- `nested`: fresh, schema-validated groups containing sixteen fresh Structs.
- `mixed`: four persistent connections per route, split across flat, nested, pure-Python
  arithmetic and a simulated 1ms blocking wait. Each native client thread has one fixed
  route, so its exact expected response bytes remain unambiguous. Connection shares are
  equal; request shares are not. This is not real database or outbound-network evidence.
- Separate untimed checks exercise eight connection open/request/close cycles and bounded
  overload shedding. Four incomplete request heads occupy four admission positions before
  a fifth connection must receive 503. Rejections are never counted as useful throughput.

Every timed response is checked for status 200 and exact route-specific bytes. Retain raw
native output, errors, after-import/after-load serving identity and sampled server/client
resources. Latencies are **wrk-adjusted closed-loop percentiles**, not fixed-offered-load
SLOs; client validation overhead and same-host contention can affect them. Sampled RSS,
thread/fd peaks and average CPU are not exact high-water measurements. The screen supports
POSIX/macOS/Linux monitoring; Windows is not a qualified measurement target.

## Record an installed-wheel baseline

Use CPython 3.14 and a genuine free-threaded 3.14 build. Installing a free-threaded executable
is not enough: the runner checks its build flag and actual worker GIL state. No GIL launch
overrides, source-path injection, editable installs or hidden parser acceleration are allowed.
Use an isolated host window; do not overlap builds or other owned tests with timing.

```sh
uv sync --all-extras --locked
uv venv --python 3.14 /absolute/evidence/gil
uv venv --python 3.14t /absolute/evidence/ft
# Obtain and retain the exact published wheel and registry digest separately.
uv pip install --python /absolute/evidence/gil/bin/python /absolute/evidence/dexpot-0.7.1-py3-none-any.whl
uv pip install --python /absolute/evidence/ft/bin/python /absolute/evidence/dexpot-0.7.1-py3-none-any.whl
uv run python benchmarks/regression/run.py record \
  --python-gil /absolute/evidence/gil/bin/python \
  --python-ft /absolute/evidence/ft/bin/python \
  --wheel /absolute/evidence/dexpot-0.7.1-py3-none-any.whl \
  --wrk /absolute/path/to/wrk \
  --output /absolute/evidence/baseline
```

Identify the actual native wrk executable and record its provenance before running. The
manifest hashes that executable, the wheel, workload, validator, controller, evaluator and
plan. Every installed Python module is checked against the supplied wheel. Dependencies,
interpreter versions, actual serving GIL state and parser selection are recorded. The
Python parser and one serving process are explicit controls, not best-deployment claims.

Every preflight and trial is bound to its own manifest fingerprints and observed serving
identity; resume and comparison reject detached rows or changed control limits. Candidate
versions and installation paths may legitimately differ from the baseline, but each must
match its own recorded artifact. Cleanup terminates and checks only the owned process
session/group, including descendants; forced cleanup is never a lifecycle pass. The
optional monitor is loaded only for recording, so parser/evaluator checks work without the
benchmark extra. Registry-digest verification is an explicit preparation step, not a claim
that the runner contacts PyPI automatically.

`baseline-recorded` means the complete matrix passed observed response/transport, runtime,
sampled-resource and lifecycle checks. It is **not** a candidate-performance verdict. A
failed cell stays failed. JSON rows use exclusive creation; a second invocation cannot
replace evidence. `--resume` verifies the immutable manifest, reuses completed rows and
runs only untouched cells. An interrupted `.started.json` without a result remains missing,
not silently retried. Resume reports are separately named; original reports remain intact.

## Screen a future candidate

Record a candidate in a separate directory with the same frozen plan, native client,
workload, evaluator, controller, interpreter/dependency versions and host configuration.
Both recordings must independently pass preflights and the whole matrix. The comparison
rejects identical wheel/source controls and mismatched environments.

```sh
uv run python benchmarks/regression/run.py compare \
  --baseline /absolute/evidence/baseline \
  --candidate /absolute/evidence/candidate \
  --output /absolute/evidence/comparison.json
```

Before collecting either side, the initial screen allows no more than 10% lower useful
throughput or 25% higher adjusted p99 in **each** matched cell; resource ceilings are frozen
in the same plan. These conservative diagnostic limits are not universal performance
promises. All required pairs must pass; losing pairs, transport failures and missing trials
cannot be discarded. Baseline/candidate recordings are not fully interleaved A/B trials:
reverse repeat order reduces some drift but does not establish statistical significance.
A failure needs investigation, and a pass still needs longer held-out scheduled-arrival,
real-service, resource-recovery and cross-platform qualification before runtime promotion.
No optimization is authorized or qualified merely by creating this baseline.

## Test the harness

`make check` includes benchmark Python lint/type checks, evaluator tests and a real HTTP
fixture check. Native validator checks run when wrk is available. An opt-in real installed
wheel/native CLI smoke can be enabled with `DEXPOT_SCREEN_TEST_PYTHON`,
`DEXPOT_SCREEN_TEST_WHEEL` and `DEXPOT_SCREEN_TEST_WRK` pointing at eligible artifacts.
That smoke records a separate one-cell/one-second fixture plan; it is not the twelve-cell
baseline. Unit records are synthetic test inputs, never measurement evidence.
