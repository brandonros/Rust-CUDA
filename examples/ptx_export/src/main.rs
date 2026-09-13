use cuda_builder::{CudaBuilder, Llvm19Cleanup};
use std::{env, fs, path::PathBuf};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let output = PathBuf::from(
        env::args_os()
            .nth(1)
            .unwrap_or_else(|| "artifacts/ptx".into()),
    );
    fs::create_dir_all(&output)?;
    let output = output.canonicalize()?;
    let kernels = env::args_os()
        .nth(3)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("kernels"));
    let mut builder = CudaBuilder::new(kernels);
    if let Some(features) = env::args().nth(4) {
        builder = builder.build_args(&["--no-default-features", "--features", &features]);
    }
    match env::args().nth(2).as_deref().unwrap_or("none") {
        "none" => {}
        "size-s" => {
            builder = builder
                .llvm19_cleanup(Llvm19Cleanup::Inline)
                .build_args(&["--config", "profile.release.opt-level=\"s\""])
        }
        "size-z" => {
            builder = builder
                .llvm19_cleanup(Llvm19Cleanup::Inline)
                .build_args(&["--config", "profile.release.opt-level=\"z\""])
        }
        "module-scalar" => builder = builder.llvm19_module_cleanup(true),
        "module-inline" => {
            builder = builder
                .llvm19_module_cleanup(true)
                .llvm19_cleanup(Llvm19Cleanup::Inline)
        }
        "dce" => builder = builder.llvm19_cleanup(Llvm19Cleanup::GlobalDce),
        "scalar" => builder = builder.llvm19_cleanup(Llvm19Cleanup::Scalar),
        "inline" => builder = builder.llvm19_cleanup(Llvm19Cleanup::Inline),
        _ => {
            return Err(
                "cleanup mode must be none, dce, scalar, inline, module-scalar, module-inline, size-s, or size-z".into(),
            );
        }
    }
    let ptx = builder
        .copy_to(output.join("rust_kernels.ptx"))
        .final_module_path(output.join("final-module.ll"))
        .emit_llvm_ir(true)
        .build()
        .map_err(|error| std::io::Error::other(format!("PTX compilation failed: {error:?}")))?;
    println!("Exported {}", ptx.display());
    Ok(())
}
