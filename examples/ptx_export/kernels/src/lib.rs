use cuda_std::prelude::*;
use sha2::{Digest, Sha256};

/// Add `count` floats. All pointers address buffers of at least `count` elements.
///
/// # Safety
/// Inputs must be readable and output writable, with no overlapping buffers.
#[kernel]
pub unsafe fn rust_vecadd(a: *const f32, b: *const f32, out: *mut f32, count: u32) {
    let i = thread::index_1d();
    if i < count {
        unsafe { *out.add(i as usize) = *a.add(i as usize) + *b.add(i as usize) };
    }
}

/// Hash `count` independent 32-byte messages into 32-byte digests.
///
/// # Safety
/// Input/output each address `count * 32` bytes and must not overlap.
#[kernel]
pub unsafe fn rust_sha256_32(input: *const u8, out: *mut u8, count: u32) {
    let i = thread::index_1d();
    if i < count {
        let offset = i as usize * 32;
        let message = unsafe { core::slice::from_raw_parts(input.add(offset), 32) };
        let digest = Sha256::digest(message);
        unsafe { core::ptr::copy_nonoverlapping(digest.as_ptr(), out.add(offset), 32) };
    }
}
