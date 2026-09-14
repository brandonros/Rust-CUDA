# LLVM 19 optimization investigation

Wave 1 completed: the full [validation matrix](https://github.com/brandonros/Rust-CUDA/actions/runs/34789945556) passes.

Wave 2 is tracked in [optimization-wave2.md](optimization-wave2.md). It promotes
GlobalDCE with explicit disable and retention tests, while keeping instruction-transforming cleanup opt-in pending broader evidence.

The evaluated outcomes are consolidated in [optimization-results.md](optimization-results.md).
The chronological notes below retain the intermediate failures and their fixes.

Objective: work through all five areas below using actual Rust-generated IR,
NVIDIA PTX/SASS, resource reports and numerical checks. A smaller IR or PTX file
alone is not a runtime performance result. Existing defaults stay unchanged
until broader correctness and hardware measurements justify a change.

| Area | Experiment | Required evidence | Status |
| --- | --- | --- | --- |
| CFG ordering | Omit/reorder final SimplifyCFG; compare cleanup with neither CFG stage | Per-helper filtered/stepped SASS, registers, numerical oracle | Evaluated: no improvement over baseline helper instruction count |
| Independent DCE | GlobalDCE alone and before/after scalar cleanup | Reachable exports/data retained; IR/PTX sizes, compile time, unchanged behavior | Evaluated on both workloads; independent opt-in DCE integrated |
| Computation/memory cleanup | EarlyCSE, GVN, memcpy optimization and DSE, separately and together | SHA-256 and a larger mining kernel; loads/stores, spills, numerical results | Evaluated on SHA and full Solana; no gain beyond inlining/scalar cleanup |
| Inlining policy | Thresholds 0/50/450 plus a size-oriented build | Call sites, code size, registers, spills and correctness | Evaluated thresholds and both size modes; simpler inlining mode integrated |
| Per-module optimization | Verified opt-in LLVM 19 cleanup before serialization, compared with merged-only cleanup | Before/after per-module IR; final PTX/SASS and correctness; default-off and LLVM feature gates | Both modes verified across 22 CGUs; no measured static advantage on the small suite |

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

## Larger workload and per-module evidence

Run 34787847715 passes both per-module modes (22 codegen units each) and the
Solana DCE/memory sweep. Its overall failure is the independent size-s build:
the libdevice override lookup calls `item_name` on an unnamed libm closure.
Commit cf5965a replaces that lookup with `opt_item_name`; both size modes must
compile before that investigation can be considered validated.

`evidence/solana-first-sweep.json` records the first full mining comparison,
including per-symbol instruction histograms, resource reports and hashes.
GlobalDCE alone reduces LLVM definitions from 3,883 to 151 and printed IR from
15,716,570 to 1,341,603 bytes, with byte-identical PTX and SASS. This reinforces
the compiler-cost result from the smaller suite. An independent opt-in builder
mode `Llvm19Cleanup::GlobalDce` now has integrated replay and oracle checks in CI.

The memory pipelines reduce registers from 216 to 178 and PTX from 1,481,081
to 1,301,076 bytes. All include inlining and scalar cleanup, so these gains
cannot yet be attributed to memory passes: the next run adds `inline-only`.
No NVIDIA runtime performance or numerical claim follows from these static
metrics. Current CuMetal rejects both baseline and memory-stores before launch
with the same restriction: trap reporting requires a call-free kernel without
barriers or collectives. That consumer limitation remains separate from the
optimization experiment; no trap semantics were bypassed.

The offline inlining-only ablation from run 34788545905 gives 38,428 non-NOP
Solana SASS instructions and 178 registers, versus baseline 39,738 and 216.
EarlyCSE and GVN add no instruction/register improvement; store cleanup adds
two instructions, with the same registers and load/store counts. All variants
retain a 208-byte kernel stack and a helper with 32-byte spill loads/stores.
This supports testing the simpler `InlineScalar` builder mode rather than
adding the memory passes. Integrated replay checks now cover that mode on
both the small suite and the full Solana kernel.

That run restored an old backend because cuda_builder finds an existing shared
library before asking Cargo to rebuild it. The offline ablation remains valid
for its recorded input, but this run does not validate cf5965a's backend fix.
The workflow now explicitly builds the checked-out backend, records its hash,
and removes only cached device outputs before generating fresh IR evidence.
The same cache reuse also explains the missing per-module dependency dumps.

`evidence/inline-scalar-apple.json` records generic M5 execution of the hashed
offline inline-scalar PTX: vector-add and SHA-256 at five boundary counts and
1,608 guarded-select oracle cases, with guards intact. This supplies numerical
evidence for the small suite, not for the full mining kernel.
