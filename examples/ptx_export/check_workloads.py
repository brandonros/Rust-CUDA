#!/usr/bin/env python3
"""Build size-oriented reproducers or pinned, unmodified Solana kernel sources."""
import argparse
from contextlib import nullcontext
import json
from pathlib import Path
import shutil
import subprocess
import sys
from replay_cleanup import normalized_functions
from workload import MINER_COMMIT, prepared_miner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifacts', type=Path)
    parser.add_argument('--miner', type=Path)
    args = parser.parse_args()
    root = args.artifacts.resolve()
    scripts = Path(__file__).resolve().parent
    context = prepared_miner(args.miner, root/'mining-solana') if args.miner else nullcontext(None)
    with context as miner:
        compare(args, root, scripts, miner)


def compare(args, root, scripts, miner):
    if args.miner:
        out = root/'mining-solana'
        (out/'workload.json').write_text(json.dumps({'repository':'brandonros/vanity-miner-rs', 'commit':MINER_COMMIT,
            'features':['solana'], 'source_change':'cuda_std dependency path only; algorithm source unchanged'}, indent=2)+'\n')
        builds = [('none', out, [str(miner/'kernels'), 'solana'])]
    else:
        builds = [(mode, root/'size-builds'/mode, []) for mode in ('size-s', 'size-z')]
    for mode, out, extra in builds:
        out.mkdir(parents=True, exist_ok=True)
        command = ['cargo', 'run', '-vv', '-p', 'ptx_export', '--features', 'llvm21', '--', str(out), mode, *extra]
        (out/'compiler-command.json').write_text(json.dumps(command, indent=2)+'\n')
        with (out/'build.log').open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run(['opt-21', '-passes=verify', '-disable-output', str(out/'final-module.ll')], check=True)
        subprocess.run([sys.executable, str(scripts/'inspect_codegen.py'), str(out)], check=True)
        if not args.miner:
            subprocess.run([sys.executable, str(scripts/'check_cleanup_ir.py'), str(out/'final-module.ll'),
                            '--out', str(out/'host-ir-check')], check=True)
    if args.miner:
        shutil.copy2(miner/'kernels/Cargo.lock', out/'Cargo.lock.resolved')
        subprocess.run([sys.executable, str(scripts/'replay_cleanup.py'), str(out), '--extended', '--only',
                        'baseline,dce-only,inline-only,inline-cleanup,memory-early-cse,memory-gvn,memory-stores,memory-combined'], check=True)
        results = []
        for mode, replay in [('dce', 'dce-only'), ('inline-scalar', 'inline-only')]:
            dest = out/'integrated-cleanup'/mode
            dest.mkdir(parents=True, exist_ok=True)
            command = ['cargo', 'run', '-vv', '-p', 'ptx_export', '--features', 'llvm21', '--',
                       str(dest), mode, str(miner/'kernels'), 'solana']
            (dest/'compiler-command.json').write_text(json.dumps(command, indent=2)+'\n')
            with (dest/'build.log').open('w') as log:
                subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
            subprocess.run(['opt-21', '-passes=verify', '-disable-output', str(dest/'final-module.ll')], check=True)
            actual = normalized_functions((dest/'rust_kernels.ptx').read_text())
            expected = normalized_functions((out/'cleanup-experiment'/replay/'rust_kernels.ptx').read_text())
            if 'kernel_find_solana_vanity_private_key' not in actual or actual != expected:
                raise RuntimeError(f'Solana {mode}: integrated cleanup differs from replay')
            subprocess.run([sys.executable, str(scripts/'inspect_codegen.py'), str(dest)], check=True)
            results.append({'mode':mode, 'matches_replay_function_bodies':True})
            (out/'integrated-cleanup/comparison.json').write_text(json.dumps(results, indent=2)+'\n')


if __name__ == '__main__':
    main()
