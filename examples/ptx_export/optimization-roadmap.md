# LLVM 19 optimization investigation

Objective: work through all five areas below using actual Rust-generated IR,
NVIDIA PTX/SASS, resource reports and numerical checks. A smaller IR or PTX file
alone is not a runtime performance result. Existing defaults stay unchanged
until broader correctness and hardware measurements justify a change.

| Area | Experiment | Required evidence | Status |
| --- | --- | --- | --- |
| CFG ordering | Omit/reorder final SimplifyCFG; compare cleanup with neither CFG stage | Per-helper filtered/stepped SASS, registers, numerical oracle | Extended sweep implemented; validation in progress |
| Independent DCE | GlobalDCE alone and before/after scalar cleanup | Reachable exports/data retained; IR/PTX sizes, compile time, unchanged behavior | Extended sweep implemented; validation in progress |
| Computation/memory cleanup | EarlyCSE, GVN, memcpy optimization and DSE, separately and together | SHA-256 and a larger mining kernel; loads/stores, spills, numerical results | Reproducer/SHA sweep implemented; mining workload pending |
| Inlining policy | Thresholds 0/50/450 plus a size-oriented build | Call sites, code size, registers, spills and correctness | Threshold sweep implemented; size-oriented build pending |
| Per-module optimization | Verified opt-in LLVM 19 cleanup before serialization, compared with merged-only cleanup | Before/after per-module IR; final PTX/SASS and correctness; default-off and LLVM feature gates | Pending implementation and evaluation |

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
