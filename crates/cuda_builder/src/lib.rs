//! Utility crate for easily building CUDA crates using rustc_codegen_nvvm. Derived from rust-gpu's spirv_builder.
//!
//! Build or install `rustc_codegen_nvvm` separately, then pass its dylib path to
//! [`CudaBuilder::new`]. This crate only builds kernels; it never discovers,
//! downloads, or builds the compiler backend.

mod artifact;
mod backend;
mod build;
mod builder;
mod error;
mod flags;

pub use builder::{CudaBuilder, DebugInfo, EmitOption, LlvmCleanup};
pub use error::CudaBuilderError;
pub use nvvm::*;
