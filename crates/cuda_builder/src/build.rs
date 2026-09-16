//! Kernel build orchestration: prepare Cargo, run it, and publish the PTX file.

use std::{
    env, fs,
    path::{Path, PathBuf},
    process::{Command, Stdio},
};

use crate::{CudaBuilder, CudaBuilderError, artifact, backend, flags, timing};

pub(crate) fn build(builder: &CudaBuilder) -> Result<PathBuf, CudaBuilderError> {
    let _timing = timing::phase("cuda_builder", &builder.path_to_crate.to_string_lossy());
    println!("cargo:rerun-if-env-changed=NVVM_TIMING_DIR");
    println!("cargo:rerun-if-changed={}", builder.path_to_crate.display());
    if !builder.path_to_crate.is_dir() {
        return Err(CudaBuilderError::CratePathDoesntExist(
            builder.path_to_crate.clone(),
        ));
    }

    let path = compile(builder)?;
    if let Some(copy_path) = &builder.ptx_file_copy_path {
        let _timing = timing::phase("copy_ptx", &copy_path.to_string_lossy());
        fs::copy(path, copy_path).map_err(CudaBuilderError::FailedToCopyPtxFile)?;
        Ok(copy_path.clone())
    } else {
        Ok(path)
    }
}

fn compile(builder: &CudaBuilder) -> Result<PathBuf, CudaBuilderError> {
    let _timing = timing::phase("prepare_and_build_kernels", "");
    let backend = {
        let _timing = timing::phase("resolve_backend", "");
        backend::resolve(&builder.codegen_backend).map_err(CudaBuilderError::Backend)?
    };
    let mut rustflags = flags::rustflags(builder, &backend)?;
    let timing_dir = env::var_os("NVVM_TIMING_DIR").map(PathBuf::from);
    if let Some(directory) = &timing_dir {
        add_self_profiling(&mut rustflags, directory);
    }
    let target_dir = nested_target_dir_from_env();
    let mut cargo = cargo_command(builder, target_dir.as_deref(), timing_dir.is_some());
    backend::configure_loader(&mut cargo, &backend)?;
    cargo.env("CARGO_ENCODED_RUSTFLAGS", flags::encode(&rustflags)?);

    let output = {
        let _timing = timing::phase("nested_cargo", &builder.path_to_crate.to_string_lossy());
        cargo.output().map_err(CudaBuilderError::CargoInvocation)?
    };
    let _timing = timing::phase("read_ptx_artifact", "");
    // Forward stdout diagnostics even when Cargo fails. Its exit status takes
    // precedence over missing/partial artifacts from an unsuccessful build.
    let artifact = artifact::read(&output.stdout);
    if !output.status.success() {
        return Err(CudaBuilderError::BuildFailed);
    }
    artifact
}

fn cargo_command(builder: &CudaBuilder, target_dir: Option<&Path>, timings: bool) -> Command {
    let mut cargo = Command::new("cargo");
    cargo.args([
        "build",
        "--lib",
        "--message-format=json-render-diagnostics",
        "-Zbuild-std=core,alloc",
        "--target=nvptx64-nvidia-cuda",
    ]);
    cargo.args(&builder.build_args);
    if timings {
        cargo.arg("--timings");
    }
    if builder.release {
        cargo.arg("--release");
    }
    if builder.optix {
        cargo.args(["-Zunstable-options", "--config", "optix=\"1\""]);
    }
    if let Some(target_dir) = target_dir {
        cargo.arg("--target-dir").arg(target_dir);
    }
    // The backend's target configuration alone does not disable f16/f128.
    cargo.env("CARGO_FEATURE_NO_F16_F128", "1");
    cargo
        .stderr(Stdio::inherit())
        .current_dir(&builder.path_to_crate);
    cargo
}

fn add_self_profiling(rustflags: &mut Vec<String>, directory: &Path) {
    let directory = directory.join("rustc");
    // rustc generates per-invocation filenames inside this directory.
    match fs::create_dir_all(&directory) {
        Ok(()) => {
            rustflags.push(format!("-Zself-profile={}", directory.display()));
            rustflags.push("-Ztime-passes".into());
        }
        Err(error) => eprintln!("Could not create rustc self-profile directory: {error}"),
    }
}

fn nested_target_dir_from_env() -> Option<PathBuf> {
    nested_target_dir(
        Path::new(&env::var_os("OUT_DIR")?),
        &env::var("PROFILE").ok()?,
    )
}

fn nested_target_dir(out_dir: &Path, profile: &str) -> Option<PathBuf> {
    // Strip <profile>/build/<package>/out and isolate the nested build to avoid
    // deadlocking on the outer Cargo invocation's target-directory lock.
    if out_dir.file_name()? != "out" {
        return None;
    }
    let build = out_dir.parent()?.parent()?;
    let profile_dir = build.parent()?;
    if build.file_name()? != "build" || profile_dir.file_name()? != profile {
        return None;
    }
    Some(profile_dir.parent()?.join("cuda-builder"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn isolates_nested_builds_in_custom_and_cross_target_directories() {
        for root in [
            "target",
            "custom-output",
            "target/aarch64-unknown-linux-gnu",
        ] {
            let root = Path::new(root);
            let out = root.join("debug/build/host-123/out");
            assert_eq!(
                nested_target_dir(&out, "debug"),
                Some(root.join("cuda-builder"))
            );
            assert_eq!(nested_target_dir(&out, "release"), None);
        }
        assert_eq!(
            nested_target_dir(Path::new("target/debug/out"), "debug"),
            None
        );
    }

    #[test]
    fn cargo_configuration_preserves_argument_boundaries() {
        let builder = CudaBuilder::new("kernel directory", "backend")
            .release(false)
            .optix(true)
            .build_args(&["--features", "feature-a,feature-b"]);
        let cargo = cargo_command(&builder, Some(Path::new("target with spaces")), true);
        let args: Vec<_> = cargo.get_args().map(|arg| arg.to_str().unwrap()).collect();
        assert_eq!(
            args,
            [
                "build",
                "--lib",
                "--message-format=json-render-diagnostics",
                "-Zbuild-std=core,alloc",
                "--target=nvptx64-nvidia-cuda",
                "--features",
                "feature-a,feature-b",
                "--timings",
                "-Zunstable-options",
                "--config",
                "optix=\"1\"",
                "--target-dir",
                "target with spaces",
            ]
        );
        assert_eq!(cargo.get_current_dir(), Some(Path::new("kernel directory")));
    }
}
