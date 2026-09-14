#!/usr/bin/env python3
"""Check extracted integer-only LLVM helpers on the host, not on a GPU.

llvm-extract preserves their bodies and makes their linkage usable by the C
oracle. Only the target triple/data layout are changed in the host copy.
This supplements, and never substitutes for, validation of NVIDIA PTX/SASS.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ir', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--llvm-bin', type=Path)
    parser.add_argument('--cc', default='cc')
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    llvm = args.llvm_bin or Path(shutil.which('llvm-extract') or '').parent
    commands = []

    def run(command, filename):
        commands.append([str(x) for x in command])
        (out/'commands.json').write_text(json.dumps(commands, indent=2)+'\n')
        with (out/filename).open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        return (out/filename).read_text()

    version = run([llvm/'llc', '--version'], 'llvm-version.txt')
    if not re.search(r'LLVM version 21\.', version): raise RuntimeError('requires LLVM 21')
    triple = re.search(r'Default target:\s*(\S+)', version)[1]
    run([args.cc, '--version'], 'cc-version.txt')
    source = args.ir.read_text()
    symbols = {}
    for name in ('filtered', 'stepped', 'preserved', 'direct', 'observed'):
        found = re.findall(r'^define [^\n]*@([\w]+guarded_select\d+'+name+r')\(', source, re.M)
        if len(found) != 1: raise RuntimeError(f'expected one {name} definition')
        symbols[name] = found[0]
    # --recursive follows function calls, but does not retain referenced global
    # initializers. Before scalar cleanup, panic paths still reference source
    # locations. Include those globals and their transitive data dependencies
    # unchanged instead of substituting dummy definitions or dropping paths.
    globals_to_keep = set()
    while True:
        run([llvm/'llvm-extract', *['--func='+s for s in symbols.values()],
             *['--glob='+s for s in sorted(globals_to_keep)], '--recursive',
             '-S', args.ir.resolve(), '-o', out/'extracted-gpu.ll'], 'extract.log')
        extracted = (out/'extracted-gpu.ll').read_text()
        external = re.findall(r'^@("[^"\\]*"|[-\w.$]+) = external ', extracted, re.M)
        if not external:
            break
        names = {s.strip('"') for s in external}
        if names <= globals_to_keep:
            raise RuntimeError(f'host extraction contains unresolved globals: {sorted(names)}')
        globals_to_keep.update(names)
    # These five helpers use only integer arithmetic and ordinary table loads.
    # Reject a changed reproducer that acquires GPU-specific or external calls.
    declarations = re.findall(r'^declare [^\n]*@([^ (]+)\(', extracted, re.M)
    # DCE-only retains ordinary lifetime markers and assumptions that scalar
    # cleanup removes. Preserve their semantics in the host copy; these are
    # target-independent LLVM intrinsics, not GPU operations or external calls.
    allowed = {'llvm.trap', 'llvm.umin.i32', 'llvm.umin.i64', 'llvm.assume', 'llvm.expect.i1',
               'llvm.lifetime.start.p0', 'llvm.lifetime.end.p0',
               'llvm.experimental.noalias.scope.decl'}
    if any(s not in allowed for s in declarations):
        raise RuntimeError(f'host extraction contains unexpected declarations: {declarations}')
    host = re.sub(r'^target datalayout = .*$', 'target datalayout = ""', extracted, flags=re.M)
    host = re.sub(r'^target triple = .*$', f'target triple = "{triple}"', host, flags=re.M)
    (out/'host.ll').write_text(host)
    run([llvm/'opt', '-passes=verify', '-disable-output', out/'host.ll'], 'verify.log')
    # Linux's host compiler links PIE by default. Referenced source-location
    # data requires PIC relocations; this affects only the host oracle object.
    run([llvm/'llc', '-relocation-model=pic', '-filetype=obj', out/'host.ll', '-o', out/'helpers.o'], 'llc.log')
    header = []
    for name, symbol in symbols.items():
        parameters = 'const uint64_t *, uint32_t'
        if name in ('preserved', 'observed'): parameters += ', uint64_t'
        header += [f'#define {name} {symbol}', f'extern uint64_t {name}({parameters});']
    (out/'helpers.h').write_text('\n'.join(header)+'\n')
    oracle = Path(__file__).with_name('cleanup_ir_oracle.c').resolve()
    run([args.cc, '-I', out, oracle, out/'helpers.o', '-o', out/'oracle'], 'link.log')
    output = run([out/'oracle'], 'numerical.log')
    if 'HOST_IR_NUMERICAL_PASS: 1608 cases' not in output: raise RuntimeError('missing numerical result')
    result = {'input_sha256': hashlib.sha256(args.ir.read_bytes()).hexdigest(),
              'oracle_sha256': hashlib.sha256(oracle.read_bytes()).hexdigest(),
              'host_triple': triple, 'gpu_execution': False, 'result': output.strip()}
    (out/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(output, end='')


if __name__ == '__main__':
    main()
