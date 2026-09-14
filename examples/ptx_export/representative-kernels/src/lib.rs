//! Runtime-input probes for floating point, shared memory, atomics and shuffles.
use core::{mem::MaybeUninit, sync::atomic::Ordering};
use cuda_std::{address_space, kernel, thread, warp};

/// # Safety
/// Inputs and output address `count` elements; output does not overlap inputs.
#[kernel]
pub unsafe fn wave2_float(a: *const f32, b: *const f32, out: *mut f32, count: u32) {
    let i = thread::index_1d();
    if i < count {
        *out.add(i as usize) = *a.add(i as usize) * 0.5 + *b.add(i as usize);
    }
}

/// # Safety
/// Launch exactly 32 threads per block. Buffers address `count` u32s and do not overlap.
#[kernel]
pub unsafe fn wave2_shared(input: *const u32, out: *mut u32, count: u32) {
    #[address_space(shared)]
    static mut TILE: [MaybeUninit<u32>; 32] = [MaybeUninit::uninit(); 32];
    let i = thread::index_1d();
    let lane = thread::thread_idx_x() as usize;
    let tile = core::ptr::addr_of_mut!(TILE).cast::<u32>();
    *tile.add(lane) = if i < count { *input.add(i as usize) } else { 0 };
    thread::sync_threads();
    if i < count {
        *out.add(i as usize) = *tile.add(31 - lane);
    }
}

/// # Safety
/// `counter` addresses one aligned u32 initialized before launch.
#[kernel]
pub unsafe fn wave2_atomic(counter: *mut u32, count: u32) {
    let i = thread::index_1d();
    if i < count {
        cuda_std::atomic::mid::atomic_fetch_add_u32_device(counter, Ordering::Relaxed, i + 1);
    }
}

/// # Safety
/// Launch exactly 32 threads per block. Buffers address `count` u32s and do not overlap.
/// All lanes, including tail padding, participate in the shuffle.
#[kernel]
pub unsafe fn wave2_shuffle(input: *const u32, out: *mut u32, count: u32) {
    let i = thread::index_1d();
    let value = if i < count { *input.add(i as usize) } else { 0 };
    let (other, valid) = warp::warp_shuffle_xor(u32::MAX, value, 1, 32);
    if i < count {
        *out.add(i as usize) = if valid { other } else { u32::MAX };
    }
}
