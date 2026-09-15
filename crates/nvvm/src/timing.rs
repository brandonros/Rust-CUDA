//! Opt-in, live compiler phase logs. One file per rustc process avoids contention
//! between Cargo jobs. No tracing subscriber or additional dependency is needed.
use std::{
    fs::{self, File, OpenOptions},
    io::Write,
    sync::{Mutex, OnceLock},
    time::{Instant, SystemTime, UNIX_EPOCH},
};

struct Log {
    file: Mutex<File>,
    epoch: Instant,
}

impl Log {
    fn record(&self, event: &str, stage: &str, detail: &str, elapsed: f64) {
        // File is unbuffered: each record is visible to tail immediately. Logging
        // failures must not turn a successful compilation into a failed build.
        if let Ok(mut file) = self.file.lock() {
            let _ = writeln!(
                file,
                "unix_ms={} at_ms={:.3} pid={} thread={:?} event={} stage={:?} detail={:?} elapsed_ms={:.3}",
                SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_millis(),
                self.epoch.elapsed().as_secs_f64() * 1000.0,
                std::process::id(),
                std::thread::current().id(),
                event,
                stage,
                detail,
                elapsed
            );
        }
    }
}

fn log() -> Option<&'static Log> {
    static LOG: OnceLock<Option<Log>> = OnceLock::new();
    LOG.get_or_init(|| {
        let directory = std::env::var_os("NVVM_TIMING_DIR")?;
        let path = std::path::PathBuf::from(directory)
            .join(format!("rust-cuda-{}.log", std::process::id()));
        let result = (|| {
            fs::create_dir_all(path.parent().unwrap())?;
            OpenOptions::new().create(true).append(true).open(&path)
        })();
        match result {
            Ok(file) => {
                eprintln!("Rust-CUDA timing log: {}", path.display());
                Some(Log {
                    file: Mutex::new(file),
                    epoch: Instant::now(),
                })
            }
            Err(error) => {
                eprintln!(
                    "Could not create Rust-CUDA timing log {}: {error}",
                    path.display()
                );
                None
            }
        }
    })
    .as_ref()
}

/// A phase emits its end record on drop, including during panic unwinding.
pub struct Phase(Option<Active>);

struct Active {
    log: &'static Log,
    stage: &'static str,
    detail: String,
    start: Instant,
}

/// Start a phase when `NVVM_TIMING_DIR` is set; otherwise this is inert.
pub fn phase(stage: &'static str, detail: &str) -> Phase {
    Phase(log().map(|log| {
        log.record("begin", stage, detail, 0.0);
        Active {
            log,
            stage,
            detail: detail.to_owned(),
            start: Instant::now(),
        }
    }))
}

impl Drop for Phase {
    fn drop(&mut self) {
        if let Some(active) = &self.0 {
            active.log.record(
                if std::thread::panicking() {
                    "unwind"
                } else {
                    "end"
                },
                active.stage,
                &active.detail,
                active.start.elapsed().as_secs_f64() * 1000.0,
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn records_are_visible_before_phase_ends() {
        let path =
            std::env::temp_dir().join(format!("nvvm-timing-test-{}.log", std::process::id()));
        let log = Box::leak(Box::new(Log {
            file: Mutex::new(File::create(&path).unwrap()),
            epoch: Instant::now(),
        }));
        log.record("begin", "test", "module\nname", 0.0);
        let scope = Phase(Some(Active {
            log,
            stage: "test",
            detail: "module\nname".into(),
            start: Instant::now(),
        }));
        let before = fs::read_to_string(&path).unwrap();
        assert_eq!(before.lines().count(), 1);
        assert!(before.contains("event=begin"));
        assert!(!before.contains("event=end"));
        drop(scope);
        let after = fs::read_to_string(&path).unwrap();
        assert_eq!(after.lines().count(), 2);
        assert!(after.contains("event=end"));
        assert!(after.contains("elapsed_ms="));
        fs::remove_file(path).unwrap();
    }
}
