use cuda_builder::CudaBuilder;
use std::{env, fs, path::PathBuf};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let output = PathBuf::from(
        env::args_os()
            .nth(1)
            .unwrap_or_else(|| "artifacts/ptx".into()),
    );
    fs::create_dir_all(&output)?;
    let output = output.canonicalize()?;
    let kernels = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("kernels");
    let ptx = CudaBuilder::new(kernels)
        .copy_to(output.join("rust_kernels.ptx"))
        .final_module_path(output.join("final-module.ll"))
        .emit_llvm_ir(true)
        .build()
        .map_err(|error| std::io::Error::other(format!("PTX compilation failed: {error:?}")))?;
    println!("Exported {}", ptx.display());
    Ok(())
}
