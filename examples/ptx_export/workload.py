"""Prepare the pinned mining source without modifying the supplied checkout."""
from contextlib import contextmanager
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

MINER_COMMIT = '9791234249fc8cb762c296c4fda4503d2686ff77'


@contextmanager
def prepared_miner(source, artifacts):
    source = source.resolve()
    commit = subprocess.check_output(
        ['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if commit != MINER_COMMIT:
        raise RuntimeError('mining revision differs from the experiment pin')
    artifacts.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ptx-miner-') as directory:
        miner = Path(directory) / 'miner'
        # Read committed sources only; local edits and untracked files are not inputs.
        subprocess.run(['git', 'clone', '--quiet', '--shared', '--no-checkout',
                        str(source), str(miner)], check=True)
        subprocess.run(['git', '-C', str(miner), 'checkout', '--quiet', '--detach',
                        commit], check=True)
        manifest = miner / 'kernels/Cargo.toml'
        original = manifest.read_text()
        cuda_std = Path(__file__).resolve().parents[2] / 'crates/cuda_std'
        replacement = 'cuda_std = { path = ' + json.dumps(str(cuda_std)) + ' }'
        patched, count = re.subn(
            r'^cuda_std = \{ git = "https://github.com/brandonros/Rust-CUDA.git", rev = "2f4fd1d" \}$',
            lambda _: replacement, original, flags=re.M)
        if count != 1:
            raise RuntimeError('unexpected cuda_std dependency; review workload pin')
        (artifacts / 'Cargo.toml.original').write_text(original)
        shutil.copy2(miner / 'kernels/Cargo.lock', artifacts / 'Cargo.lock.original')
        manifest.write_text(patched)
        (artifacts / 'Cargo.toml.patched').write_text(patched)
        yield miner
