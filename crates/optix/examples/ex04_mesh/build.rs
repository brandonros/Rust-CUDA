use std::env;
use std::path;

use cuda_builder::CudaBuilder;

fn main() {
    println!("cargo::rerun-if-env-changed=RUST_CUDA_CODEGEN_BACKEND");
    let backend = env::var_os("RUST_CUDA_CODEGEN_BACKEND")
        .expect("Set RUST_CUDA_CODEGEN_BACKEND to the already-built rustc_codegen_nvvm dylib");
    let ptx_path = path::PathBuf::from(env::var("OUT_DIR").unwrap()).join("kernels.ptx");
    CudaBuilder::new("kernels", &backend)
        .copy_to(ptx_path)
        .build()
        .unwrap();
}
