<div align="center">
  <h1>The Rust CUDA Project</h1>

  <p>
    <strong>An ecosystem of libraries and tools for writing and executing extremely fast GPU code
    fully in <a href="https://www.rust-lang.org/">Rust</a></strong>
  </p>
</div>

> [!IMPORTANT]
> This project is no longer dormant and is [being
> rebooted](https://rust-gpu.github.io/blog/2025/01/27/rust-cuda-reboot). Read the [latest status update](https://rust-gpu.github.io/blog/2025/08/11/rust-cuda-update).
> Please contribute!
>
> The project is still in early development, however. Expect bugs, safety issues, and things that
> don't work.

## Documentation

Please see [The Rust CUDA Guide](https://rust-gpu.github.io/rust-cuda/) for documentation on Rust
CUDA.

## Building kernels

`CudaBuilder` requires an already-built backend dylib:

```rust,ignore
CudaBuilder::new("kernels", "/path/to/librustc_codegen_nvvm.so").build()?;
```

Build the backend separately with the same Rust toolchain and LLVM flavor as
the kernel build. The examples and samples read `RUST_CUDA_CODEGEN_BACKEND` and
pass its value to the constructor; the library has no environment-variable
fallback or automatic backend build. For LLVM 21 on Linux, from this checkout:

```sh
nix develop .#v21 --command cargo build -p rustc_codegen_nvvm --features llvm21 --target-dir target/cuda-builder-codegen
export RUST_CUDA_CODEGEN_BACKEND="$PWD/target/cuda-builder-codegen/debug/librustc_codegen_nvvm.so"
nix develop .#v21 --command cargo build -p vecadd --features llvm21
```

Use a backend built without `--features llvm21` for legacy LLVM 7 consumers.
Windows uses `rustc_codegen_nvvm.dll`; macOS uses `librustc_codegen_nvvm.dylib`.
The former `cuda_builder/rustc_codegen_nvvm` feature has been removed.

## Compiler phase timings

From the consuming project's directory, capture the complete command:

```sh
/path/to/rust-cuda/scripts/trace-build.sh \
  nix develop .#v21 --command cargo build --release --timings -vv --features llvm21,self_test
```

The script prints its log location immediately. `build.log` captures the command,
start/end times, exit status, Nix setup output, and verbose Cargo output. Cargo's
HTML timing reports are in each build's target directory under `cargo-timings/`;
the nested kernel build has its own target directory and report.

The script sets `NVVM_TIMING_DIR` to a fresh directory under
`~/.cache/rust-cuda-traces` (or `$XDG_CACHE_HOME`). You can also set this variable
yourself. Each builder/compiler process writes `rust-cuda-<pid>.log` there.
Records include Unix timestamps for cross-process correlation, monotonic elapsed
milliseconds, thread ID, and codegen-unit name where available. No phase logs are
created when unset. The logger is shared by `cuda_builder` and the backend through
the `nvvm` crate.

The phases cover backend path validation, sysroot lookup, nested Cargo,
artifact parsing/copying, backend initialization, codegen units, LLVM optimization, module merging,
internalization, cleanup/DCE, IR output, bitcode serialization, libnvvm verification,
and PTX compilation. Watch the files with `tail -f`: an unmatched `begin` identifies
work still in progress (or a process that terminated before finishing).
Phases can nest or overlap, so their durations should not be summed. `end` means
the scope exited, not that compilation succeeded; panic unwinding uses `unwind`.

With timing enabled, `cuda_builder` adds `--timings` to nested Cargo and
`-Ztime-passes` plus `-Zself-profile` to its rustc invocations. Rustc query profiles
are stored under `rustc/` in the trace directory, for analysis with the Rust
`measureme` tools. These expose compiler work before and during backend execution;
they cannot expose optimization passes hidden inside NVIDIA's libnvvm.

Changing `NVVM_TIMING_DIR` reruns consuming build scripts that use `CudaBuilder`;
cached dependencies remain cached. For a genuinely cold build, select a fresh
`CARGO_TARGET_DIR` after entering the development shell. Warm and cold timings
measure different work. Existing running compilers cannot be instrumented.
For local development, patch the consuming project to use the matching local
Rust-CUDA crates together, rather than mixing them with a pinned Git revision.

## License

Licensed under either of

- Apache License, Version 2.0, ([LICENSE-APACHE](LICENSE-APACHE) or
  http://www.apache.org/licenses/LICENSE-2.0)
- MIT license ([LICENSE-MIT](LICENSE-MIT) or http://opensource.org/licenses/MIT)

at your discretion.

### Contribution

Unless you explicitly state otherwise, any contribution intentionally submitted for inclusion in
the work by you, as defined in the Apache-2.0 license, shall be dual licensed as above, without any
additional terms or conditions.
