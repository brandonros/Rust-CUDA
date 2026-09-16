# LLVM optimization results

The five-area investigation found two useful opt-in additions: standalone
GlobalDCE reduces the IR handed to NVVM, and inlining plus scalar cleanup
improves static Solana code metrics. Extra memory passes, tested CFG reorderings,
and size-oriented profiles did not justify a general default change.

This is an LLVM 19 / CUDA 13.2 / `compute_100` investigation. It does not compare
LLVM 7 or LLVM 21. NVIDIA results are compilation/disassembly measurements;
NVIDIA runtime performance remains unmeasured.

The complete [Linux matrix passed](https://github.com/brandonros/Rust-CUDA/actions/runs/34789945556)
on source `11f26a4`. [Machine-readable results](evidence/optimization-final.json)
include all 17 small-suite variants, eight Solana variants, four integrated
merged modes, both per-module modes and both size profiles, with hashes,
per-symbol counts, resource reports and host-oracle results. The final artifacts
are byte-identical to the PTX used for the linked Apple GPU checks.

## Decisions

| Area | Result | Implementation decision |
| --- | --- | --- |
| CFG cleanup ordering | Tested reordered/omitted SimplifyCFG stages. None beats the small filtered helper's 28 baseline non-NOP instructions. Correlated propagation removes two selects but grows that helper to 49 instructions. | Keep correlated cleanup experimental; no more CFG passes added. |
| Independent GlobalDCE | Small module: 3,299 → 93 definitions. Solana: 3,883 → 151. PTX and SASS remain byte-identical to their respective baselines. | Add verified `LlvmCleanup::GlobalDce`, independent of scalar cleanup/inlining. |
| Computation/memory cleanup | EarlyCSE and GVN add no improvement beyond inlining on SHA-256 or Solana. Store cleanup does not reduce registers or load/store sites and adds two Solana instructions. | Retain the experiments; do not add these passes to the integrated pipelines. |
| Inlining/size policy | Inlining plus scalar cleanup improves Solana metrics. Thresholds 0/50/450 do not improve the small helper's count. Size profiles produce mixed results and increase SHA-256 stack usage. | Add `LlvmCleanup::InlineScalar`; retain explicit size experiments. No universal threshold/preset change. |
| Per-module cleanup | Both modes verify and match independent replay across 22 codegen units, including dependencies. No SHA-256 instruction improvement; the filtered/stepped entry grows. | Add verified `.llvm_module_cleanup(true)` for further workload experiments, disabled by default. |

## Larger workload

The actual Solana mining source is pinned to vanity-miner-rs `9791234`.
Only its cuda_std dependency is redirected to the backend being tested;
algorithm source is unchanged. Full source/manifest/lock provenance is in CI.

| Pipeline | PTX bytes | Cubin bytes | Non-NOP SASS instructions | Registers |
| --- | ---: | ---: | ---: | ---: |
| Baseline | 1,481,081 | 739,480 | 39,738 | 216 |
| GlobalDCE only | 1,481,081 | 739,480 | 39,738 | 216 |
| Inlining + scalar cleanup | 1,301,076 | 716,024 | 38,428 | 178 |
| Plus correlated propagation | 1,300,592 | 715,912 | 38,436 | 180 |
| Plus EarlyCSE or GVN | 1,301,076 | 716,024 | 38,428 | 178 |
| Plus memcpy/DSE cleanup | 1,301,076 | 715,800 | 38,430 | 178 |

The inlining-only ablation is essential: the memory pipelines include inlining
and scalar cleanup, which account for their improvement over baseline.
Additional correlated propagation also loses to the simpler pipeline here.

Kernel stack usage remains 208 bytes. The same RNG helper retains 32 bytes
of spill stores and loads; the kernel entry reports zero spill bytes. Static
load sites remain 288, while store sites change from 433 to 436 after inlining.
These counts include helper code and are not dynamic memory traffic or timings.

GlobalDCE shrinks Solana's printed LLVM module from 15,716,570 to 1,341,603 bytes.
Single-run compiler timings are retained as observations, not controlled
benchmarks. Byte-identical PTX/SASS means DCE's measured benefit is upstream
compiler work, not a different GPU program.

## Size-oriented builds

These build the same Rust source with Cargo opt-level `s` or `z`, holding the
merged `Inline` cleanup pipeline constant. They are not a new CPU-style LLVM
optimization preset installed in the backend.

| Profile | Whole-module PTX bytes | Whole-module cubin bytes | SHA-256 non-NOP instructions | SHA-256 registers | SHA-256 stack bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Release level 3 + Inline | 106,091 | 58,376 | 1,623 | 40 | 112 |
| Size `s` + Inline | 96,349 | 66,928 | 2,009 | 40 | 320 |
| Size `z` + Inline | 94,320 | 60,008 | 1,920 | 39 | 320 |

The guarded-select entry gets smaller (614 → 405 → 127 static instructions),
but the filtered/stepped entry does not (124 → 130 → 128). Changing loop
structure affects static counts; this does not establish runtime speed.
A smaller PTX file is insufficient justification for a global size preset.

## Correctness and reproducibility

The workflow verifies LLVM IR, assembles PTX with ptxas, records disassembly,
resources, versions, flags and hashes, and compares integrated output against
independent `opt`/NVVM replay. The five extracted integer helpers have an
independent 1,608-case host oracle, including the observable-false-path control.
Extraction preserves referenced globals and target-independent intrinsics;
it does not erase trap paths or substitute dummy data.

Generic CuMetal execution on Apple M5 passes vector addition and SHA-256 at
counts 1/31/32/33/257, plus 1,608 guarded-select cases, for the inlining/scalar
and both size configurations. Guards remain intact. Evidence is recorded in
`evidence/inline-scalar-apple.json`, `evidence/size-s-apple.json`, and
`evidence/size-z-apple.json`; per-module scalar evidence is recorded separately.
These are tests of the hashed PTX through another consumer, not NVIDIA execution.

Full Solana numerical execution remains unvalidated: the current CuMetal
consumer rejects both baseline and optimized PTX before launch because its trap
reporting requires a call-free kernel without barriers or collectives. The
filtered/stepped GPU entry also remains outside the successful GPU checks.
Neither limitation was bypassed to obtain a pass.

Two infrastructure fixes were required: the libdevice override lookup now skips
unnamed libm closures instead of crashing at size optimization, and CI explicitly
rebuilds the checked-out backend instead of trusting a restored shared library.
Device outputs are regenerated so all per-module IR is present. The expensive
host/backend dependency cache is retained.

## Using the measured options

```rust
// Reduce unused IR before NVVM; no scalar rewriting or inlining.
builder.llvm_cleanup(LlvmCleanup::GlobalDce)

// The simpler inlining pipeline favored by the Solana measurements.
builder.llvm_cleanup(LlvmCleanup::InlineScalar)
```

Both require the modern LLVM backend and remain opt-in. The exporter accepts `dce`
and `inline-scalar` after its output directory. When changing backend source,
explicitly rebuild it as the workflow does; a cached backend library alone is
not proof that the current source is being used. See the [exporter guide](README.md).
