use std::{error::Error, fmt, io, path::PathBuf};

#[derive(Debug)]
#[non_exhaustive]
pub enum CudaBuilderError {
    CratePathDoesntExist(PathBuf),
    FailedToCopyPtxFile(io::Error),
    BuildFailed,
    Backend(String),
    CargoInvocation(io::Error),
    InvalidOption(String),
    MissingPtxArtifact,
    MultiplePtxArtifacts(Vec<PathBuf>),
}

impl fmt::Display for CudaBuilderError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::CratePathDoesntExist(path) => {
                write!(f, "Crate directory {} does not exist", path.display())
            }
            Self::FailedToCopyPtxFile(error) => write!(f, "Failed to copy PTX file: {error}"),
            Self::BuildFailed => f.write_str("Kernel compilation failed; see Cargo diagnostics above"),
            Self::Backend(message) => write!(f, "CUDA backend: {message}"),
            Self::CargoInvocation(error) => write!(f, "Failed to execute cargo build: {error}"),
            Self::InvalidOption(message) => write!(f, "Invalid build option: {message}"),
            Self::MissingPtxArtifact => f.write_str(
                "Cargo succeeded without a PTX artifact for the final crate; check its crate-type (lib/rlib)",
            ),
            Self::MultiplePtxArtifacts(paths) => {
                write!(f, "Final crate produced multiple PTX artifacts: {paths:?}")
            }
        }
    }
}

impl Error for CudaBuilderError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::FailedToCopyPtxFile(error) | Self::CargoInvocation(error) => Some(error),
            _ => None,
        }
    }
}
