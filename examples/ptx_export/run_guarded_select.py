#!/usr/bin/env python3
"""Numerically check runtime-input select kernels through a CUDA Driver API library.

Native default: NVIDIA libcuda.so.1 and an unchanged PTX/cubin module.
An explicit compatible driver/module can test another consumer separately.
"""
import argparse
import ctypes as c
import os
from pathlib import Path

MASK = (1 << 64) - 1


def expected(table, limit, initial, filtered=False):
    n = min(limit, 64)
    odd_sum = sum(table[i] for i in range(1, n, 2)) & MASK
    if filtered:
        return [odd_sum, odd_sum]
    observed = sum(table[(initial & 63) if i == 0 else ((i - 1) | 1)] for i in range(n)) & MASK
    return [odd_sum, odd_sum, observed]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('module', type=Path)
    parser.add_argument('--kernel', choices=['rust_guarded_select', 'rust_filtered_select'], required=True)
    parser.add_argument('--driver', default='libcuda.so.1')
    args = parser.parse_args()
    os.environ['CUMETAL_TRACE_GPU'] = '1'
    os.environ['CUMETAL_ENABLE_WORKLOAD_SPECIALIZATIONS'] = '0'
    lib = c.CDLL(args.driver)
    ptr, u32, u64 = c.c_void_p, c.c_uint32, c.c_uint64

    def api(name, types, *values):
        # Prefer the size_t / 64-bit device-pointer versions on NVIDIA.
        fn = getattr(lib, name + '_v2', None) or getattr(lib, name)
        fn.argtypes, fn.restype = types, c.c_int
        status = fn(*values)
        if status: raise RuntimeError(f'{name} failed: {status}')

    api('cuInit', [u32], 0)
    device = c.create_string_buffer(256)
    api('cuDeviceGetName', [ptr, c.c_int, c.c_int], device, len(device), 0)
    context, module, kernel = ptr(), ptr(), ptr()
    api('cuCtxCreate', [c.POINTER(ptr), u32, c.c_int], c.byref(context), 0, 0)
    total = 0
    try:
        api('cuModuleLoad', [c.POINTER(ptr), c.c_char_p], c.byref(module), os.fsencode(args.module.resolve()))
        api('cuModuleGetFunction', [c.POINTER(ptr), ptr, c.c_char_p], c.byref(kernel), module, args.kernel.encode())
        cases = [(limit, initial) for limit in [*range(66), (1 << 32) - 1]
                 for initial in [0, 1, 17, 63, 64, MASK]]
        filtered = args.kernel == 'rust_filtered_select'
        for seed in [0, 1, 1 << 63, MASK]:
            table = [(i * 0x9e3779b97f4a7c15 + seed) & MASK for i in range(64)]
            oracle = [v for limit, initial in cases for v in expected(table, limit, initial, filtered)]
            poison = 0xa5a5a5a5a5a5a5a5
            result = (u64 * (len(oracle) + 16))(*([poison] * (len(oracle) + 16)))
            inputs = [(u64 * 64)(*table), (u32 * len(cases))(*(x[0] for x in cases))]
            if not filtered: inputs.append((u64 * len(cases))(*(x[1] for x in cases)))
            allocations = []
            try:
                for data in [*inputs, result]:
                    address = u64()
                    api('cuMemAlloc', [c.POINTER(u64), c.c_size_t], c.byref(address), c.sizeof(data))
                    allocations.append(address)
                    api('cuMemcpyHtoD', [u64, ptr, c.c_size_t], address, c.cast(data, ptr), c.sizeof(data))
                # Native CUDA reads the low four bytes; wider backing storage
                # also accommodates consumers whose scalar ABI reads eight.
                count = u64(len(cases))
                parameters = (ptr * (len(allocations) + 2))(
                    *[c.cast(c.pointer(x), ptr) for x in [*allocations, count]], None)
                api('cuLaunchKernel', [ptr] + [u32] * 7 + [ptr, c.POINTER(ptr), ptr],
                    kernel, (len(cases) + 63) // 64, 1, 1, 64, 1, 1, 0, None, parameters, None)
                api('cuCtxSynchronize', [])
                api('cuMemcpyDtoH', [ptr, u64, c.c_size_t], c.cast(result, ptr), allocations[-1], c.sizeof(result))
                for index, value in enumerate(oracle):
                    if result[index] != value:
                        raise RuntimeError(f'seed={seed} word={index}: got {result[index]:016x}, expected {value:016x}')
                if list(result)[len(oracle):] != [poison] * 16: raise RuntimeError('output guard overwritten')
                total += len(cases)
            finally:
                for address in reversed(allocations): api('cuMemFree', [u64], address)
        print(f'NUMERICAL_PASS {args.kernel}: {total} cases, independent oracle and guards; '
              f'device={device.value.decode()} driver={args.driver}')
    finally:
        if module.value: api('cuModuleUnload', [ptr], module)
        api('cuCtxDestroy', [ptr], context)


if __name__ == '__main__':
    main()
