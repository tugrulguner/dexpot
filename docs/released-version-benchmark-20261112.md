# Published Dexpot 0.9.0 versus 0.8.1: bounded macOS screen

## Decision

The initial five-second screen failed three free-threaded comparison cells. A separate, alternating-order twenty-second confirmation passed all seven declared pairs. The initial failures remain failures; the confirmation did not consistently reproduce them. Both versions show tail-latency variation, so these observations establish neither a repeatable overall speedup nor a reliably attributed release regression. No runtime optimization is proposed from this screen.

This compares actual PyPI packages, not experimental branches. It is a same-host diagnostic, not a framework ranking, Linux result, production capacity claim or scheduled-arrival latency qualification.

## Configuration and provenance

Recorded on 2026-11-12: macOS 26.5.2, Apple M4 (ARM64 Mac16,10), 10 logical CPUs and 24 GiB RAM. Both ordinary and genuine unforced free-threaded CPython 3.14.7 use msgspec 0.22.0. Each server uses one process, the Python request-head parser, sixteen persistent client connections and four native wrk 4.2.0 threads. GIL pool: 16; queue: 16; FT connection limit: 32. Serving-time identity and installed wheel-member bytes are verified in every recording. No optional parser accelerator was installed.

Workloads return fresh schema-validated JSON: a small item, a nested group of sixteen items, and a mixed cohort of item/nested/CPU/simulated1ms blocking-wait routes. Mixed connection shares are equal; request shares are not. This is not database or real outbound-service evidence.

All reported latencies are wrk-adjusted closed-loop percentiles. The tables show per-trial ranges, not pooled percentiles; throughput is the median of per-trial correct responses/second. Client validation overhead and uncontrolled background host activity are included. AC Low Power Mode stayed enabled; no power/QoS settings were changed.

The original frozen screen permits at most 10% lower goodput and 25% higher adjusted p99 in every matched cell, plus unchanged resource/identity/cleanup limits. Those diagnostic limits are retained unchanged. Goodput counts correct successful responses; p99 describes the slow-request tail, with the client-adjustment caveat above.

Published wheel SHA-256:

- 0.8.1: `23efe01a3b6d8ec912247f8e7a6692bc4f0f6c3f35518beca66c7d65452595f6`; https://pypi.org/project/dexpot/0.8.1/
- 0.9.0: `671ef73acb70e17eb329fa23d5999401ecef7276f1f3e04522014c6456aaede7`; https://pypi.org/project/dexpot/0.9.0/

## Results

### Initial five-second screen

| Version | Runtime | Workload | Trials | Correct replies/s, median | p50 range, ms | p95 range, ms | p99 range, ms |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 0.8.1 | gil | flat | 2 | 21,452 | 0.696–0.699 | 1.634–1.657 | 2.181–2.267 |
| 0.8.1 | gil | nested | 2 | 17,628 | 0.847–0.855 | 1.962–1.969 | 2.641–2.658 |
| 0.8.1 | gil | mixed | 2 | 18,162 | 0.736–0.738 | 4.679–4.725 | 6.176–6.198 |
| 0.8.1 | ft | flat | 2 | 115,623 | 0.110–0.110 | 0.285–0.447 | 0.491–2.716 |
| 0.8.1 | ft | nested | 2 | 91,174 | 0.134–0.153 | 0.309–0.383 | 0.566–1.067 |
| 0.8.1 | ft | mixed | 2 | 93,177 | 0.119–0.121 | 1.069–1.081 | 1.286–1.330 |
| 0.9.0 | gil | flat | 2 | 21,512 | 0.694–0.699 | 1.613–1.634 | 2.156–2.199 |
| 0.9.0 | gil | nested | 2 | 17,454 | 0.855–0.864 | 1.978–2.003 | 2.679–2.684 |
| 0.9.0 | gil | mixed | 2 | 17,106 | 0.752–0.814 | 4.663–4.703 | 6.204–6.269 |
| 0.9.0 | ft | flat | 2 | 107,773 | 0.111–0.121 | 0.303–0.661 | 0.554–4.088 |
| 0.9.0 | ft | nested | 2 | 87,174 | 0.138–0.162 | 0.328–0.545 | 0.610–3.158 |
| 0.9.0 | ft | mixed | 2 | 92,865 | 0.116–0.123 | 1.067–1.104 | 1.267–1.840 |

Per-pair comparison:

- `gil-flat-0`: goodput ratio 1.0028; adjusted-p99 ratio 0.9885; pass.
- `ft-flat-0`: goodput ratio 0.8442; adjusted-p99 ratio 8.3259; **FAIL**.
- `gil-nested-0`: goodput ratio 0.9882; adjusted-p99 ratio 1.0163; pass.
- `ft-nested-0`: goodput ratio 0.9835; adjusted-p99 ratio 1.0777; pass.
- `gil-mixed-0`: goodput ratio 0.9023; adjusted-p99 ratio 1.0151; pass.
- `ft-mixed-0`: goodput ratio 1.0419; adjusted-p99 ratio 0.9526; pass.
- `ft-mixed-1`: goodput ratio 0.9511; adjusted-p99 ratio 1.4308; **FAIL**.
- `gil-mixed-1`: goodput ratio 0.9816; adjusted-p99 ratio 1.0010; pass.
- `ft-nested-1`: goodput ratio 0.9248; adjusted-p99 ratio 2.9597; **FAIL**.
- `gil-nested-1`: goodput ratio 0.9920; adjusted-p99 ratio 1.0079; pass.
- `ft-flat-1`: goodput ratio 1.0241; adjusted-p99 ratio 0.2040; pass.
- `gil-flat-1`: goodput ratio 1.0028; adjusted-p99 ratio 0.9700; pass.

### Held-out twenty-second confirmation

| Version | Runtime | Workload | Trials | Correct replies/s, median | p50 range, ms | p95 range, ms | p99 range, ms |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 0.8.1 | gil | flat | 1 | 21,716 | 0.691–0.691 | 1.606–1.606 | 2.140–2.140 |
| 0.8.1 | ft | flat | 2 | 115,776 | 0.110–0.111 | 0.284–0.344 | 0.483–0.765 |
| 0.8.1 | ft | nested | 2 | 91,064 | 0.138–0.145 | 0.317–0.572 | 0.582–19.200 |
| 0.8.1 | ft | mixed | 2 | 99,564 | 0.113–0.114 | 1.058–1.058 | 1.254–1.254 |
| 0.9.0 | gil | flat | 1 | 21,453 | 0.699–0.699 | 1.643–1.643 | 2.233–2.233 |
| 0.9.0 | ft | flat | 2 | 116,080 | 0.110–0.111 | 0.295–0.324 | 0.526–0.619 |
| 0.9.0 | ft | nested | 2 | 94,366 | 0.137–0.141 | 0.323–0.350 | 0.584–0.714 |
| 0.9.0 | ft | mixed | 2 | 99,139 | 0.113–0.114 | 1.057–1.057 | 1.252–1.254 |

Per-pair comparison:

- `ft-flat-0`: goodput ratio 1.0107; adjusted-p99 ratio 0.8092; pass.
- `ft-nested-0`: goodput ratio 1.0808; adjusted-p99 ratio 0.0372; pass.
- `ft-mixed-0`: goodput ratio 0.9991; adjusted-p99 ratio 0.9984; pass.
- `ft-flat-1`: goodput ratio 0.9947; adjusted-p99 ratio 1.0890; pass.
- `ft-nested-1`: goodput ratio 0.9961; adjusted-p99 ratio 1.0034; pass.
- `ft-mixed-1`: goodput ratio 0.9924; adjusted-p99 ratio 1.0000; pass.
- `gil-flat-0`: goodput ratio 0.9879; adjusted-p99 ratio 1.0435; pass.

## Interpretation and retained limits

- Ordinary Python passed all initial cells, but its first mixed pair was near the throughput-loss limit. The single longer ordinary-Python flat control is not confirmation of every GIL workload.
- The longer free-threaded flat and mixed pairs are close in throughput. Nested throughput gains are inconsistent between pairs; do not headline an overall speedup.
- The older package had a 19.2 ms nested adjusted-p99 outlier in one confirmation trial versus 0.582 ms in its other repeat. This variability prevents treating the large favorable ratio as a stable improvement.
- No same-source calibration campaign, offered-rate latency study, separate-host client run, production soak, competitor comparison or cross-platform performance qualification is established.
- Release-added typed source binding and OpenAPI functionality are not exercised by this shared older-compatible response workload.

## Traffic, resources and cleanup

38 distinct completed trials; 32,783,239 exact successful replies; zero bad bodies or transport errors in both cohorts. Every owned server process group exited normally and its listener closed. Timed traffic totals400seconds; setup/preflight time is additional.

The companion JSON retains sampled CPU/RSS/thread/fd ranges, per-trial counters, latency metrics, artifact/input hashes and raw-record digests. Sampling is observational, not a proof of exact peaks. Raw native output/manifests and the frozen alternating-order driver are retained outside Git under `~/Projects/dexpot-performance/released-090-vs081-20261112/`. The initial and confirmation generations are separate and immutable.

## Reproduce

Use the existing `benchmarks/regression/run.py record` commands in the regression README with separately downloaded, registry-hash-verified0.8.1 and0.9.0 wheels and matched isolated GIL/FT environments. Run the full default plan for each version into distinct directories, then invoke `run.py compare`. Do not replace a failed cell with a retry.

The confirmation uses a separate plan with20-second duration, each FT workload twice and one GIL-flat pair. It calls the unchanged runner trial/evaluator functions with alternating version order per pair. Its exact plan, driver digest and recorded commands are retained with that generation; do not relabel the default version-grouped recording as interleaved.

See [the companion evidence](released-version-benchmark-20261112.json) and [the regression screen contract](../benchmarks/regression/README.md).
