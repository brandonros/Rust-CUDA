use std::{ffi::c_void, io, path::PathBuf};

/// Query the loader for the library containing a static in the linked backend.
/// No library names or directories are searched.
#[cfg(unix)]
pub(super) fn containing(address: *const c_void) -> io::Result<PathBuf> {
    use std::{
        ffi::{CStr, OsStr},
        mem::MaybeUninit,
        os::unix::ffi::OsStrExt,
    };

    let mut info = MaybeUninit::<libc::Dl_info>::uninit();
    // SAFETY: dladdr inspects the address, and initializes info on success.
    // The backend is a linked dependency and stays loaded while this runs.
    // https://man7.org/linux/man-pages/man3/dladdr.3.html
    if unsafe { libc::dladdr(address, info.as_mut_ptr()) } == 0 {
        return Err(io::Error::other(
            "dladdr could not identify the backend library",
        ));
    }
    // SAFETY: dladdr succeeded; its non-null filename is a loader-owned C string.
    let info = unsafe { info.assume_init() };
    if info.dli_fname.is_null() {
        return Err(io::Error::other("dladdr returned no backend filename"));
    }
    let name = unsafe { CStr::from_ptr(info.dli_fname) };
    Ok(PathBuf::from(OsStr::from_bytes(name.to_bytes())))
}

#[cfg(windows)]
pub(super) fn containing(address: *const c_void) -> io::Result<PathBuf> {
    use std::{ffi::OsString, os::windows::ffi::OsStringExt};

    #[link(name = "kernel32")]
    unsafe extern "system" {
        fn GetModuleHandleExW(flags: u32, address: *const u16, module: *mut *mut c_void) -> i32;
        fn GetModuleFileNameW(module: *mut c_void, filename: *mut u16, size: u32) -> u32;
    }
    const FROM_ADDRESS: u32 = 0x00000004;
    const UNCHANGED_REFCOUNT: u32 = 0x00000002;
    let mut module = std::ptr::null_mut();
    // SAFETY: FROM_ADDRESS treats the pointer as an address, not a string.
    // This link-time dependency cannot unload during the query. The
    // borrowed module handle must not be passed to FreeLibrary.
    // https://learn.microsoft.com/windows/win32/api/libloaderapi/nf-libloaderapi-getmodulehandleexw
    if unsafe {
        GetModuleHandleExW(
            FROM_ADDRESS | UNCHANGED_REFCOUNT,
            address.cast(),
            &mut module,
        )
    } == 0
    {
        return Err(io::Error::last_os_error());
    }
    let mut name = vec![0; 256];
    loop {
        // SAFETY: name has space for exactly the number of UTF-16 units passed.
        let len =
            unsafe { GetModuleFileNameW(module, name.as_mut_ptr(), name.len() as u32) } as usize;
        if len == 0 {
            return Err(io::Error::last_os_error());
        }
        if len < name.len() {
            return Ok(PathBuf::from(OsString::from_wide(&name[..len])));
        }
        // A result equal to the buffer size means truncation, not success.
        // https://learn.microsoft.com/windows/win32/api/libloaderapi/nf-libloaderapi-getmodulefilenamew
        if name.len() >= 32768 {
            return Err(io::Error::other(
                "backend library path exceeds Windows path limit",
            ));
        }
        name.resize(name.len() * 2, 0);
    }
}

#[cfg(not(any(unix, windows)))]
pub(super) fn containing(_address: *const c_void) -> io::Result<PathBuf> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "unsupported backend host platform",
    ))
}
