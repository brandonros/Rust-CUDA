//! Defined Rust source for investigating loop-carried conditional selection.
//! All initial values and table contents come from the caller; no uninitialized
//! Rust memory or compiler-specific assembly is used.

#[inline(never)]
pub fn preserved(table: &[u64; 64], limit: u32, initial: u64) -> u64 {
    let mut remembered = initial;
    let mut sum = 0u64;
    for i in 0..limit.min(64) {
        let odd = i & 1 != 0;
        if odd {
            remembered = u64::from(i);
        }
        if odd {
            sum = sum.wrapping_add(table[(remembered & 63) as usize]);
        }
    }
    sum
}

#[inline(never)]
pub fn direct(table: &[u64; 64], limit: u32) -> u64 {
    let mut sum = 0u64;
    for i in 0..limit.min(64) {
        if i & 1 != 0 {
            sum = sum.wrapping_add(table[i as usize]);
        }
    }
    sum
}

/// Negative control: the false-path value is observed, including at i=0.
/// Replacing the conditional assignment with `remembered = i` is incorrect.
#[inline(never)]
pub fn observed(table: &[u64; 64], limit: u32, initial: u64) -> u64 {
    let mut remembered = initial;
    let mut sum = 0u64;
    for i in 0..limit.min(64) {
        if i & 1 != 0 {
            remembered = u64::from(i);
        }
        sum = sum.wrapping_add(table[(remembered & 63) as usize]);
    }
    sum
}

/// Preserve Dalek's filtered-range idiom; strip curve arithmetic first.
#[inline(never)]
pub fn filtered(table: &[u64; 64], limit: u32) -> u64 {
    let mut sum = 0u64;
    for i in (0..limit.min(64) as usize).filter(|x| x % 2 == 1) {
        sum = sum.wrapping_add(table[i]);
    }
    sum
}

/// Same odd-index accesses, without Filter::next's retained result.
#[inline(never)]
pub fn stepped(table: &[u64; 64], limit: u32) -> u64 {
    let mut sum = 0u64;
    for i in (1..limit.min(64) as usize).step_by(2) {
        sum = sum.wrapping_add(table[i]);
    }
    sum
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn compare_against_independent_index_oracle() {
        for seed in [0u64, 1, 0x8000_0000_0000_0000, u64::MAX] {
            let table = core::array::from_fn(|i| {
                (i as u64)
                    .wrapping_mul(0x9e37_79b9_7f4a_7c15)
                    .wrapping_add(seed)
            });
            for limit in (0..=65).chain([u32::MAX]) {
                for initial in [0u64, 1, 17, 63, 64, u64::MAX] {
                    let n = limit.min(64) as usize;
                    let expected = (1..n)
                        .step_by(2)
                        .fold(0u64, |sum, i| sum.wrapping_add(table[i]));
                    // Last odd index <= i; on the first iteration use initial.
                    let observed_expected = (0..n).fold(0u64, |sum, i| {
                        let index = if i == 0 {
                            (initial & 63) as usize
                        } else {
                            (i - 1) | 1
                        };
                        sum.wrapping_add(table[index])
                    });
                    assert_eq!(preserved(&table, limit, initial), expected);
                    assert_eq!(direct(&table, limit), expected);
                    assert_eq!(filtered(&table, limit), expected);
                    assert_eq!(stepped(&table, limit), expected);
                    assert_eq!(observed(&table, limit, initial), observed_expected);
                }
            }
        }
    }

    #[test]
    fn control_detects_discarding_a_live_false_arm() {
        let table = core::array::from_fn(|i| i as u64);
        assert_eq!(preserved(&table, 1, 17), 0);
        assert_eq!(direct(&table, 1), 0);
        assert_eq!(observed(&table, 1, 17), 17);
        assert_ne!(observed(&table, 1, 17), table[0]);
    }
}
