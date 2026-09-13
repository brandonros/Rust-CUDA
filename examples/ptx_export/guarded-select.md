# Guarded loop-carried value experiment

This is a producer-side semantic experiment, not a confirmed Rust-CUDA bug
reproducer. The original LLVM 19 Ed25519 PTX preserved a register on even loop
iterations, then replaced it on odd iterations before using it. CuMetal's SSA
import initially rejected the incoming undefined register. A smaller source
program lets us investigate independently of curve arithmetic and CuMetal.

The shared source is `kernels/src/guarded_select.rs`. It uses fully initialized,
defined Rust and contains three separately named, non-inlined functions:

| Function | Behavior | Expected dependency on initial value |
| --- | --- | --- |
| `preserved` | Conditionally update the remembered index; read the table only on odd iterations | None |
| `direct` | Read the table at the current odd index directly | None |
| `observed` | Conditionally update, but read the table on every iteration | Yes, when the loop executes |

All loops cap the runtime limit at 64. All arithmetic sums wrap at 64 bits.
The third function is a negative control: changing its conditional assignment
to an unconditional assignment must change some results. We do not use
uninitialized Rust values, `MaybeUninit`, or hand-authored PTX to force a shape.
The compiler may legally remove the first function's initializer or the entire
select. Emitting no self-referential `selp` is not a test failure; it means this
candidate did not reproduce that instruction shape.

## CPU checks on a Mac or Linux

Run from the repository root; this needs only a native Rust compiler, no CUDA:

```sh
rustc --edition=2024 --test examples/ptx_export/kernels/src/guarded_select.rs -o /tmp/guarded-select-debug
/tmp/guarded-select-debug
rustc --edition=2024 -O --test examples/ptx_export/kernels/src/guarded_select.rs -o /tmp/guarded-select-release
/tmp/guarded-select-release
```

Tests cover four tables, six initial values and 67 limits (0..65 plus u32::MAX):
1,608 input combinations per build, each checking all three functions against
an independent index-based oracle. High-bit values and wrapping sums are
included. An explicit negative control uses table[i]=i, limit=1, initial=17:
outputs must be `[0, 0, 17]`.

These tests passed locally with native rustc 1.97.1 in both modes. They do not
exercise the NVVM backend. The export workflow also runs them before exporting.

Native optimized LLVM IR provides another useful observation: `preserved` no
longer uses its initial-value argument or carries `remembered` around the loop;
its odd branch directly indexes with the loop counter. `observed` retains the
initial-value dependency. This demonstrates a legal optimization on the native
backend, not the instruction shape that NVVM will produce. To inspect it:

```sh
rustc --edition=2024 -O --crate-type lib --emit=llvm-ir examples/ptx_export/kernels/src/guarded_select.rs -o /tmp/guarded-select-native.ll
```

## PTX generation and inspection

On the supported Linux CUDA/NVVM environment for this checkout:

```sh
nix develop .#v19 --command cargo run -p ptx_export --features llvm19 -- artifacts/ptx
```

This worktree uses the portable PTX branch's LLVM 19 producer. The existing exporter includes `final-module.ll` and LLVM IR emission.
Record the source revision, rustc version, CUDA/NVVM version and target for every
comparison. The default/LLVM 7 path can also export with its matching `.#v7`
flake shell and without `--features llvm19`. Keep outputs in
separate directories. Do not assume identical targets between dialects.

Find `rust_guarded_select` and its reachable helper functions in the PTX. Check
whether a self-referential false operand survives optimization, and trace its
uses and branch predicate if it does. Compare the observable control as well.
The presence of a self-reference alone is not proof of incorrect code generation.

## GPU ABI and oracle

`rust_guarded_select(table, limits, initials, out, count)` takes:

- A common 64-element u64 table.
- `count` u32 limits and `count` u64 initial values.
- An output allocation of `3 * count` u64s, plus optional guard words.

Each work item writes `[preserved, direct, observed]`. Inputs and outputs must
not overlap. The kernel bounds-checks its work-item index; launch extra threads
to test this and verify trailing output guards.

For `n = min(limit, 64)`, the independent expected outputs are:

1. Sum of table[i] for odd i in 0..n, wrapping modulo 2^64.
2. The same sum.
3. For i=0 use table[initial & 63]; for i>0 use table[(i-1)|1],
   summing over 0..n with the same wrapping. For n=0, all sums are zero.

A future NVIDIA execution should compare all three outputs, not merely compare
the first two: two incorrect functions could otherwise agree. Running on NVIDIA
isolates Rust-CUDA/NVVM from CuMetal; running the same artifact on Metal adds a
consumer comparison. This change adds the export kernel and CPU oracle, but no
NVIDIA runner or GPU numerical result. PTX generation cannot run natively in
this Mac's CUDA-less environment and has not yet been verified for this change.

## LLVM 19 offline codegen artifact

The export workflow now runs `inspect_codegen.py` after PTX generation. It uses
that PTX's declared target, assembles at `-O3` with relocation preservation,
and records NVIDIA disassembly and resource usage without launching a GPU.
The `rust-ptx` artifact includes build commands/logs, compiler/tool versions,
lockfiles, per-crate LLVM IR, linked `final-module.ll`, unchanged PTX, cubin,
`nvdisasm.txt`, `sass.txt`, assembler spill/register reports, and checksums.
`codegen-summary.md` and `.json` inventory named functions and opcodes.

The analysis must follow the preserved/direct helpers through any merging,
inlining or renaming. Static counts and matching histograms are not proofs of
semantic equivalence or runtime cost. Use the observable control to distinguish
removing unused preservation from incorrectly deleting a meaningful dependency.
A missing self-select means this candidate did not reproduce the original PTX
shape; it does not prove that the larger Ed25519 case was optimized identically.

Tool semantics: [NVIDIA binary utilities](https://docs.nvidia.com/cuda/cuda-binary-utilities/).
This artifact pipeline is LLVM 19 only; it does not involve the LLVM 21 worktree.

## Measured LLVM 19 baseline (2026-09-13)

[CI run 34782620441](https://github.com/brandonros/Rust-CUDA/actions/runs/34782620441)
succeeded at source `f5df0590d2938c5dec42c38bf908dcd34ef193e8`. Download the
`rust-ptx` artifact there for IR, PTX, cubin, disassembly and resource reports.
All 43 checksummed artifact files verified after download. PTX SHA-256:
`0abd6c9c5dc9b40eafd382180385bbd3c02d44a91c1e2e904e7951e835d72f60`.
Assembler: CUDA 13.2, ptxas V13.2.51, target sm_100, optimization O3.

| Helper | PTX instructions | Self-false PTX selects | SASS instructions through return | SASS global-load sites | SASS SEL sites |
| --- | ---: | ---: | ---: | ---: | ---: |
| preserved | 123 | 0 | 172 | 21 | 0 |
| direct | 123 | 0 | 174 | 21 | 0 |
| observed control | 180 | 1 | 238 | 22 | 11 |

These are static counts, not per-launch or per-iteration counts. SASS counts
exclude the trailing unreachable self-branch and ten NOP padding instructions
following the final helper's return. Helper boundaries are the named function
labels in `nvdisasm.txt`; cuobjdump groups them under the calling kernel.
The assembler reports zero stack frame, spill stores and spill loads for all
three helpers. The combined `rust_guarded_select` kernel uses 32 registers;
that is not an independently measured register count for each variant.

The PTX bodies for preserved/direct are textually identical after replacing
their own function names and function-specific `$L__BB` prefixes. In contrast,
the pre-NVVM `final-module.ll` still contains the initial/remembered storage.
That dump is written before adding the module to NVVM (`nvvm.rs`), so the
redundancy is eliminated by the time NVVM emits PTX. SASS has register-allocation
and move differences; it is not byte-identical. The difference in static
instruction counts does not establish that either source form runs faster.

Conclusion: this candidate does not reproduce the original Ed25519 missed-
optimization suspicion. It shows NVVM removes the unnecessary bookkeeping in
the small guarded example while retaining selection for the observable control.
The next useful reduction starts from the original Ed25519 loop and preserves
its PTX self-select as a reduction criterion, rather than forcing an instruction
into the small Rust source. NVIDIA runtime correctness and performance remain
unmeasured.

`ptxas` warned that relocation preservation is not fully implemented for sm_100.
Both disassemblers completed successfully; the warning is retained in the raw
assembler report and no complete-relocation guarantee is inferred.

## Source-guided reduction: filtered iteration

Dalek 4.1.3 `edwards.rs`, `mul_base`, iterates with
`(0..$adds).filter(|x| x % 2 == 1)` before an even-index pass. The first
reproducer used an explicit conditional inside the loop and omitted this
iterator structure. The next candidate retains the filtered range but removes
curve arithmetic, scalar conversion and the precomputed-point table, replacing
the body with a wrapping sum of runtime table entries. `stepped` performs the
same odd-index accesses using `step_by(2)` as a source-level comparison.

`rust_filtered_select(table, limits, out, count)` writes two u64 results per
case: filtered and stepped. Both must equal the existing independent sum of
odd-index table entries for `min(limit, 64)`. CPU tests exercise both functions
alongside the previous variants. No instruction shape is forced with assembly
or undefined Rust. This is a candidate reduction until LLVM 19 output confirms
whether an unobserved self-select survives.

## Successful source reduction: filtered range (2026-09-13)

[CI run 34783117581](https://github.com/brandonros/Rust-CUDA/actions/runs/34783117581)
compiled, assembled and uploaded the reduction at source
`d360d1184dfd36ec9723dea83c047cb234613e2b`. All downloaded artifact checksums
verified. Full PTX SHA-256:
`d97b462c4c17e9390b82f676d39d3359dd5a438598b10382fef8705ab9379f37`.

The small `filtered` Rust function DOES reproduce the original shape. No curve
arithmetic, scalar conversion, precomputed tables, or undefined Rust is needed:

```rust
let mut sum = 0u64;
for i in (0..limit.min(64) as usize).filter(|x| x % 2 == 1) {
    sum = sum.wrapping_add(table[i]);
}
```

The exact emitted helper is checked in at
[evidence/llvm19-filtered-helper.ptx](evidence/llvm19-filtered-helper.ptx).
Its relevant original instructions are:

```ptx
and.b64 %rd5, %rd10, 1;
setp.ne.b64 %p2, %rd5, 0;
selp.b64 %rd11, %rd10, %rd11, %p2;
mov.b64 %rd10, %rd3;
@%p2 bra $L__BB1_3;
bra.uni $L__BB1_1;
$L__BB1_3:
shl.b64 %rd6, %rd11, 3;
```

As in Ed25519, the selected index is read only on the matching true path. The
false path preserves an index that is not observed before replacement. This is
not the sum accumulator: `%rd9` carries that separately. The `stepped` comparison
has no self-referential false select. Both source variants pass the CPU oracle in
debug and optimized builds, including empty, capped, and wrapping-sum cases.

Unlike the explicit-if candidate, NVIDIA assembly retains the index selection:

```text
/*0530*/      LOP3.LUT P1, RZ, R10, 0x1, RZ, 0xc0, !PT ;
/*0540*/      SEL R11, R10, R11, P1 ;
/*0550*/      SEL R14, R9, R14, P1 ;
...
/*0590*/  @P1 LEA R4, P0, R11, R4, 0x3 ;
/*05a0*/  @P1 LEA.HI.X R5, R11, R5, R14, 0x3, P0 ;
/*05b0*/  @P1 LDG.E.64 R4, desc[UR6][R4.64] ;
```

The 64-bit PTX select becomes two unpredicated 32-bit SASS selects. The indexed
load remains predicated, so this is evidence of retained register bookkeeping,
not an unnecessary table load. Both helpers have zero reported stack frame and
spills. The combined `rust_filtered_select` kernel uses 17 registers; per-helper
register savings are not established.

The pre-NVVM LLVM IR for `filtered` calls the standard library's
`Range<usize>::try_fold` with `Iterator::find::check`, returning an aggregate
`ControlFlow<usize>` value. This provides the next compiler-side tracing point
for how a filtered iterator result turns into the loop-carried select.

This is now a concrete candidate missed optimization that survives PTX and SASS
on CUDA 13.2 / sm_100, not merely a rejected CuMetal input. It is not a measured
performance regression or proof of a Rust source correctness bug. `step_by`
also changes loop structure; its instruction count alone is not a performance
comparison. Next investigations can use this small case to compare NVIDIA's
handling of the iterator lowering or benchmark equivalent loops on hardware.

## Opt-in handoff cleanup investigation

The workflow's manual `cleanup_experiment` input replays the saved pre-NVVM
module with LLVM 19 `opt`, without changing compiler defaults. It compares:

- `verify`: unchanged assembly/replay baseline.
- `function(sroa,instcombine<max-iterations=2;no-verify-fixpoint>,simplifycfg,adce),verify`: local scalar/control cleanup.
- `cgscc(inline),function(sroa,instcombine<max-iterations=2;no-verify-fixpoint>,simplifycfg,adce),globaldce,verify`:
  expose helper control flow before the same cleanup.

`replay_cleanup.py` uses the backend's LLVM 19 intrinsic bitcode, toolkit
libdevice, and the exporter's sole explicit NVVM option `-arch=compute_100`.
Library hashes, commands, pass strings and per-stage logs are retained. The
baseline must reproduce the original PTX function bodies (ignoring whitespace
and comments) before cleanup comparisons proceed. This guard does not substitute
for GPU numerical tests. Modified IR rejected by NVVM is reported as failure,
not evidence that the cleanup is safe to enable by default.

Artifacts are under `cleanup-experiment/`, with a separate IR/PTX/cubin/SASS and
resource-report directory per variant and `experiment.json` for status. The
initial investigation was launched as
[run 34783692948](https://github.com/brandonros/Rust-CUDA/actions/runs/34783692948)
on source `4678196`; this entry records launch, not a successful result.

### Handoff verification prerequisite

The first replay failed before running any cleanup: stock LLVM 19 rejected
`@llvm.used = internal global ...` with `invalid linkage for intrinsic global
variable`. The backend's internalization loop was changing every defined global
to internal linkage, including special appending globals. The fix preserves
appending linkage (including `llvm.used` and `llvm.compiler.used`) and leaves
ordinary defined globals subject to the existing internalization behavior.
The export workflow now verifies the real LLVM 19 handoff module with stock
`opt-19` on every run, independent of whether cleanup replay is requested.
This fixes a concrete IR validity issue; it is not a performance claim.

### Experimental compiler integration

`CudaBuilder::llvm19_cleanup(Llvm19Cleanup::Scalar)` opts into modern-PM
SROA, instruction combining, CFG simplification and aggressive DCE at the
merged-module handoff. `Llvm19Cleanup::Inline` additionally runs the modern
inliner first and GlobalDCE afterward. The default is `None`; LLVM 7 requests
are rejected. The low-level flags are `--llvm19-cleanup=scalar` and
`--llvm19-cleanup=inline`. No target-independent CPU default pipeline is enabled.
The wrapper registers modern analyses/proxies and verifies LLVM IR before and
after the pass pipeline. NVVM verification/compilation still follow normally.

The exporter accepts an optional second argument `scalar` or `inline` after
its output directory. It saves both `final-module.before-cleanup.ll` and
`final-module.ll`. The opt-in workflow now also compiles both modes through the
real backend and requires their PTX function bodies to match offline replay,
then assembles and disassembles them. This tests plumbing and output consistency;
it does not establish numerical GPU correctness or warrant enabling defaults.

InstCombine is explicitly bounded to two iterations with its fixed-point
assertion disabled. LLVM 19's default one-iteration fixed-point assertion aborts
on this valid handoff module; failing to finish all simplifications is distinct
from producing invalid IR. Replay still uses `-verify-each`, and the integrated
backend verifies the module before and after cleanup. This setting permits
bounded optimization without promising that every combining opportunity is exhausted.
