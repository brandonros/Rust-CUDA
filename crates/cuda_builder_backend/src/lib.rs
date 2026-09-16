//! Keep rustc-private linkage inside this proc macro, not in consumer build scripts.
#![feature(rustc_private)]

mod library_path;

use proc_macro::{Literal, TokenStream, TokenTree};

/// The path of the backend dylib Cargo linked into this proc macro.
#[proc_macro]
pub fn backend_path(_input: TokenStream) -> TokenStream {
    let address = std::ptr::from_ref(&rustc_codegen_nvvm::BACKEND_LIBRARY_MARKER).cast();
    let result = library_path::containing(address).and_then(|path| path.canonicalize());
    match result {
        Ok(path) => match path.to_str() {
            Some(path) => TokenTree::Literal(Literal::string(path)).into(),
            None => error("the Cargo backend path is not valid UTF-8"),
        },
        Err(err) => error(&format!(
            "cannot identify Cargo's linked CUDA backend: {err}"
        )),
    }
}

fn error(message: &str) -> TokenStream {
    format!("compile_error!({})", Literal::string(message))
        .parse()
        .expect("valid compile_error invocation")
}
