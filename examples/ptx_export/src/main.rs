use cuda_builder::{CudaBuilder, LlvmCleanup};
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
    let backend = env::var_os("RUST_CUDA_CODEGEN_BACKEND")
        .ok_or("Set RUST_CUDA_CODEGEN_BACKEND to the already-built rustc_codegen_nvvm dylib")?;
    let mut builder = CudaBuilder::new(kernels, backend);
    if let Some(features) = env::args().nth(4) {
        builder = builder.build_args(&["--no-default-features", "--features", &features]);
    }
    let mode = env::args().nth(2).unwrap_or_else(|| "default".into());
    // Historical wave-1 experiments explicitly isolate their selected pipeline.
    // The default mode exercises the production default without overrides.
    if cfg!(feature = "llvm21") && mode != "default" {
        builder = builder.llvm_global_dce(false);
    }
    match mode.as_str() {
        "default" => {}
        "none" => {}
        "size-s" => {
            builder = builder
                .llvm_cleanup(LlvmCleanup::Inline)
                .build_args(&["--config", "profile.release.opt-level=\"s\""])
        }
        "size-z" => {
            builder = builder
                .llvm_cleanup(LlvmCleanup::Inline)
                .build_args(&["--config", "profile.release.opt-level=\"z\""])
        }
        "module-scalar" => builder = builder.llvm_module_cleanup(true),
        "module-inline" => {
            builder = builder
                .llvm_module_cleanup(true)
                .llvm_cleanup(LlvmCleanup::Inline)
        }
        "inline-scalar" => builder = builder.llvm_cleanup(LlvmCleanup::InlineScalar),
        "dce" => builder = builder.llvm_cleanup(LlvmCleanup::GlobalDce),
        "scalar" => builder = builder.llvm_cleanup(LlvmCleanup::Scalar),
        "inline" => builder = builder.llvm_cleanup(LlvmCleanup::Inline),
        _ => {
            return Err(
                "cleanup mode must be default, none, dce, scalar, inline, inline-scalar, module-scalar, module-inline, size-s, or size-z".into(),
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
