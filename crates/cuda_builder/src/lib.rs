//! Utility crate for easily building CUDA crates using rustc_codegen_nvvm. Derived from rust-gpu's spirv_builder.
//!
//! With the default `rustc_codegen_nvvm` feature, Cargo builds the backend as a
//! dependency and `CudaBuilder::new` uses that exact artifact. The `llvm21`
//! feature forwards to the backend and selects matching compiler options.
//! Use [`CudaBuilder::with_backend`] for an explicitly supplied compiler.
//! Neither path scans for backend files or starts a nested backend build.

mod artifact;
mod backend;
mod build;
mod builder;
mod error;
mod flags;

pub use builder::{CudaBuilder, DebugInfo, EmitOption, LlvmCleanup};
pub use error::CudaBuilderError;
pub use nvvm::*;
