# LLVM 19 optimization investigation

Objective: work through all five areas below using actual Rust-generated IR,
NVIDIA PTX/SASS, resource reports and numerical checks. A smaller IR or PTX file
alone is not a runtime performance result. Existing defaults stay unchanged
until broader correctness and hardware measurements justify a change.

| Area | Experiment | Required evidence | Status |
| --- | --- | --- | --- |
| CFG ordering | Omit/reorder final SimplifyCFG; compare cleanup with neither CFG stage | Per-helper filtered/stepped SASS, registers, numerical oracle | Extended sweep implemented; validation in progress |
| Independent DCE | GlobalDCE alone and before/after scalar cleanup | Reachable exports/data retained; IR/PTX sizes, compile time, unchanged behavior | Extended sweep implemented; validation in progress |
| Computation/memory cleanup | EarlyCSE, GVN, memcpy optimization and DSE, separately and together | SHA-256 and a larger mining kernel; loads/stores, spills, numerical results | Reproducer/SHA sweep implemented; pinned Solana workload implemented; compilation pending |
| Inlining policy | Thresholds 0/50/450 plus a size-oriented build | Call sites, code size, registers, spills and correctness | Threshold sweep implemented; size-oriented builds implemented; validation pending |
| Per-module optimization | Verified opt-in LLVM 19 cleanup before serialization, compared with merged-only cleanup | Before/after per-module IR; final PTX/SASS and correctness; default-off and LLVM feature gates | Opt-in hook and replay checks implemented; Linux validation pending |

The previous stage is documented in `guarded-select.md` and
`evidence/cleanup-validated.json`. It removed two filtered-helper SASS selects
but increased that helper's non-NOP instruction count from 28 to 49. The old
combined-kernel totals masked how much of the growth belonged to that helper.

The workflow's `optimization_sweep` input enables the extended standalone
experiments. Exact pipelines and options live in `optimization_pipelines.py`
and are retained in each artifact. Results include LLVM-pass and total elapsed
seconds; CI machine load makes these illustrative compiler-cost observations,
not controlled benchmarks. The original five comparisons and both integrated
backend checks remain in the suite.

Completion requires evaluating every row, recording negative results as well
as improvements, retaining meaningful regression checks, and integrating only
changes justified by the evidence. NVIDIA runtime benchmarking remains distinct
from offline compilation and Apple-GPU consumer checks.

The per-module experiment uses `CudaBuilder::llvm19_module_cleanup(true)`
(`--llvm19-module-cleanup`) after each codegen unit's definitions, used globals
and debug information are finalized, before serialization and the legacy
optimization hook. It uses scalar cleanup only, preserving cross-module linkage.
It is independent of merged cleanup and disabled by default. Exporter modes
`module-scalar` and `module-inline` test it alone and with merged inline cleanup.
The extended workflow saves before/after IR for every rebuilt codegen unit and
checks each against standalone LLVM replay, including dependency modules.

Size modes `size-s` and `size-z` hold merged inline cleanup constant and change
Cargo's release opt-level. The `mining_workload` workflow input checks out
vanity-miner-rs at `9791234`, builds the full Solana mining kernel, and repeats
the independent DCE and memory-cleanup comparisons. Only cuda_std's dependency
location changes to the backend under test; original/resolved manifests and
locks are retained. This does not modify the user's vanity-miner checkout.

## First extended sweep

Run 34787085815 passes all 17 variants and the existing integrated checks.
`evidence/extended-sweep.json` records verified artifact hashes and per-helper
metrics. None of the tested CFG orderings, memory passes or inlining thresholds
improves the small filtered helper's instruction count over baseline (28).
SHA-256's non-NOP SASS count remains 1,623. Equal counts do not imply identical
code; some threshold variants alter output without improving these metrics.

GlobalDCE alone reduces the printed module from 13,107,292 to 257,877 bytes and
3,299 to 93 definitions while producing byte-identical PTX and SASS. In this
single CI observation, total replay/inspection time drops from 3.137 to 2.147
seconds. This supports a compiler-cost candidate, not a GPU speed claim.
Validation on the larger workload is still pending, as are the per-module and
size-oriented comparisons; the five-area objective is not complete.

The first per-module run compiled successfully but its textual comparison was
too strict about LLVM predecessor comments, local SSA names and PHI pair order.
The comparison now uses LLVM's `strip-nondebug` on comparison copies, ignores
comments outside strings and sorts complete PHI incoming pairs. Instructions,
attributes, constants and each value/block association remain compared. Negative
tests cover changed values and strings. All 22 saved module-scalar units from
run 34787242514 match standalone replay under this comparison; module-inline
and final workload checks still need the new CI run. Independent size/mining
checks now run after a successful baseline export even if another experiment
fails, while the overall workflow continues to report those failures.

Per-module scalar PTX from run 34787242514 passes vector-add and SHA-256 at
counts 1/31/32/33/257, plus all 1,608 guarded-select cases, on Apple M5 through
generic CuMetal lowering. `evidence/module-scalar-apple.json` records its hash
and consumer provenance. This adds numerical evidence while final per-module,
size-oriented and mining comparisons are still running; it is not a timing
result or NVIDIA execution proof.
