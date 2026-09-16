use std::env;
use std::path;

use cuda_builder::CudaBuilder;

fn main() {
    println!("cargo::rerun-if-env-changed=RUST_CUDA_CODEGEN_BACKEND");
    let backend = env::var_os("RUST_CUDA_CODEGEN_BACKEND")
        .expect("Set RUST_CUDA_CODEGEN_BACKEND to the already-built rustc_codegen_nvvm dylib");
    println!("cargo::rerun-if-changed=build.rs");
    println!("cargo::rerun-if-changed=kernels");

    let out_path = path::PathBuf::from(env::var("OUT_DIR").unwrap());
    let manifest_dir = path::PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());

    CudaBuilder::new(manifest_dir.join("kernels"), &backend)
        .copy_to(out_path.join("kernels.ptx"))
        .build()
        .unwrap();
}
