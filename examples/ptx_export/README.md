# Export PTX without a GPU host application

This example compiles three Rust kernels to PTX without linking a CUDA host
application or launching an NVIDIA GPU. Compilation still requires the normal
Rust-CUDA Linux toolchain, CUDA toolkit, and NVVM libraries.

```sh
nix develop .#v19 --command cargo run -p ptx_export --features llvm19 -- artifacts/ptx
```

The exporter uses `CudaBuilder`'s feature-dependent target default: `compute_100`
with `llvm19`, or `compute_75` without it. This keeps the target compatible with
the selected NVVM IR dialect; overriding it to `compute_89` on the LLVM 19 path
selects NVVM's legacy reader and fails to parse the generated bitcode.

The output `rust_kernels.ptx` contains:

- `rust_vecadd(a: pointer, b: pointer, out: pointer, count: u32)`
- `rust_sha256_32(input: pointer, out: pointer, count: u32)`
- `rust_guarded_select(table: pointer, limits: pointer, initials: pointer, out: pointer, count: u32)`

Pointers are 64-bit PTX addresses. Each SHA-256 work item reads exactly 32 bytes
and writes the corresponding 32-byte digest. All kernels bounds-check the
thread index so callers can round their dispatch size up. Inputs and outputs
must not overlap. These explicit pointer/count interfaces avoid requiring a
consumer to infer Rust slice or aggregate layouts.

Keep the generated PTX unchanged when testing another PTX consumer. Successful
export alone does not establish compatibility or numerical GPU correctness.

The guarded-select experiment has a separate [test guide](guarded-select.md).
