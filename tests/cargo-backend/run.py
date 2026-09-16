#!/usr/bin/env python3
"""Check Cargo backend identity and rustc-private isolation without CUDA/LLVM builds.

Requires the project's Rust toolchain, including rustc-dev. Uses the production
proc macro with a small rustc-private dylib in place of the full NVVM backend.
"""
import json
from pathlib import Path
import subprocess
import tempfile


root = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix="cuda backend identity ") as directory:
    workspace = Path(directory)
    files = {
        "Cargo.toml": '''[workspace]
resolver = "2"
members = ["backend", "bridge", "consumer"]
''',
        "backend/Cargo.toml": '''[package]
name = "rustc_codegen_nvvm"
version = "0.3.0"
edition = "2024"
[lib]
crate-type = ["dylib"]
[features]
llvm21 = []
''',
        "backend/src/lib.rs": '''#![feature(rustc_private)]
extern crate rustc_driver;
pub static BACKEND_LIBRARY_MARKER: u8 = if cfg!(feature = "llvm21") { 21 } else { 7 };
''',
        "bridge/Cargo.toml": '''[package]
name = "cuda_builder_backend"
version = "0.1.0"
edition = "2024"
[lib]
proc-macro = true
path = ''' + json.dumps(str(root / "crates/cuda_builder_backend/src/lib.rs")) + '''
[features]
llvm21 = ["rustc_codegen_nvvm/llvm21"]
[dependencies]
rustc_codegen_nvvm = { path = "../backend" }
[target.'cfg(unix)'.dependencies]
libc = "0.2"
''',
        "consumer/Cargo.toml": '''[package]
name = "consumer"
version = "0.1.0"
edition = "2024"
[features]
llvm21 = ["cuda_builder_backend/llvm21"]
[build-dependencies]
cuda_builder_backend = { path = "../bridge" }
''',
        # No rustc_private gate here: it must not leak into consumer build scripts.
        "consumer/build.rs": '''fn main() {
    println!("cargo:rerun-if-changed=build.rs");
    let path = cuda_builder_backend::backend_path!();
    assert!(std::path::Path::new(path).is_file());
    std::fs::write(
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("selected-backend"), path
    ).unwrap();
}
''',
        "consumer/src/lib.rs": "",
    }
    for name, contents in files.items():
        path = workspace / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)
    (workspace / "Cargo.lock").write_bytes((root / "Cargo.lock").read_bytes())
    (workspace / "rust-toolchain.toml").write_bytes((root / "rust-toolchain.toml").read_bytes())
    target = workspace / "custom output"
    # Files a directory scanner could accidentally accept must have no effect.
    decoys = target / "debug/deps"
    decoys.mkdir(parents=True)
    for name in ("librustc_codegen_nvvm-old.so", "librustc_codegen_nvvm-old.dylib",
                 "rustc_codegen_nvvm-old.dll"):
        (decoys / name).write_text("stale backend")
    for index, options in enumerate(([], [], ["--features", "llvm21"], ["--features", "llvm21", "--release"])):
        result = subprocess.run(
            ["cargo", "build", "-p", "consumer", "--target-dir", str(target),
             "--message-format=json", *options], cwd=workspace,
            stdout=subprocess.PIPE, text=True, check=True,
        )
        artifacts = [json.loads(line) for line in result.stdout.splitlines()]
        backend = next(message for message in artifacts
                       if message.get("reason") == "compiler-artifact"
                       and message["target"]["name"] == "rustc_codegen_nvvm")
        expected = [Path(path).resolve() for path in backend["filenames"]
                    if Path(path).suffix in (".so", ".dylib", ".dll")]
        actual = Path((workspace / "consumer/selected-backend").read_text()).resolve()
        # Cargo can report a top-level copy while the loader uses deps/.
        assert len(expected) == 1 and actual.read_bytes() == expected[0].read_bytes(), (expected, actual)
        assert ("llvm21" in backend["features"]) == ("llvm21" in options)
        if index == 1:
            assert backend["fresh"], "the repeated build should reuse Cargo's backend"
        print(f"Verified exact Cargo backend: {options or 'default'}", flush=True)
