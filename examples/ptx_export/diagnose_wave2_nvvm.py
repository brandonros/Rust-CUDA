#!/usr/bin/env python3
"""Isolate representative entry points without suppressing NVVM verification.

Run each NVIDIA invocation in a child process so a verifier crash does not
prevent retaining evidence for the remaining kernels. No production IR changes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from replay_cleanup import compile_nvvm


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ir', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--worker', action='store_true')
    args = parser.parse_args()
    candidates = list(Path('target/cuda-builder-codegen').rglob('libintrinsics_v21.bc'))
    unique = {hashlib.sha256(p.read_bytes()).hexdigest():p for p in candidates}
    if len(unique) != 1: raise RuntimeError('expected one distinct LLVM 21 intrinsic library')
    libraries = [Path(os.environ['CUDA_HOME'])/'nvvm/libdevice/libdevice.10.bc',next(iter(unique.values()))]
    if args.worker:
        compile_nvvm(args.ir,libraries,args.out)
        return
    args.out.mkdir(parents=True,exist_ok=True)
    llvm_bin = Path(subprocess.check_output([os.environ['LLVM_CONFIG_21'],'--bindir'],text=True).strip())
    report = {'input_sha256':hashlib.sha256(args.ir.read_bytes()).hexdigest(),
              'libraries':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in libraries},'kernels':{}}
    for kernel in ('wave2_float','wave2_shared','wave2_atomic','wave2_shuffle'):
        out = args.out/kernel;out.mkdir(exist_ok=True)
        globals_to_keep = set()
        commands = []
        while True:
            command = [str(llvm_bin/'llvm-extract'),'--recursive','--func='+kernel,
                       *['--glob='+s for s in sorted(globals_to_keep)],'-S',str(args.ir),'-o',str(out/'extracted.ll')]
            commands.append(command);subprocess.run(command,check=True)
            source = (out/'extracted.ll').read_text()
            names = {s.strip('"') for s in re.findall(r'^@("[^"\\]*"|[-\w.$]+) = external (?:addrspace\(\d+\) )?',source,re.M)}
            if not names: break
            if names <= globals_to_keep: raise RuntimeError(f'unresolved globals: {names}')
            globals_to_keep.update(names)
        command = ['opt-21','-passes=verify',str(out/'extracted.ll'),'-o',str(out/'module.bc')]
        commands.append(command);subprocess.run(command,check=True)
        command = [sys.executable,str(Path(__file__).resolve()),str(out/'module.bc'),'--out',str(out),'--worker']
        commands.append(command)
        with (out/'nvvm.log').open('w') as log:
            result = subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
        (out/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        report['kernels'][kernel] = {'exit_code':result.returncode,'compiled':result.returncode==0,
                                    'ir_sha256':hashlib.sha256((out/'extracted.ll').read_bytes()).hexdigest()}
        (args.out/'diagnosis.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__ == '__main__':
    main()
