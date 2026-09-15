#!/usr/bin/env python3
"""Build one pinned workload and compare production DCE and bounded LLVM experiments."""
import argparse
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from replay_cleanup import normalized_functions

from workload import MINER_COMMIT, prepared_miner
WORKLOADS = ('solana', 'bitcoin', 'ethereum', 'shallenge', 'self_test', 'representative', 'small')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workload', choices=WORKLOADS)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--miner', type=Path)
    args = parser.parse_args()
    scripts = Path(__file__).resolve().parent
    root = args.out.resolve(); root.mkdir(parents=True, exist_ok=True)
    if args.workload not in ('representative', 'small') and args.miner is None:
        parser.error('mining workload requires a pinned checkout')
    context = prepared_miner(args.miner, root) if args.workload not in ('representative', 'small') else nullcontext(None)
    with context as miner:
        compare(args, scripts, root, miner)


def compare(args, scripts, root, miner):
    provenance = {'workload':args.workload, 'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()}
    if args.workload in ('representative', 'small'):
        kernels = scripts/('representative-kernels' if args.workload == 'representative' else 'kernels')
        extra = [str(kernels)]
        expected = set(re.findall(r'pub unsafe fn (\w+)\(', (kernels/'src/lib.rs').read_text()))
    else:
        kernels = miner/'kernels'
        provenance['mining_commit'] = MINER_COMMIT
        source_file = {'solana':'solana_vanity.rs','bitcoin':'bitcoin_vanity.rs','ethereum':'ethereum_vanity.rs','shallenge':'shallenge.rs','self_test':'self_test.rs'}[args.workload]
        expected = set(re.findall(r'pub unsafe extern "C" fn (\w+)\(', (kernels/'src'/source_file).read_text()))
        extra = [str(kernels),args.workload]
    if not expected: raise RuntimeError('no expected kernel exports identified')
    provenance['expected_entries'] = sorted(expected)
    (root/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    modules = {}
    failures = {}
    for mode in ('none','default','inline-scalar'):
        print(f'{args.workload}: building {mode}',flush=True)
        out = root/mode; out.mkdir(parents=True,exist_ok=True)
        command = ['cargo','run','-vv','-p','ptx_export','--features','llvm21','--',str(out),mode,*extra]
        (out/'compiler-command.json').write_text(json.dumps(command,indent=2)+'\n')
        with (out/'build.log').open('w') as log:
            build = subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
        if build.returncode:
            failures[mode] = build.returncode
            continue
        subprocess.run(['opt-21','-passes=verify','-disable-output',str(out/'final-module.ll')],check=True)
        print(f'{args.workload}: inspecting {mode}',flush=True)
        subprocess.run([sys.executable,str(scripts/'inspect_codegen.py'),str(out),
                        '--reuse-from',str(root/'none')],check=True)
        source = (out/'rust_kernels.ptx').read_text()
        if args.workload == 'representative':
            for direction in ('idx','up','down','bfly'):
                if 'shfl.sync.'+direction not in source:
                    raise RuntimeError(f'{mode}: missing {direction} shuffle regression coverage')
        entries = set(re.findall(r'\.entry\s+(\w+)\s*\(',source))
        if entries != expected: raise RuntimeError(f'{mode}: unexpected kernel exports: missing={expected-entries}, extra={entries-expected}')
        modules[mode] = normalized_functions(source)
    if failures:
        (root/'build-failures.json').write_text(json.dumps(failures,indent=2)+'\n')
        if args.workload == 'representative':
            for mode in failures:
                ir = root/mode/'final-module.ll'
                if ir.exists():
                    subprocess.run([sys.executable,str(scripts/'diagnose_wave2_nvvm.py'),str(ir),
                                    '--out',str(root/mode/'isolated')],check=True)
        raise RuntimeError(f'build failures (other modes were still checked): {failures}')
    if modules['default'] != modules['none']:
        raise RuntimeError('production default DCE changes baseline PTX function bodies; investigate before promotion')
    if args.workload not in ('representative','small'):
        shutil.copy2(kernels/'Cargo.lock',root/'Cargo.lock.resolved')
    command = [sys.executable,str(scripts/'replay_cleanup.py'),str(root/'none'),'--wave2']
    if args.workload not in ('solana','small'):
        command += ['--only','baseline,dce-only,inline-only']
    subprocess.run(command,check=True)
    replay = root/'none/cleanup-experiment/inline-only/rust_kernels.ptx'
    if normalized_functions(replay.read_text()) != modules['inline-scalar']:
        raise RuntimeError('integrated InlineScalar differs from independent replay')
    result = {'workload':args.workload,'expected_entry_count':len(expected),'default_matches_disabled_ptx':True,
              'inline_scalar_matches_replay':True,'nvidia_execution':False,
              'ptx_sha256':{m:hashlib.sha256((root/m/'rust_kernels.ptx').read_bytes()).hexdigest() for m in modules}}
    (root/'comparison.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)


if __name__ == '__main__':
    main()
