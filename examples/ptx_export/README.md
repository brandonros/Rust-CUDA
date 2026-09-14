# Export PTX without a GPU host application

Compile vector-addition and SHA-256 kernels without linking a CUDA host
application or launching a GPU. Compilation requires the Linux Rust-CUDA
toolchain, CUDA toolkit, and NVVM libraries.

```sh
nix develop .#v21 --command cargo run -p ptx_export --features llvm21 -- artifacts/ptx
```

The output is `rust_kernels.ptx`; `final-module.ll` records the NVVM input.
The builder selects `compute_100` with LLVM 21 and `compute_75` with LLVM 7.
The kernels accept explicit pointer/count arguments. SHA-256 reads and writes
32 bytes per work item. Input and output buffers must not overlap.

Export success does not establish another PTX consumer's numerical correctness.

The exporter also includes guarded-select regression kernels. Modern LLVM
GlobalDCE runs by default; use the second argument `none` to disable it.
Experimental modes are `dce`, `scalar`, `inline-scalar`, `inline`,
`module-scalar`, `module-inline`, `size-s`, and `size-z`. Optional third and
fourth arguments select a kernel crate and its features.

Historical `llvm19_*` builder settings control the LLVM 21 backend on this
stack. These names and pipelines are preserved from the original branch.
The DCE retention check covers used globals, external functions, initialized
data, and unreachable negative controls. Replay checks compare integrated
cleanup with standalone LLVM processing. GPU runtime validation is separate.
