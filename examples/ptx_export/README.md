# Export PTX without a GPU host application

This example compiles four Rust kernels to PTX without linking a CUDA host
application or launching an NVIDIA GPU. Compilation still requires the normal
Rust-CUDA Linux toolchain, CUDA toolkit, and NVVM libraries.

```sh
nix develop .#v21 --command cargo run -p ptx_export --features llvm21 -- artifacts/ptx
```

Cargo builds the backend dependency with the exporter's `llvm21` feature.
`backend-path.txt` records the exact backend used. For LLVM 7, omit the feature
and use the matching toolchain shell.

The exporter uses `CudaBuilder`'s feature-dependent target default: `compute_100`
with `llvm21`, or `compute_75` without it. This keeps the target compatible with
the selected NVVM IR dialect; overriding it to `compute_89` on the modern LLVM path
selects NVVM's legacy reader and fails to parse the generated bitcode.

The output `rust_kernels.ptx` contains:

- `rust_vecadd(a: pointer, b: pointer, out: pointer, count: u32)`
- `rust_sha256_32(input: pointer, out: pointer, count: u32)`
- `rust_filtered_select(table: pointer, limits: pointer, out: pointer, count: u32)`
- `rust_guarded_select(table: pointer, limits: pointer, initials: pointer, out: pointer, count: u32)`

Pointers are 64-bit PTX addresses. Each SHA-256 work item reads exactly 32 bytes
and writes the corresponding 32-byte digest. All kernels bounds-check the
thread index so callers can round their dispatch size up. Inputs and outputs
must not overlap. These explicit pointer/count interfaces avoid requiring a
consumer to infer Rust slice or aggregate layouts.

Keep the generated PTX unchanged when testing another PTX consumer. Successful
export alone does not establish compatibility or numerical GPU correctness.

The guarded-select experiment has a separate [test guide](guarded-select.md).

This branch builds on `experiment/cuda13.3-llvm21` and uses the `llvm21` feature
and `v21` shell. The linked experiment reports and checked-in result files record
**historical LLVM 19 measurements**, not LLVM 21 validation. Re-run the workflows
to establish results for this stack. The experimental `LlvmCleanup` and
`llvm_*` builder/option names are version-independent and control the modern
LLVM backend.

## Experimental modern LLVM cleanup

The exporter accepts `default` (the default), `none`, `dce`, `scalar`, `inline-scalar`, or `inline` after the output
directory. For example:

```sh
nix develop .#v21 --command cargo run -p ptx_export --features llvm21 -- artifacts/ptx-inline inline
```

The builder API is `CudaBuilder::llvm_cleanup(...)`, with
`LlvmCleanup::{GlobalDce, Scalar, InlineScalar, Inline}`. These use bounded pass pipelines with verification at
the merged-module handoff. GlobalDce removes unreachable internal definitions
without scalar cleanup or inlining. InlineScalar combines target-aware inlining
and scalar cleanup; Inline additionally runs branch-correlated cleanup. These modes are experimental and disabled by default.

[Run 34786097065](https://github.com/brandonros/Rust-CUDA/actions/runs/34786097065)
verified both modes on LLVM 19 against standalone replay and packages IR, PTX, SASS,
resource reports and numerical IR checks. The filtered helper loses two SASS
selects, but the combined filtered/stepped kernel grows in instruction count;
this is not an established performance win. See the [measured results and
correctness limits](guarded-select.md#validated-integration) before using either
mode for a workload.

Merged-module GlobalDCE is enabled by default on the modern backend. Use
`CudaBuilder::llvm_global_dce(false)` or exporter mode `none` to disable it.
The other transformations remain opt-in. The [wave-2 report](optimization-wave2.md)
records retention checks, all four mining comparisons and the reasons not to
promote inlining as a general default.

The [five-area investigation](optimization-roadmap.md) includes default-off
per-module cleanup, inlining policy and size-oriented builds, memory cleanup,
and a pinned Solana mining workload. Static Solana results favor inlining plus
scalar cleanup; additional memory passes have not shown an advantage. Runtime
performance on NVIDIA remains unmeasured.

The consolidated [optimization results](optimization-results.md) record which
passes helped, which did not, and the remaining runtime-validation limits.
