#!/usr/bin/env python3
"""Validate default GlobalDCE through Rust codegen, internalization and NVVM."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from replay_cleanup import normalized_functions


def definitions(ir):
    return set(re.findall(r'^define [^\n]*@([\w.$]+)\(', ir, re.M))


def globals_defined(ir):
    return {name: body for name, body in re.findall(r'^@([\w.$]+) = ([^\n]+)', ir, re.M)
            if not body.startswith('external ')}


def check_retention(before, after):
    live_functions = {'retention_probe', 'retention_external', 'retention_table_target', 'retention_used_target', 'retention_linker_target'}
    live_globals = {'RETENTION_TABLE', 'RETENTION_USED', 'RETENTION_DATA', 'RETENTION_DATA_REF', 'RETENTION_LINKER_USED'}
    for phase, ir in [('before', before), ('after', after)]:
        if not live_functions <= definitions(ir):
            raise RuntimeError(f'{phase}: missing retained functions: {live_functions - definitions(ir)}')
        if not live_globals <= globals_defined(ir).keys():
            raise RuntimeError(f'{phase}: missing retained initialized data')
    for symbol in live_globals:
        if globals_defined(before)[symbol] != globals_defined(after)[symbol]:
            raise RuntimeError(f'GlobalDCE changed initializer/linkage: {symbol}')
    if 'retention_unreachable' not in definitions(before) or 'RETENTION_UNREACHABLE_DATA' not in globals_defined(before):
        raise RuntimeError('negative controls were not emitted before GlobalDCE')
    if 'retention_unreachable' in definitions(after) or 'RETENTION_UNREACHABLE_DATA' in globals_defined(after):
        raise RuntimeError('default GlobalDCE did not remove unreachable controls')
    for used in ('llvm.used', 'llvm.compiler.used'):
        if not re.search(r'^@'+re.escape(used)+r' = appending ', after, re.M):
            raise RuntimeError(f'missing appending-linkage {used}')
    if not re.search(r'^define (?!internal\b)[^\n]*@retention_external\(', after, re.M):
        raise RuntimeError('explicit external function was internalized')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifacts', type=Path)
    args = parser.parse_args()
    root = args.artifacts.resolve()/'default-dce'
    scripts = Path(__file__).resolve().parent
    root.mkdir(parents=True, exist_ok=True)
    results = []
    for fixture, extra in [('small', []), ('retention', [str(scripts/'retention-kernels')])]:
        modules = {}
        for mode in ('none', 'default'):
            out = root/fixture/mode; out.mkdir(parents=True, exist_ok=True)
            command = ['cargo', 'run', '-vv', '-p', 'ptx_export', '--features', 'llvm21', '--', str(out), mode, *extra]
            (out/'compiler-command.json').write_text(json.dumps(command, indent=2)+'\n')
            with (out/'build.log').open('w') as log:
                subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
            subprocess.run(['opt-21', '-passes=verify', '-disable-output', str(out/'final-module.ll')], check=True)
            subprocess.run([sys.executable, str(scripts/'inspect_codegen.py'), str(out)], check=True)
            modules[mode] = out
        raw = (modules['none']/'final-module.ll').read_text()
        default = (modules['default']/'final-module.ll').read_text()
        before = (modules['default']/'final-module.before-cleanup.ll').read_text()
        if not len(definitions(default)) < len(definitions(raw)):
            raise RuntimeError('default did not prune definitions relative to explicit disable')
        for left, right in [(modules['none'], modules['default'])]:
            if normalized_functions((left/'rust_kernels.ptx').read_text()) != normalized_functions((right/'rust_kernels.ptx').read_text()):
                raise RuntimeError(f'{fixture}: default changes baseline PTX function bodies')
        if fixture == 'retention':
            check_retention(before, default)
        else:
            subprocess.run([sys.executable, str(scripts/'check_cleanup_ir.py'), str(modules['default']/'final-module.ll'),
                            '--out', str(modules['default']/'host-ir-check')], check=True)
        results.append({'fixture':fixture, 'definitions_before_after':[len(definitions(raw)), len(definitions(default))],
                        'matches_disabled_ptx_function_bodies':True,
                        'ptx_sha256':{m:hashlib.sha256((p/'rust_kernels.ptx').read_bytes()).hexdigest() for m,p in modules.items()}})
        (root/'comparison.json').write_text(json.dumps(results, indent=2)+'\n')
        print(f'{fixture}: default GlobalDCE verified against explicit disable', flush=True)


if __name__ == '__main__':
    main()
