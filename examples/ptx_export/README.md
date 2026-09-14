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
