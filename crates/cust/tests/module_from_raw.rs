//! Exercise raw-handle ownership without requiring a GPU. This test executable
//! supplies the unload entry point in place of the CUDA driver.

use cust::module::Module;
use cust_raw::driver_sys::{CUmodule, CUresult, cudaError_enum};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};

static UNLOADS: AtomicUsize = AtomicUsize::new(0);
static FAIL_UNLOAD: AtomicBool = AtomicBool::new(false);

#[unsafe(no_mangle)]
unsafe extern "C" fn cuModuleUnload(module: CUmodule) -> CUresult {
    assert_eq!(module, std::ptr::dangling_mut());
    UNLOADS.fetch_add(1, Ordering::SeqCst);
    if FAIL_UNLOAD.load(Ordering::SeqCst) {
        cudaError_enum::CUDA_ERROR_INVALID_CONTEXT
    } else {
        cudaError_enum::CUDA_SUCCESS
    }
}

#[test]
fn adopted_module_owns_cleanup_and_survives_failed_explicit_drop() {
    // SAFETY: the mock driver recognizes this handle and no other owner exists.
    let module = unsafe { Module::from_raw(std::ptr::dangling_mut()) };
    assert_eq!(module.as_inner(), std::ptr::dangling_mut());
    assert_eq!(UNLOADS.load(Ordering::SeqCst), 0);
    drop(module);
    assert_eq!(UNLOADS.load(Ordering::SeqCst), 1);

    // SAFETY: begin a new lifetime for the mock driver's handle.
    let module = unsafe { Module::from_raw(std::ptr::dangling_mut()) };
    FAIL_UNLOAD.store(true, Ordering::SeqCst);
    let (_, module) = Module::drop(module).expect_err("mock unload should fail");
    assert_eq!(module.as_inner(), std::ptr::dangling_mut());
    assert_eq!(UNLOADS.load(Ordering::SeqCst), 2);
    FAIL_UNLOAD.store(false, Ordering::SeqCst);
    drop(module);
    assert_eq!(UNLOADS.load(Ordering::SeqCst), 3);
}
