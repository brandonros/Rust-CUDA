//! Read Cargo's message stream and select the final crate's PTX output.

use std::path::PathBuf;

use serde::Deserialize;

use crate::CudaBuilderError;

#[derive(Deserialize)]
struct CargoMessage {
    reason: String,
    filenames: Option<Vec<PathBuf>>,
}

pub(crate) fn read(stdout: &[u8]) -> Result<PathBuf, CudaBuilderError> {
    read_with(stdout, |line| println!("{line}"))
}

fn read_with(stdout: &[u8], mut diagnostic: impl FnMut(&str)) -> Result<PathBuf, CudaBuilderError> {
    let mut last_artifact = None;
    // Consume the whole stream so plain-text diagnostics aren't lost before the
    // final artifact. Lossy decoding applies to diagnostics, not artifact paths.
    for line in stdout.split(|byte| *byte == b'\n') {
        if line.is_empty() {
            continue;
        }
        match serde_json::from_slice::<CargoMessage>(line) {
            Ok(message) if message.reason == "compiler-artifact" => {
                last_artifact = Some(message.filenames.unwrap_or_default());
            }
            Ok(_) => {}
            Err(_) => diagnostic(&String::from_utf8_lossy(line)),
        }
    }

    // Do not return a dependency's PTX when the final crate didn't produce one.
    let mut paths: Vec<_> = last_artifact
        .unwrap_or_default()
        .into_iter()
        .filter(|path| path.extension().is_some_and(|extension| extension == "ptx"))
        .collect();
    match paths.len() {
        0 => Err(CudaBuilderError::MissingPtxArtifact),
        1 => Ok(paths.remove(0)),
        _ => Err(CudaBuilderError::MultiplePtxArtifacts(paths)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn selects_final_artifact_and_preserves_diagnostics_in_order() {
        let output = br#"before
{"reason":"compiler-artifact","filenames":["dependency.ptx"]}
between
{"reason":"compiler-artifact","filenames":["kernel.rlib","kernel.ptx"]}
{"reason":"build-finished","success":true}
after
"#;
        let mut diagnostics = Vec::new();
        let path = read_with(output, |line| diagnostics.push(line.to_owned())).unwrap();
        assert_eq!(path, PathBuf::from("kernel.ptx"));
        assert_eq!(diagnostics, ["before", "between", "after"]);
    }

    #[test]
    fn never_falls_back_to_a_dependency_artifact() {
        let output = br#"{"reason":"compiler-artifact","filenames":["dependency.ptx"]}
{"reason":"compiler-artifact","filenames":["kernel.rlib"]}"#;
        assert!(matches!(
            read(output),
            Err(CudaBuilderError::MissingPtxArtifact)
        ));
        assert!(matches!(
            read(b""),
            Err(CudaBuilderError::MissingPtxArtifact)
        ));
    }

    #[test]
    fn reports_ambiguous_artifacts() {
        let output = br#"{"reason":"compiler-artifact","filenames":["a.ptx","b.ptx"]}"#;
        assert!(
            matches!(read(output), Err(CudaBuilderError::MultiplePtxArtifacts(paths)) if paths.len() == 2)
        );
    }

    #[test]
    fn tolerates_non_utf8_diagnostics() {
        let output =
            b"warning: \xff\n{\"reason\":\"compiler-artifact\",\"filenames\":[\"kernel.ptx\"]}";
        let mut diagnostics = Vec::new();
        assert_eq!(
            read_with(output, |line| diagnostics.push(line.to_owned())).unwrap(),
            PathBuf::from("kernel.ptx")
        );
        assert_eq!(diagnostics, ["warning: \u{fffd}"]);
    }
}
