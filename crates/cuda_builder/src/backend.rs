//! Validate the supplied backend and configure its shared-library dependencies.

use std::{
    collections::HashSet,
    env, fs,
    path::{Path, PathBuf},
    process::Command,
};

use crate::{CudaBuilderError, timing};

pub(crate) fn resolve(path: &Path) -> Result<PathBuf, String> {
    // Resolve before the kernel build changes its working directory.
    println!("cargo:rerun-if-changed={}", path.display());
    let absolute = fs::canonicalize(path)
        .map_err(|error| format!("cannot use {}: {error}", path.display()))?;
    if !absolute.is_file() {
        return Err(format!("{} is not a backend file", path.display()));
    }
    Ok(absolute)
}

pub(crate) fn configure_loader(cmd: &mut Command, backend: &Path) -> Result<(), CudaBuilderError> {
    extend_library_path_env(cmd, &backend_library_dirs(backend))
}

// https://github.com/rust-lang/cargo/blob/1857880b5124580c4aeb4e8bc5f1198f491d61b1/src/cargo/util/paths.rs#L29-L52
fn dylib_path_envvar() -> &'static str {
    if cfg!(windows) {
        "PATH"
    } else if cfg!(target_os = "macos") {
        "DYLD_FALLBACK_LIBRARY_PATH"
    } else {
        "LD_LIBRARY_PATH"
    }
}

fn extend_library_path_env(cmd: &mut Command, dirs: &[PathBuf]) -> Result<(), CudaBuilderError> {
    let var = dylib_path_envvar();
    let mut paths: Vec<PathBuf> = dirs.iter().filter(|dir| dir.is_dir()).cloned().collect();

    if paths.is_empty() {
        return Ok(());
    }

    if let Some(existing) = env::var_os(var) {
        paths.extend(env::split_paths(&existing));
    }

    let joined = env::join_paths(paths)
        .map_err(|error| CudaBuilderError::Backend(format!("cannot set {var}: {error}")))?;
    cmd.env(var, joined);
    Ok(())
}

fn backend_library_dirs(backend: &Path) -> Vec<PathBuf> {
    let mut dirs = Vec::new();
    if let Some(parent) = backend.parent() {
        dirs.push(parent.to_path_buf());
        if let Some(grand) = parent.parent() {
            dirs.push(grand.to_path_buf());
        }
        if parent.file_name().is_none_or(|name| name != "deps") {
            dirs.push(parent.join("deps"));
        }
    }
    dirs.extend(rustc_sysroot_lib_dirs());
    let mut seen = HashSet::new();
    dirs.retain(|dir| seen.insert(dir.clone()));
    dirs
}

fn rustc_sysroot_lib_dirs() -> Vec<PathBuf> {
    let _timing = timing::phase("find_sysroot", "");
    let mut dirs = Vec::new();

    let sysroot = match Command::new("rustc").args(["--print", "sysroot"]).output() {
        Ok(output) if output.status.success() => {
            String::from_utf8_lossy(&output.stdout).trim().to_owned()
        }
        _ => return dirs,
    };

    let sysroot = PathBuf::from(sysroot);
    dirs.push(sysroot.join("lib"));

    for variable in ["TARGET", "HOST"] {
        if let Some(triple) = env::var_os(variable) {
            dirs.push(sysroot.join("lib").join("rustlib").join(triple).join("lib"));
        }
    }

    dirs
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn uses_only_the_supplied_file() {
        let path = std::env::current_exe().unwrap();
        assert_eq!(resolve(&path).unwrap(), path.canonicalize().unwrap());
        assert!(resolve(&path.join("missing")).is_err());
        assert!(resolve(path.parent().unwrap()).is_err());
    }
}
