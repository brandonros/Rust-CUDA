//! PTX shuffle control encoding, shared by every shuffled value width.

#[allow(dead_code)] // GPU-only callers are replaced with stubs on the host.
#[inline(always)]
pub(crate) fn shuffle_control(width: u32, is_up: bool) -> u32 {
    assert!(
        width.is_power_of_two() && width <= 32,
        "width must be a power of 2 and less than or equal to 32"
    );
    // UP compares against a segment's lower bound. Other directions compare
    // against its upper bound. The upper bits partition the 32-lane warp.
    let clamp = if is_up { 0 } else { 31 };
    ((32 - width) << 8) | clamp
}

#[cfg(test)]
mod tests {
    extern crate std;
    use super::shuffle_control;

    #[test]
    fn control_bounds_match_logical_warp_segments() {
        for width in [1, 2, 4, 8, 16, 32] {
            for lane in 0..32_u32 {
                for is_up in [false, true] {
                    let control = shuffle_control(width, is_up);
                    // Apply the PTX ISA's maxLane expression independently.
                    let mask = (control >> 8) & 31;
                    let bound = (lane & mask) | ((control & 31) & !mask);
                    let segment_start = lane / width * width;
                    assert_eq!(
                        bound,
                        if is_up {
                            segment_start
                        } else {
                            segment_start + width - 1
                        }
                    );
                    if is_up {
                        assert_eq!(lane > bound, lane % width != 0);
                    } else {
                        assert_eq!(lane < bound, lane % width + 1 < width);
                    }
                }
            }
        }
    }

    #[test]
    fn rejects_zero_non_power_of_two_and_oversized_widths() {
        for width in [0, 3, 7, 15, 31, 33, 64, u32::MAX] {
            for is_up in [false, true] {
                assert!(std::panic::catch_unwind(|| shuffle_control(width, is_up)).is_err());
            }
        }
    }
}
