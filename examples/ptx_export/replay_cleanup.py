#!/usr/bin/env python3
"""Opt-in pre-NVVM cleanup experiment; never changes Rust-CUDA defaults."""
import argparse
import ctypes as c
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from optimization_pipelines import experiments, wave2_experiments
from inspect_codegen import ptx_functions, ptx_summary


def compile_nvvm(bitcode, libraries, output):
    lib = c.CDLL('libnvvm.so')
    ptr = c.c_void_p
    signatures = {
        'nvvmCreateProgram': [c.POINTER(ptr)], 'nvvmDestroyProgram': [c.POINTER(ptr)],
        'nvvmAddModuleToProgram': [ptr, ptr, c.c_size_t, c.c_char_p],
        'nvvmLazyAddModuleToProgram': [ptr, ptr, c.c_size_t, c.c_char_p],
        'nvvmCompileProgram': [ptr, c.c_int, c.POINTER(c.c_char_p)],
        'nvvmVerifyProgram': [ptr, c.c_int, c.POINTER(c.c_char_p)],
        'nvvmGetProgramLogSize': [ptr, c.POINTER(c.c_size_t)],
        'nvvmGetProgramLog': [ptr, ptr],
        'nvvmGetCompiledResultSize': [ptr, c.POINTER(c.c_size_t)],
        'nvvmGetCompiledResult': [ptr, ptr],
    }
    for name, types in signatures.items():
        fn = getattr(lib, name); fn.argtypes = types; fn.restype = c.c_int
    program = ptr()
    def call(name, *args):
        status = getattr(lib, name)(*args)
        if status: raise RuntimeError(f'{name}: NVVM status {status}')
    def log():
        size = c.c_size_t()
        if lib.nvvmGetProgramLogSize(program, c.byref(size)) or not size.value: return ''
        data = c.create_string_buffer(size.value)
        if lib.nvvmGetProgramLog(program, data): return 'cannot read NVVM log'
        return data.value.decode(errors='replace')
    call('nvvmCreateProgram', c.byref(program))
    # Keep all backing buffers alive until destruction of the NVVM program.
    buffers = []
    try:
        for index, path in enumerate([bitcode, *libraries]):
            data = path.read_bytes(); buf = c.create_string_buffer(data); buffers.append(buf)
            call('nvvmAddModuleToProgram' if index == 0 else 'nvvmLazyAddModuleToProgram',
                 program, buf, len(data), [b'merged', b'libdevice', b'libintrinsics'][index])
        options = (c.c_char_p * 1)(b'-arch=compute_100')
        status = lib.nvvmVerifyProgram(program, 1, options)
        verification_log = log()
        (output / 'nvvm-verify.log').write_text(verification_log)
        if status:
            # Match the existing LLVM 21 backend's narrowly recognized verifier
            # false negative; retain the log and let compilation decide.
            known = all(x in verification_log for x in
                        ("Producer: 'LLVM21", "Reader: 'LLVM 7.0.1'", 'parse Invalid value'))
            if not known: raise RuntimeError(f'NVVM verification failed: {status}')
        status = lib.nvvmCompileProgram(program, 1, options)
        (output / 'nvvm-compile.log').write_text(log())
        if status: raise RuntimeError(f'NVVM compilation failed: {status}')
        size = c.c_size_t(); call('nvvmGetCompiledResultSize', program, c.byref(size))
        data = c.create_string_buffer(size.value)
        call('nvvmGetCompiledResult', program, data)
        (output / 'rust_kernels.ptx').write_bytes(data.raw.rstrip(b'\0'))
    finally:
        call('nvvmDestroyProgram', c.byref(program))


def normalized_functions(ptx):
    return {name: re.sub(r'\s+', ' ', re.sub(r'//[^\n]*', '', body)).strip()
            for name, body in ptx_functions(ptx)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifacts', type=Path)
    parser.add_argument('--extended', action='store_true')
    parser.add_argument('--wave2', action='store_true', help='Record inlining remarks and bounded loop experiments')
    parser.add_argument('--only', help='Comma-separated experiment names; baseline is always included')
    args = parser.parse_args()
    root = args.artifacts.resolve()
    out = root / 'cleanup-experiment'; out.mkdir(exist_ok=True)
    # Require unique content when build caches contain multiple backend hashes.
    candidates = list(Path('target/cuda-builder-codegen').rglob('libintrinsics_v21.bc'))
    unique = {hashlib.sha256(p.read_bytes()).hexdigest(): p for p in candidates}
    if len(unique) != 1: raise RuntimeError(f'expected one distinct LLVM 21 intrinsic library, got {len(unique)}')
    intrinsics = next(iter(unique.values())).resolve()
    libdevice = Path(os.environ['CUDA_HOME']) / 'nvvm/libdevice/libdevice.10.bc'
    libraries = [libdevice, intrinsics]
    metadata = {'nvvm_options': ['-arch=compute_100'],
                'libraries': [{'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in libraries],
                'input_sha256': hashlib.sha256((root/'final-module.ll').read_bytes()).hexdigest(),
                'results': []}
    pipelines = wave2_experiments() if args.wave2 else experiments(args.extended)
    if args.only:
        requested = set(args.only.split(',')) | {'baseline'}
        unknown = requested - pipelines.keys()
        if unknown: raise ValueError(f'unknown experiments: {sorted(unknown)}')
        pipelines = {name: spec for name, spec in pipelines.items() if name in requested}
    baseline_matches = False
    for name, (passes, options) in pipelines.items():
        dest = out/name; dest.mkdir(exist_ok=True)
        if args.wave2:
            options = [*options, '-pass-remarks=inline|loop-unroll|sroa', '-pass-remarks-missed=inline|loop-unroll|sroa',
                       '-pass-remarks-analysis=inline|loop-unroll|sroa', '-pass-remarks-output='+str(dest/'remarks.yaml')]
        command = ['opt-21', '-passes='+passes, '-verify-each', *options, str(root/'final-module.ll'), '-o', str(dest/'module.bc')]
        item = {'name': name, 'passes': passes, 'opt_options': options, 'opt_command': command}
        started = time.perf_counter()
        try:
            with (dest/'opt.log').open('w') as log:
                subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
            item['opt_seconds'] = time.perf_counter() - started
            subprocess.run(['llvm-dis-21', str(dest/'module.bc'), '-o', str(dest/'final-module.ll')], check=True)
            compile_nvvm(dest/'module.bc', libraries, dest)
            source = (dest/'rust_kernels.ptx').read_text()
            if name == 'baseline':
                baseline_matches = normalized_functions(source) == normalized_functions((root/'rust_kernels.ptx').read_text())
                item['matches_original_function_bodies'] = baseline_matches
                if not baseline_matches: raise RuntimeError('baseline replay differs; do not attribute differences to cleanup')
            subprocess.run([sys.executable, str(Path(__file__).with_name('inspect_codegen.py')), str(dest),
                            '--reuse-from',str(root),'--reuse-from',str(root.parent/'inline-scalar')], check=True)
            item['ptx_helpers'] = {n:v for n,v in ptx_summary(source).items() if 'guarded_select' in n}
            item['status'] = 'compiled_and_assembled'
        except (RuntimeError, subprocess.CalledProcessError) as error:
            item['status'] = 'failed'; item['error'] = str(error)
        item['total_seconds'] = time.perf_counter() - started
        metadata['results'].append(item)
        (out/'experiment.json').write_text(json.dumps(metadata, indent=2)+'\n')
        print(name, item['status'], item.get('error',''), flush=True)
        if name == 'baseline' and not baseline_matches: return 1
    # Unsupported optimized IR is an experiment result, not a silent success.
    return int(any(item['status'] == 'failed' for item in metadata['results']))


if __name__ == '__main__':
    raise SystemExit(main())
