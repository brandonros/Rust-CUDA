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
