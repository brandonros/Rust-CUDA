//! Translate builder options into rustc and backend arguments without running tools.

use std::path::Path;

use crate::{CudaBuilder, CudaBuilderError, DebugInfo, EmitOption, LlvmCleanup, NvvmOption};

pub(crate) fn rustflags(
    builder: &CudaBuilder,
    backend: &Path,
) -> Result<Vec<String>, CudaBuilderError> {
    let mut rustflags = vec![
        format!("-Zcodegen-backend={}", path_argument(backend)?),
        "-Zunstable-options".into(),
        "-Zcrate-attr=feature(register_tool)".into(),
        "-Zcrate-attr=register_tool(nvvm_internal)".into(),
        "-Zcrate-attr=no_std".into(),
        "-Zsaturating_float_casts=false".into(),
        "-Cpanic=immediate-abort".into(),
    ];

    if let Some(emit) = &builder.emit {
        let string = match emit {
            EmitOption::LlvmIr => "llvm-ir",
            EmitOption::Bitcode => "llvm-bc",
        };
        rustflags.push(format!("--emit={string}"));
    }

    let mut llvm_args = vec![NvvmOption::Arch(builder.arch).to_string()];
    if !builder.llvm_global_dce {
        llvm_args.push("--disable-llvm-global-dce".to_string());
    }
    if builder.llvm_module_cleanup {
        llvm_args.push("--llvm-module-cleanup".to_string());
    }
    if let Some(mode) = builder.llvm_cleanup {
        let mode = match mode {
            LlvmCleanup::GlobalDce => "dce",
            LlvmCleanup::InlineScalar => "inline-scalar",
            LlvmCleanup::Scalar => "scalar",
            LlvmCleanup::Inline => "inline",
        };
        llvm_args.push(format!("--llvm-cleanup={mode}"));
    }

    for (enabled, option) in [
        (!builder.nvvm_opts, NvvmOption::NoOpts),
        (builder.ftz, NvvmOption::Ftz),
        (builder.fast_sqrt, NvvmOption::FastSqrt),
        (builder.fast_div, NvvmOption::FastDiv),
        (!builder.fma_contraction, NvvmOption::NoFmaContraction),
    ] {
        if enabled {
            llvm_args.push(option.to_string());
        }
    }

    if builder.override_libm {
        llvm_args.push("--override-libm".to_string());
    }

    if builder.use_constant_memory_space {
        llvm_args.push("--use-constant-memory-space".to_string());
    }

    if let Some(path) = &builder.final_module_path {
        llvm_args.push("--final-module-path".to_string());
        llvm_args.push(path_argument(path)?.to_owned());
    }

    if builder.debug == DebugInfo::LineTables {
        llvm_args.push(NvvmOption::GenLineInfo.to_string());
        rustflags.push("-Cdebuginfo=1".into());
    }

    let llvm_args = llvm_args.join(" ");
    rustflags.push(format!("-Cllvm-args={llvm_args}"));

    Ok(rustflags)
}

fn path_argument(path: &Path) -> Result<&str, CudaBuilderError> {
    path.to_str().ok_or_else(|| {
        CudaBuilderError::InvalidOption(format!(
            "compiler argument path is not valid UTF-8: {}",
            path.display()
        ))
    })
}

pub(crate) fn encode(flags: &[String]) -> Result<String, CudaBuilderError> {
    for flag in flags {
        if flag.contains('\x1f') {
            return Err(CudaBuilderError::InvalidOption(format!(
                "rustc argument contains Cargo's unit separator: {flag:?}"
            )));
        }
    }
    Ok(flags.join("\x1f"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::NvvmArch;

    #[test]
    fn default_flags_preserve_backend_paths_with_spaces() {
        let backend = Path::new("compiler directory/backend.so");
        let builder = CudaBuilder::new("kernels", backend).arch(NvvmArch::Compute70);
        let flags = rustflags(&builder, backend).unwrap();
        assert_eq!(
            flags,
            [
                "-Zcodegen-backend=compiler directory/backend.so",
                "-Zunstable-options",
                "-Zcrate-attr=feature(register_tool)",
                "-Zcrate-attr=register_tool(nvvm_internal)",
                "-Zcrate-attr=no_std",
                "-Zsaturating_float_casts=false",
                "-Cpanic=immediate-abort",
                "-Cllvm-args=-arch=compute_70 --override-libm",
            ]
        );
        let encoded = encode(&flags).unwrap();
        assert_eq!(encoded.split('\x1f').collect::<Vec<_>>(), flags);
    }

    #[test]
    fn translates_debug_math_and_cleanup_options() {
        let backend = Path::new("backend.so");
        let builder = CudaBuilder::new("kernels", backend)
            .arch(NvvmArch::Compute100)
            .release(false)
            .ftz(true)
            .fast_sqrt(true)
            .fast_div(true)
            .fma_contraction(false)
            .override_libm(false)
            .use_constant_memory_space(true)
            .debug(DebugInfo::LineTables)
            .emit_llvm_ir(true)
            .final_module_path("final.ll")
            .llvm_global_dce(false)
            .llvm_module_cleanup(true)
            .llvm_cleanup(LlvmCleanup::InlineScalar);
        let flags = rustflags(&builder, backend).unwrap();
        assert_eq!(
            &flags[7..],
            [
                "--emit=llvm-ir",
                "-Cdebuginfo=1",
                concat!(
                    "-Cllvm-args=-arch=compute_100 --disable-llvm-global-dce ",
                    "--llvm-module-cleanup --llvm-cleanup=inline-scalar ",
                    "-opt=0 -ftz=1 -prec-sqrt=0 -prec-div=0 -fma=0 ",
                    "--use-constant-memory-space --final-module-path final.ll -generate-line-info"
                ),
            ]
        );
    }

    #[test]
    fn rejects_flags_that_would_split_into_extra_arguments() {
        assert!(matches!(
            encode(&["path\x1fextra".into()]),
            Err(CudaBuilderError::InvalidOption(_))
        ));
    }

    #[cfg(unix)]
    #[test]
    fn reports_non_utf8_paths_instead_of_panicking_or_substituting() {
        use std::{ffi::OsStr, os::unix::ffi::OsStrExt};

        let path = Path::new(OsStr::from_bytes(b"bad-\xff"));
        let builder = CudaBuilder::new("kernels", path);
        assert!(matches!(
            rustflags(&builder, path),
            Err(CudaBuilderError::InvalidOption(_))
        ));
        let builder = builder.final_module_path(path);
        assert!(matches!(
            rustflags(&builder, Path::new("backend.so")),
            Err(CudaBuilderError::InvalidOption(_))
        ));
    }
}
