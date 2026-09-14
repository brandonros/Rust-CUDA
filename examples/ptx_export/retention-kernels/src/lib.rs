//! Exercise actual Rust-CUDA internalization and DCE root discovery.
#![feature(used_with_arg)]

use cuda_std::{externally_visible, kernel};

type Callback = extern "C" fn(u32) -> u32;

#[no_mangle]
#[inline(never)]
pub extern "C" fn retention_table_target(x: u32) -> u32 {
    x.wrapping_mul(7)
}

#[no_mangle]
#[inline(never)]
pub extern "C" fn retention_used_target(x: u32) -> u32 {
    x.wrapping_add(19)
}

#[no_mangle]
#[inline(never)]
pub extern "C" fn retention_linker_target(x: u32) -> u32 {
    x.wrapping_sub(13)
}

#[used(linker)]
#[no_mangle]
pub static RETENTION_LINKER_USED: [Callback; 1] = [retention_linker_target];

#[externally_visible]
#[no_mangle]
pub extern "C" fn retention_external(x: u32) -> u32 {
    x ^ 0x5a5a_5a5a
}

#[no_mangle]
pub static RETENTION_TABLE: [Callback; 1] = [retention_table_target];

// Never read by a kernel. Its initializer must nevertheless retain its target.
#[used(compiler)]
#[no_mangle]
pub static RETENTION_USED: [Callback; 1] = [retention_used_target];

#[no_mangle]
pub static RETENTION_DATA: [u32; 3] = [11, 29, 47];

#[no_mangle]
pub static RETENTION_DATA_REF: &'static [u32; 3] = &RETENTION_DATA;

// Emitted as externally named items, then internalized and eligible for DCE.
#[no_mangle]
pub extern "C" fn retention_unreachable(x: u32) -> u32 {
    x.wrapping_add(23)
}

#[no_mangle]
pub static RETENTION_UNREACHABLE_DATA: [u32; 3] = [101, 103, 107];

/// # Safety
/// `out` addresses three writable u64s. No inputs overlap the output.
#[kernel]
pub unsafe fn retention_probe(out: *mut u64, index: u32) {
    // Volatile reads keep the initializer dependencies visible in the emitted IR.
    let callback =
        core::ptr::read_volatile(core::ptr::addr_of!(RETENTION_TABLE).cast::<Callback>());
    let data = core::ptr::read_volatile(core::ptr::addr_of!(RETENTION_DATA_REF));
    *out = callback as usize as u64;
    *out.add(1) = core::ptr::read_volatile(data.as_ptr().add((index % 3) as usize)) as u64;
    *out.add(2) = retention_external(index) as u64;
}
