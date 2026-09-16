//! Public build configuration and fluent setters.

use std::path::{Path, PathBuf};

use crate::{CudaBuilderError, NvvmArch, backend::Backend, build};

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum DebugInfo {
    None,
    LineTables,
    // NOTE(RDambrosio016): currently unimplemented because it causes a segfault somewhere in LLVM
    // or libnvvm. Probably the latter.
    // Full,
}

/// Experimental pre-NVVM optimization. Requires the modern LLVM backend.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LlvmCleanup {
    /// Remove unreachable internal definitions without rewriting live function bodies.
    GlobalDce,
    /// Inline internal calls, then run scalar cleanup without correlated propagation.
    InlineScalar,
    Scalar,
    Inline,
}

pub enum EmitOption {
    LlvmIr,
    Bitcode,
}

/// A builder for easily compiling Rust GPU crates in build.rs
pub struct CudaBuilder {
    pub(crate) path_to_crate: PathBuf,
    pub(crate) codegen_backend: Backend,
    /// Whether to compile the gpu crate for release.
    /// `true` by default.
    pub release: bool,
    /// An optional path to copy the final ptx file to.
    pub ptx_file_copy_path: Option<PathBuf>,

    /// Whether to generate debug line number info.
    /// This defaults to `true`, but nothing will be generated
    /// if the gpu crate is built as release.
    pub generate_line_info: bool,
    /// Whether to run libnvvm optimizations. Defaults to `true`.
    /// Calling `release` also sets this to the same value.
    pub nvvm_opts: bool,
    /// The virtual compute architecture to target for PTX generation. This dictates how
    /// certain things are codegenned and may affect performance and/or which gpus the
    /// code can run on.
    ///
    /// You should generally try to pick an arch that will work with most GPUs you want
    /// your program to work with. Make sure to also use an appropriate compute arch if
    /// you are using recent features such as tensor cores (which need at least 7.x).
    ///
    /// If you are unsure, either leave this option to default, or pick something around
    /// 5.2 to 7.x.
    ///
    /// You can find a list of features supported on each arch and a list of GPUs for
    /// every arch
    /// [`here`](https://en.wikipedia.org/wiki/CUDA#Version_features_and_specifications).
    ///
    /// NOTE that this does not necessarily mean that code using a certain capability
    /// will not work on older capabilities. It means that if it uses certain features
    /// it may not work.
    ///
    /// This defaults to the default value of `NvvmArch`.
    ///
    /// Starting with CUDA 12.9, architectures can have suffixes:
    ///
    /// - **No suffix** (e.g., `Compute70`): Forward-compatible across all future GPUs.
    ///   Best for general compatibility.
    /// - **'f' suffix** (e.g., `Compute100f`): Family-specific features,
    ///   forward-compatible within same major version (10.0, 10.3, etc.) but NOT across
    ///   major versions.
    /// - **'a' suffix** (e.g., `Compute100a`): Architecture-specific features (mainly
    ///   Tensor Cores). Code ONLY runs on that exact compute capability, no
    ///   compatibility with any other GPU.
    ///
    /// Most applications should use base architectures (no suffix). Only use 'f' or 'a'
    /// if you need specific features and understand the compatibility trade-offs.
    ///
    /// The chosen architecture enables target features for conditional compilation:
    /// - Base arch: `#[cfg(target_feature = "compute_70")]` - enabled on 7.0+
    /// - Family variant: `#[cfg(target_feature = "compute_100f")]` - enabled on 10.x family
    ///   with same or higher minor version
    /// - Arch variant: `#[cfg(target_feature = "compute_100a")]` - enabled when building for
    ///   exactly 10.0 (includes all base and family features during compilation)
    ///
    /// For example, with `.arch(NvvmArch::Compute61)`:
    /// ```ignore
    /// #[cfg(target_feature = "compute_61")]
    /// {
    ///     // Code that requires compute capability 6.1+ will be emitted because it matches
    ///     // the target architecture.
    /// }
    /// #[cfg(target_feature = "compute_51")]
    /// {
    ///     // Code that requires compute capability 5.1 will be emitted
    ///     // because 6.1 is a superset of 5.1.
    /// }
    /// #[cfg(target_feature = "compute_71")]
    /// {
    ///     // Code that requires compute capability 7.1 will NOT be emitted
    ///     // because the chosen arch (6.1) is not a superset of 7.1.
    /// }
    /// ```
    ///
    /// See:
    /// <https://developer.nvidia.com/blog/nvidia-blackwell-and-nvidia-cuda-12-9-introduce-family-specific-architecture-features/>
    pub arch: NvvmArch,
    /// Flush denormal values to zero when performing single-precision floating point operations.
    /// `false` by default.
    pub ftz: bool,
    /// Use a fast approximation for single-precision floating point square root.
    /// `false` by default.
    pub fast_sqrt: bool,
    /// Use a fast approximation for single-precision floating point division.
    /// `false` by default.
    pub fast_div: bool,
    /// Enable FMA (fused multiply-add) contraction.
    /// `true` by default.
    pub fma_contraction: bool,
    /// Whether to emit a certain IR. Emitting LLVM IR is useful to debug any codegen
    /// issues. If you are submitting a bug report try to include the LLVM IR file of
    /// the program that contains the offending function.
    pub emit: Option<EmitOption>,
    /// Indicates to the codegen that the program is being compiled for use in the OptiX hardware raytracing library.
    /// This does a couple of things:
    /// - Aggressively inlines all functions.
    /// - Immediately aborts on panic, not going through the panic handler or panicking machinery.
    /// - sets the `optix` cfg.
    ///
    /// Code compiled with this option should always work under CUDA, but it might not be the most efficient or practical.
    ///
    /// `false` by default.
    pub optix: bool,
    /// Whether to override calls to [`libm`](https://docs.rs/libm/latest/libm/) with calls to libdevice intrinsics.
    ///
    /// Libm is used by no_std crates for functions such as sin, cos, fabs, etc. However, CUDA provides
    /// extremely fast GPU-specific implementations of such functions through `libdevice`. Therefore, the codegen
    /// exposes the option to automatically override any calls to libm functions with calls to libdevice functions.
    /// However, this means the overriden functions are likely to not be deterministic, so if you rely on strict
    /// determinism in things like `rapier`, then it may be helpful to disable such a feature.
    ///
    /// `true` by default.
    pub override_libm: bool,
    /// If `true`, the codegen will attempt to place `static` variables in CUDA's
    /// constant memory, which is fast but limited in size (~64KB total across all
    /// statics). The codegen avoids placing any single item too large, but it does not
    /// track cumulative size. Exceeding the limit may cause `IllegalAddress` runtime
    /// errors (CUDA error code: `700`).
    ///
    /// The default is `false`, which places all statics in global memory. This avoids
    /// such errors but may reduce performance and use more general memory. When set to
    /// `false`, you can still annotate `static` variables with
    /// `#[cuda_std::address_space(constant)]` to place them in constant memory
    /// manually. This option only affects automatic placement.
    ///
    /// Future versions may support smarter placement and user-controlled
    /// packing/spilling strategies.
    pub use_constant_memory_space: bool,
    /// Whether to generate any debug info and what level of info to generate.
    pub debug: DebugInfo,
    /// Additional arguments passed to cargo during `cargo build`.
    pub build_args: Vec<String>,
    /// An optional path where to dump LLVM IR of the final output the codegen will feed to libnvvm. Usually
    /// used for debugging.
    pub final_module_path: Option<PathBuf>,
    /// Whether the modern backend removes unreachable definitions at the merged handoff.
    pub llvm_global_dce: bool,
    /// Additional opt-in modern LLVM cleanup; disabled by default.
    pub llvm_cleanup: Option<LlvmCleanup>,
    /// Experimental scalar cleanup of each codegen unit before serialization.
    pub llvm_module_cleanup: bool,
}

impl CudaBuilder {
    /// Compile kernels with the backend dependency selected and built by Cargo.
    /// Requires the default `rustc_codegen_nvvm` feature. Enable `llvm21` to
    /// forward the modern LLVM configuration to that dependency.
    #[cfg(feature = "rustc_codegen_nvvm")]
    pub fn new(path_to_crate_root: impl AsRef<Path>) -> Self {
        Self::configured(path_to_crate_root.as_ref(), Backend::Cargo)
    }

    /// Compile a kernel crate using the specified, already-built backend dylib.
    /// Relative paths are resolved against the calling process's working directory.
    /// The backend must match the Rust toolchain and LLVM flavor used by this builder.
    pub fn with_backend(
        path_to_crate_root: impl AsRef<Path>,
        codegen_backend: impl AsRef<Path>,
    ) -> Self {
        Self::configured(
            path_to_crate_root.as_ref(),
            Backend::Explicit(codegen_backend.as_ref().to_owned()),
        )
    }

    /// Return the exact compiler dylib this builder will use, for build provenance.
    pub fn backend_path(&self) -> Result<PathBuf, CudaBuilderError> {
        crate::backend::resolve(&self.codegen_backend).map_err(CudaBuilderError::Backend)
    }

    fn configured(path_to_crate_root: &Path, codegen_backend: Backend) -> Self {
        Self {
            path_to_crate: path_to_crate_root.to_owned(),
            codegen_backend,
            release: true,
            ptx_file_copy_path: None,
            generate_line_info: true,
            nvvm_opts: true,
            arch: NvvmArch::default(),
            ftz: false,
            fast_sqrt: false,
            fast_div: false,
            fma_contraction: true,
            emit: None,
            optix: false,
            override_libm: true,
            use_constant_memory_space: false,
            debug: DebugInfo::None,
            build_args: vec![],
            final_module_path: None,
            llvm_global_dce: true,
            llvm_cleanup: None,
            llvm_module_cleanup: false,
        }
    }

    /// Enable or disable the default modern LLVM merged-module GlobalDCE pass.
    /// Disabling is intended for compiler-output comparisons; LLVM 7 is unchanged.
    pub fn llvm_global_dce(mut self, enabled: bool) -> Self {
        self.llvm_global_dce = enabled;
        self
    }

    /// Enable verified scalar cleanup before each codegen unit is serialized.
    /// Disabled by default; independent of merged-module cleanup.
    pub fn llvm_module_cleanup(mut self, enabled: bool) -> Self {
        self.llvm_module_cleanup = enabled;
        self
    }

    /// Enable a bounded modern LLVM cleanup pipeline before NVVM compilation.
    /// This is experimental; compare numerical results and generated code.
    pub fn llvm_cleanup(mut self, cleanup: LlvmCleanup) -> Self {
        self.llvm_cleanup = Some(cleanup);
        self
    }

    /// Additional arguments passed to cargo during `cargo build`.
    pub fn build_args(mut self, args: &[impl AsRef<str>]) -> Self {
        self.build_args
            .extend(args.iter().map(|s| s.as_ref().to_owned()));
        self
    }

    /// Whether to generate any debug info and what level of info to generate.
    pub fn debug(mut self, debug: DebugInfo) -> Self {
        self.debug = debug;
        self
    }

    /// Whether to compile the gpu crate for release.
    pub fn release(mut self, release: bool) -> Self {
        self.release = release;
        self.nvvm_opts = release;
        self
    }

    /// Whether to generate debug line number info.
    /// This defaults to `true`, but nothing will be generated
    /// if the gpu crate is built as release.
    pub fn generate_line_info(mut self, generate_line_info: bool) -> Self {
        self.generate_line_info = generate_line_info;
        self
    }

    /// Whether to run libnvvm optimizations. Defaults to `true`.
    /// Calling `release` also sets this to the same value.
    pub fn nvvm_opts(mut self, nvvm_opts: bool) -> Self {
        self.nvvm_opts = nvvm_opts;
        self
    }

    /// See the documentation on the `arch` field for more details.
    pub fn arch(mut self, arch: NvvmArch) -> Self {
        self.arch = arch;
        self
    }

    /// Flush denormal values to zero when performing single-precision floating point operations.
    pub fn ftz(mut self, ftz: bool) -> Self {
        self.ftz = ftz;
        self
    }

    /// Use a fast approximation for single-precision floating point square root.
    pub fn fast_sqrt(mut self, fast_sqrt: bool) -> Self {
        self.fast_sqrt = fast_sqrt;
        self
    }

    /// Use a fast approximation for single-precision floating point division.
    pub fn fast_div(mut self, fast_div: bool) -> Self {
        self.fast_div = fast_div;
        self
    }

    /// Enable FMA (fused multiply-add) contraction.
    pub fn fma_contraction(mut self, fma_contraction: bool) -> Self {
        self.fma_contraction = fma_contraction;
        self
    }

    /// Emit LLVM IR, the exact same as rustc's `--emit=llvm-ir`.
    pub fn emit_llvm_ir(mut self, emit_llvm_ir: bool) -> Self {
        self.emit = emit_llvm_ir.then_some(EmitOption::LlvmIr);
        self
    }

    /// Emit LLVM Bitcode, the exact same as rustc's `--emit=llvm-bc`.
    pub fn emit_llvm_bitcode(mut self, emit_llvm_bitcode: bool) -> Self {
        self.emit = emit_llvm_bitcode.then_some(EmitOption::Bitcode);
        self
    }

    /// Copy the final ptx file to this location once finished building.
    pub fn copy_to(mut self, path: impl AsRef<Path>) -> Self {
        self.ptx_file_copy_path = Some(path.as_ref().to_path_buf());
        self
    }

    /// Indicates to the codegen that the program is being compiled for use in the OptiX hardware raytracing library.
    /// This does a couple of things:
    /// - Aggressively inlines all functions. (not currently implemented but will be in the future)
    /// - Immediately aborts on panic, not going through the panic handler or panicking machinery.
    /// - sets the `optix` cfg.
    ///
    /// Code compiled with this option should always work under CUDA, but it might not be the most efficient or practical.
    pub fn optix(mut self, optix: bool) -> Self {
        self.optix = optix;
        self
    }

    /// Whether to override calls to [`libm`](https://docs.rs/libm/latest/libm/) with calls to libdevice intrinsics.
    ///
    /// Libm is used by no_std crates for functions such as sin, cos, fabs, etc. However, CUDA provides
    /// extremely fast GPU-specific implementations of such functions through `libdevice`. Therefore, the codegen
    /// exposes the option to automatically override any calls to libm functions with calls to libdevice functions.
    /// However, this means the overriden functions are likely to not be deterministic, so if you rely on strict
    /// determinism in things like `rapier`, then it may be helpful to disable such a feature.
    pub fn override_libm(mut self, override_libm: bool) -> Self {
        self.override_libm = override_libm;
        self
    }

    /// If `true`, the codegen will attempt to place `static` variables in CUDA's
    /// constant memory, which is fast but limited in size (~64KB total across all
    /// statics). The codegen avoids placing any single item too large, but it does not
    /// track cumulative size. Exceeding the limit may cause `IllegalAddress` runtime
    /// errors (CUDA error code: `700`).
    ///
    /// If `false`, all statics are placed in global memory. This avoids such errors but
    /// may reduce performance and use more general memory. You can still annotate
    /// `static` variables with `#[cuda_std::address_space(constant)]` to place them in
    /// constant memory manually as this option only affects automatic placement.
    ///
    /// Future versions may support smarter placement and user-controlled
    /// packing/spilling strategies.
    pub fn use_constant_memory_space(mut self, use_constant_memory_space: bool) -> Self {
        self.use_constant_memory_space = use_constant_memory_space;
        self
    }

    /// An optional path where to dump LLVM IR of the final output the codegen will feed to libnvvm. Usually
    /// used for debugging.
    pub fn final_module_path(mut self, path: impl AsRef<Path>) -> Self {
        self.final_module_path = Some(path.as_ref().to_path_buf());
        self
    }

    /// Runs rustc with the supplied backend to compile the gpu crate, returning the path of the final
    /// ptx file. If [`ptx_file_copy_path`](Self::ptx_file_copy_path) is set, this returns the copied path.
    pub fn build(self) -> Result<PathBuf, CudaBuilderError> {
        build::build(&self)
    }
}
