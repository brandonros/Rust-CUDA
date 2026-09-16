# LLVM optimization: broader validation

Status: all seven workloads pass in [the final matrix](https://github.com/brandonros/Rust-CUDA/actions/runs/34794484421),
including the 119-entry self-test/probe module. Native NVIDIA measurements
remain unavailable. This report separates offline, host and Apple-GPU evidence.

GlobalDCE is now enabled by default at the merged LLVM 19 handoff. Scalar,
inlining, per-module and loop transformations remain opt-in. LLVM 7 retains
its existing pipeline. `CudaBuilder::llvm_global_dce(false)` explicitly
disables the new default; explicit cleanup modes may themselves include DCE.
The exporter now defaults to `default`; use `none` for the unpruned control.

## Default-DCE evidence

[Run 34792081740](https://github.com/brandonros/Rust-CUDA/actions/runs/34792081740)
passes the production builder/standalone replay checks and retention regression.
The small suite shrinks from 3,299 to 93 LLVM definitions; the retention fixture
shrinks from 3,192 to five. Both produce identical PTX with DCE disabled/enabled.
The fixture retains kernel entries, explicitly externally visible functions,
function-pointer tables, referenced initialized data, and both `llvm.used` and
`llvm.compiler.used`; deliberately unreachable function/data controls disappear.
The small-suite host oracle also passes. These are compiler pruning results,
not evidence of faster GPU execution.

## Four full mining workloads

[Run 34792081315](https://github.com/brandonros/Rust-CUDA/actions/runs/34792081315)
uses miner commit `9791234249fc8cb762c296c4fda4503d2686ff77` and backend commit
`6cefd7d3f92a71a3e19f5363441c5a7fbd2e7f62`. Every mining build passes LLVM
verification, NVVM compilation, `ptxas` and disassembly. Production InlineScalar
matches independent LLVM replay. Default DCE produces byte-identical PTX and
cubins for all four workloads.

| Workload | SASS instructions: disabled → InlineScalar | Registers | Cumulative stack bytes |
| --- | ---: | ---: | ---: |
| Solana | 39,738 → 38,428 | 216 → 178 | 208 → 208 |
| Bitcoin | 90,877 → 96,968 | 255 → 255 | 11,120 → 11,024 |
| Ethereum | 87,009 → 86,774 | 255 → 255 | 10,928 → 3,984 |
| Shallenge | 2,380 → 2,710 | 96 → 96 | 144 → 176 |

Instruction counts are static non-NOP counts over each entry's disassembly
extent, including its helpers. They are not dynamic executed instructions.
Do not add helper counts to those totals. Register and stack figures are
assembler reports, not measured occupancy or bandwidth.

These mixed results reject promotion of InlineScalar as a general default.
Ethereum's stack reduction is worth a hardware measurement, while Bitcoin and
Shallenge demonstrate why PTX size alone is insufficient.

## Final matrix and self-test module

The final matrix uses backend commit `d111f80dbfa2374fb50af5b6d49407ffab13bd1a`.
All seven workloads pass baseline, default-DCE and InlineScalar compilation,
LLVM/NVVM verification, NVIDIA assembly/disassembly and independent replay.
Default DCE produces identical PTX and cubins to the disabled control in every
workload. The evidence ledger records the final artifacts separately from the
earlier experiments; all 378 files listed in the 21 inspection manifests were
checked against their SHA-256 hashes after download.

The large module contains 118 numerical self-test entry points and one plumbing
probe. These are 119 compiled entries, not 119 executed numerical tests.

| Mode | LLVM definitions | LLVM IR bytes | PTX bytes | Cubin bytes |
| --- | ---: | ---: | ---: | ---: |
| Disabled | 6,166 | 26,340,781 | 21,849,956 | 24,220,008 |
| Default DCE | 605 | 4,560,285 | 21,849,956 | 24,220,008 |
| InlineScalar | 159 | 4,946,377 | 39,891,407 | 23,053,904 |

Inlining grows this module's PTX while shrinking its cubin. Neither file size
establishes a runtime improvement; the mixed mining results still argue for
keeping it opt-in.

Subsequent changes fix lint diagnostics and keep the exporter's explicit `none`
control usable on LLVM 7. [Linux CI on that code](https://github.com/brandonros/Rust-CUDA/actions/runs/34795701436)
passes all six Ubuntu/Rocky, x86/ARM, CUDA 12/13 jobs and compile tests.
[Export/retention checks](https://github.com/brandonros/Rust-CUDA/actions/runs/34795912080)
also pass. Windows validation remains pending: an earlier job failed downloading
prebuilt LLVM 7 with an SSL connection reset, and subsequent runs are still
in progress. This does not establish Windows compatibility or a compiler failure.

## Inlining and local memory

The recorded LLVM inlining remarks identify `Xoroshiro128StarStar::from_seed`
as recursive, with an uninlinable cost rather than a threshold miss. Its
zero-seed fallback recurses. Increasing the generic threshold does not address
that reason. Its 79-instruction SASS helper retains a 56-byte stack frame and
32-byte spill stores/loads under all three tested loop/inlining configurations.

The bounded `tiny-loops` pipeline runs loop canonicalization, induction-variable
simplification, full unrolling capped at four trips, and scalar cleanup. Runtime
unrolling, partial unrolling and peeling are disabled. It reduces the RNG
helper's intermediate allocations from five to four without changing its SASS.
Standalone function-attribute/tail-call elimination and a second inlining pass
also leave its recursive call and five allocations intact. A further native LLVM experiment with IPSCCP retains the same five allocations.
Argument promotion plus another inlining pass retains the pointer-based recursive
helper and four allocations while expanding the module to 2.24 MB; it is not
advanced to NVIDIA measurement. No recursion or undefined-register semantics
were changed to obtain a smaller result.

| Solana experiment | SASS instructions | Registers | Cumulative stack bytes |
| --- | ---: | ---: | ---: |
| InlineScalar | 38,428 | 178 | 208 |
| InlineScalar + tiny loops | 36,480 | 200 | 192 |
| InlineScalar + correlated cleanup + tiny loops | 35,971 | 179 | 192 |

The last variant is a promising static candidate, not a new default. Its full
mining numerical behavior and speed have not been measured on NVIDIA hardware.
Both loop variants pass the five-helper 1,608-case host oracle and vector-add/
SHA-256 tests at counts 1, 31, 32, 33 and 257 on Apple M5 through generic CuMetal.
Those checks cover the small suite, not the complete Solana kernel.

SHA-256 remains at 1,623 SASS instructions, 40 registers and 112 stack bytes
under both bounded loop variants. Its PTX contains an actual 112-byte local
buffer with hash-state and input/padding stores; the assembler reports zero
spills. Treating that storage as a register-allocation spill would misdiagnose
it. The separate loop-idiom/memcpy/SROA experiment in run 34793033638 reduces
intermediate allocations but leaves the SHA machine code and stack unchanged.
It adds two Solana SASS instructions with unchanged registers and spills; it
is not selected for integration.

## Representative operations and hardware validation

The representative crate adds runtime-input floating-point, shared-memory,
atomic and warp-shuffle probes. Run 34793214204 isolates the pre-existing NVVM
crash to shuffle: the other three operations compile under all builder modes,
then pass six input sizes each on Apple M5 (54 checks), including guards.
Per-entry extraction retains referenced global initializers and runs NVVM in
child processes so one crash cannot hide remaining results. No new verifier exception was introduced. These are extracted modules, not a passing full-module compilation.

The LLVM 19 intrinsic library now uses the modern IDX/UP/DOWN/BFLY forms while
LLVM 7 keeps the legacy wrapper. This follows the [CUDA 13.2 NVVM specification](https://docs.nvidia.com/cuda/archive/13.2.0/nvvm-ir-spec/index.html#data-movement).
Both retain the packed i64 Rust-facing value/predicate ABI. The expanded
regression covers all four directions. Reviewing that probe also exposed an
incorrect UP clamp (31 instead of 0) and an invalid power-of-two assertion in
cuda_std. The shared control helper fixes both, with tests applying the PTX
bound calculation independently across all lanes and supported widths, plus
invalid-width rejection. [Run 34793862065](https://github.com/brandonros/Rust-CUDA/actions/runs/34793862065)
passes the complete four-entry module in all three builder modes, including
LLVM/NVVM verification, assembly, disassembly and independent replay.

The full-module float/shared/atomic entries pass all 54 numerical checks on M5.
The shuffle predicate check fails in every mode: at count 32, output[0] is
`0xffffffff` instead of `0x28b7bc80`. The generated MSL declares four predicate
variables (`v16`, `v18`, `v20`, `v22`) and reads them in output selects without
ever assigning them. The PTX defines all four predicates through `shfl.sync`.
This is a separate CuMetal lowering blocker; its generic/exact provenance label
is not sufficient evidence of correctness. No generated MSL or expected answer
was modified to turn this into a pass.

[The unchanged four-entry PTX fixture](evidence/representative-shuffle.ptx) and
the commands/logs/hashes in [the evidence ledger](evidence/optimization-wave2.json)
provide the handoff. For the current CuMetal build, compile with
`--backend=cumetal-ir --ptx-strict --entry wave2_shuffle --emit=msl`, then use
`run_wave2_gpu.py --kernel wave2_shuffle --counts 32` with the explicit driver.
NVIDIA numerical validation of the corrected shuffle remains outstanding.

`run_wave2_gpu.py` provides independent expected results and guard checks for
these probes, with optional CUDA-event timing on a native NVIDIA driver. It
records module/runner hashes, driver version, device and per-count results.
Timing excludes initialization, compilation, allocation and copies; small
kernels can still be dominated by launch overhead. Compatible drivers are
numerical-only. The compatible-driver numerical path is exercised; native NVIDIA timing remains
unvalidated: this Mac
has an Apple M5 and both forks currently have zero self-hosted runners.

The workflow supports selecting a single workload for repeat investigations:

```sh
gh workflow run optimization_wave2.yml --repo brandonros/Rust-CUDA \
  --ref poc/portable-ptx-export -f workload=representative
```

Raw CI artifacts include original/resolved workload locks, compiler/backend
provenance, exact commands, before/after IR, PTX, cubins, disassembly, assembler
resource reports and inlining/loop remarks. Compilation success is kept
separate from numerical validation and runtime performance.

## Inspection reuse

The final matrix avoids repeating assembly/disassembly only when PTX bytes,
inspector source hash, tool executable hashes and all three version outputs
match. Every reused result names its source, original commands and copied-file
hashes in `reused-inspection.json`; fresh LLVM/NVVM compilation still runs.
Changed-input tests reject reuse. This reduces redundant CI work, not GPU
execution time. Self-test jobs have a 90-minute ceiling; other jobs retain 45.
