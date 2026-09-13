#!/usr/bin/env python3
"""Compile through the real backend and compare against the offline pass replay."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from replay_cleanup import normalized_functions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifacts', type=Path)
    args = parser.parse_args()
    root = args.artifacts.resolve()
    results = []
    for mode, replay in [('scalar', 'local-cleanup'), ('inline', 'inline-cleanup')]:
        dest = root/'integrated-cleanup'/mode
        dest.mkdir(parents=True, exist_ok=True)
        command = ['cargo', 'run', '-vv', '-p', 'ptx_export', '--features', 'llvm19', '--', str(dest), mode]
        (dest/'compiler-command.json').write_text(json.dumps(command, indent=2)+'\n')
        with (dest/'build.log').open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run(['opt-19', '-passes=verify', '-disable-output', str(dest/'final-module.ll')], check=True)
        before = dest/'final-module.before-cleanup.ll'
        if not before.is_file(): raise RuntimeError('backend did not record the pre-cleanup IR')
        actual = normalized_functions((dest/'rust_kernels.ptx').read_text())
        expected = normalized_functions((root/'cleanup-experiment'/replay/'rust_kernels.ptx').read_text())
        matches = actual == expected
        results.append({'mode': mode, 'matches_replay_function_bodies': matches})
        (root/'integrated-cleanup'/'comparison.json').write_text(json.dumps(results, indent=2)+'\n')
        if not matches: raise RuntimeError(f'{mode}: integrated cleanup differs from replay')
        subprocess.run([sys.executable, str(Path(__file__).with_name('inspect_codegen.py')), str(dest)], check=True)
        print(f'{mode}: real backend matches replay; LLVM verified and PTX assembled', flush=True)


if __name__ == '__main__':
    main()
