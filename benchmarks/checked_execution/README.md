# Checked-execution workload and recorded evidence

This fixture preserves the measured synchronous application operations, checked schemas,
exact expected responses, and native-client response validator used during the execution
experiments. `evidence.json` contains the final deadline-corrected source fingerprints and
all eight macOS/Ubuntu comparison records in compact form, including invalid-rate cells.
It does not contain the full private experiment archive or make a passing qualification claim.
See `../../docs/experimental-execution.md` for interpretation and unresolved gates.

## Run the native Dexpot fixture

Create a separate environment using the intended interpreter and install this checkout:

```bash
uv venv --python 3.14 .bench-gil
uv pip install --python .bench-gil/bin/python .
COMPARE_FRAMEWORK=dexpot COMPARE_CONTRACT=native COMPARE_WORKERS=4 \
  COMPARE_SYNC_THREADS=22 COMPARE_PORT=18881 \
  .bench-gil/bin/python benchmarks/checked_execution/app.py
```

For FT, create a different environment with `--python 3.14t`, use that environment's Python,
and set `COMPARE_WORKERS=1`. Verify `/runtime` reports the intended interpreter/GIL state,
package import path, native contract and scalar-strategy marker before measuring. Python
3.12 lacks the GIL-query API; the recorded campaign used CPython 3.14.7/3.14.7t.

In a second terminal, with a verified genuine wrk2 binary:

```bash
wrk2 -t4 -c16 -d25s -R10000 -L -U \
  -s benchmarks/checked_execution/check.lua http://127.0.0.1:18881/ -- mixed
```

The mixed request sequence is item/item/I/O/CPU: 50% checked flat responses, 25% identical
responses after `sleep(0.001)`, and 25% after `sum(i*i for i in range(500))`. The flat and
nested fixtures build values per request; there is no pre-encoded response cache. Other Lua
profiles are `originalflat`, `nested`, and `large_nested` (64 rows).

The optional FastAPI/Granian and Litestar adapters in `app.py` retain the original comparison
fixture; they require separate optional dependency environments. `COMPARE_CONTRACT=shared`
requires the historical compatibility fixture, which is not included here. This directory's
supported reproduction path is `COMPARE_CONTRACT=native`; do not relabel a shared/raw-byte
application contract as the framework's native checked path.

## Read results without manufacturing a pass

- Require `good == requests`, `bad == 0`, all four transport counters zero, all client threads
  calibrated, and the expected post-calibration histogram population.
- At fixed load, achieved rate must be within 5% of offered rate. A mismatched-rate cell is
  not a valid matched-load comparison even when every completed reply is correct.
- The recorded scheduled p99 budget was 20 ms. Keep it unchanged. Native `-U` output is a
  different actual-start distribution; it cannot replace a failed scheduled percentile.
- Record exact source/wheel/client/workload hashes, runtime identity, worker/process budgets,
  elapsed duration and all failures. Repeat pairs in the declared order rather than choosing
  the best result. The recorded order was predecessor/candidate/candidate/predecessor.
- `baseline` in the compact latest evidence means reviewed experimental predecessor
  `cc580b219bef31152b503dfe6078c2fb9adb7b90879b52d45e2c1c180e3ddb25`, not released Dexpot.
  Earlier release/competitor results are a separate source generation.
- Run server and client serially relative to other benchmark campaigns. Docker Desktop is
  Linux-path screening, not bare-metal or separate-host qualification.

Client provenance matters: upstream wrk2 can print a wrk version banner; require a real
`-R` invocation and scheduled timing implementation. The original native ARM builds needed
LuaJIT/toolchain compatibility fixes, including preserving `getopt_long`'s signed `int`
return on Linux ARM. Never reuse a Mach-O binary in an Ubuntu container or silently change
the request/timing/histogram algorithm to improve results.
