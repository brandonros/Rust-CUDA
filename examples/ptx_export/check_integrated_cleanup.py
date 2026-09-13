#!/usr/bin/env python3
"""Compile through the real backend and compare against the offline pass replay."""
import argparse
import json
import re
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
    for mode, replay in [('inline-scalar', 'inline-only'), ('dce', 'dce-only'), ('scalar', 'local-cleanup'), ('inline', 'inline-cleanup')]:
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
        required = {'rust_vecadd', 'rust_sha256_32', 'rust_guarded_select', 'rust_filtered_select'}
        if not required <= actual.keys(): raise RuntimeError('cleanup removed an exported kernel')
        result = {'mode': mode, 'matches_replay_function_bodies': matches}
        if mode == 'dce':
            baseline = normalized_functions((root/'rust_kernels.ptx').read_text())
            if actual != baseline:
                raise RuntimeError('DCE-only changed baseline PTX function bodies')
            before_count = len(re.findall(r'^define ', before.read_text(), re.M))
            after_count = len(re.findall(r'^define ', (dest/'final-module.ll').read_text(), re.M))
            if not 0 < after_count < before_count:
                raise RuntimeError('DCE-only did not prune unused definitions')
            result['definitions_before_after'] = [before_count, after_count]
        if mode == 'inline':
            # Check the real compiler output, not a hand-written substitute.
            # The negative control must still carry its observable dependency.
            ir = (dest/'final-module.ll').read_text()
            counts = {}
            for helper in ('filtered', 'observed'):
                bodies = re.findall(r'^define [^\n]*guarded_select\d+' + helper +
                                    r'\([^\n]*\{\n(.*?)^}', ir, re.M | re.S)
                if len(bodies) != 1: raise RuntimeError(f'expected one {helper} IR definition')
                counts[helper] = len(re.findall(r'= select ', bodies[0]))
            result['ir_select_counts'] = counts
            if counts != {'filtered': 0, 'observed': 1}:
                raise RuntimeError(f'guarded-select cleanup regression: {counts}')
        results.append(result)
        (root/'integrated-cleanup'/'comparison.json').write_text(json.dumps(results, indent=2)+'\n')
        if not matches: raise RuntimeError(f'{mode}: integrated cleanup differs from replay')
        subprocess.run([sys.executable, str(Path(__file__).with_name('inspect_codegen.py')), str(dest)], check=True)
        if mode in ('dce', 'inline', 'inline-scalar'):
            subprocess.run([sys.executable, str(Path(__file__).with_name('check_cleanup_ir.py')),
                            str(dest/'final-module.ll'), '--out', str(dest/'host-ir-check')], check=True)
        print(f'{mode}: real backend matches replay; LLVM verified and PTX assembled', flush=True)


if __name__ == '__main__':
    main()
