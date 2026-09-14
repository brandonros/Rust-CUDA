#!/usr/bin/env python3
"""Numerical probes and opt-in CUDA-event timings for unchanged wave-2 modules.

Use native NVIDIA libcuda.so.1 for timing. An explicit compatible driver can
validate another consumer numerically; those results are labeled separately.
"""
import argparse
import ctypes as c
import hashlib
import json
import os
from pathlib import Path
import statistics

PTR, U32, U64 = c.c_void_p, c.c_uint32, c.c_uint64
GUARD = 0xA5A5A5A5


class Driver:
    def __init__(self, library):
        self.lib = c.CDLL(library)

    def call(self, name, types, *values):
        fn = getattr(self.lib, name+'_v2', None) or getattr(self.lib, name)
        fn.argtypes, fn.restype = types, c.c_int
        status = fn(*values)
        if status:
            raise RuntimeError(f'{name}: CUDA status {status}')

    def launch(self, kernel, parameters, count):
        self.call('cuLaunchKernel', [PTR]+[U32]*7+[PTR,c.POINTER(PTR),PTR],
                  kernel, (count+31)//32,1,1,32,1,1,0,None,parameters,None)


def input_and_oracle(kernel, count):
    if kernel == 'wave2_float':
        # Binary fractions in this range are exact with either fused or separate operations.
        a = [(i % 1024 - 512) * 0.25 for i in range(count)]
        b = [(i % 257 - 128) * 0.5 for i in range(count)]
        expected = [(c.cast(c.pointer(c.c_float(x*0.5+y)), c.POINTER(U32))[0]) for x,y in zip(a,b)]
        inputs = [(c.c_float*count)(*a), (c.c_float*count)(*b)]
    elif kernel == 'wave2_atomic':
        inputs, expected = [], [(count*(count+1)//2) & 0xFFFFFFFF]
    else:
        data = [(i*2654435761+17) & 0xFFFFFFFF for i in range(count)]
        if kernel == 'wave2_shared':
            partners = [(i//32)*32+31-i%32 for i in range(count)]
            expected = [data[p] if p < count else 0 for p in partners]
        else:
            expected = []
            for i in range(count):
                base, lane = i//32*32, i%32
                # IDX(31), UP(1), DOWN(1), XOR(1), including invalid edge lanes.
                for partner in (31,lane-1,lane+1,lane^1):
                    expected.append(0xFFFFFFFF if not 0<=partner<32 else
                                    data[base+partner] if base+partner<count else 0)
        inputs = [(U32*count)(*data)]
    return inputs, expected


def run_case(driver, kernel, name, count, repeats):
    inputs, expected = input_and_oracle(name,count)
    host_output = (U32*(len(expected)+16))(*([GUARD]*(len(expected)+16)))
    if name == 'wave2_atomic': host_output[0] = 0
    allocations = []
    events = []
    try:
        for host in [*inputs,host_output]:
            device = U64()
            driver.call('cuMemAlloc',[c.POINTER(U64),c.c_size_t],c.byref(device),c.sizeof(host))
            allocations.append(device)
            driver.call('cuMemcpyHtoD',[U64,PTR,c.c_size_t],device,c.cast(host,PTR),c.sizeof(host))
        scalar = U64(count)  # Low 32 bits for CUDA; accommodates compatible consumers.
        parameters = (PTR*(len(allocations)+2))(*[c.cast(c.pointer(x),PTR) for x in [*allocations,scalar]],None)
        driver.launch(kernel,parameters,count)
        driver.call('cuCtxSynchronize',[])
        driver.call('cuMemcpyDtoH',[PTR,U64,c.c_size_t],c.cast(host_output,PTR),allocations[-1],c.sizeof(host_output))
        if list(host_output)[:len(expected)] != expected:
            raise RuntimeError(f'{name}/{count}: numerical mismatch')
        if list(host_output)[len(expected):] != [GUARD]*16:
            raise RuntimeError(f'{name}/{count}: output guard overwritten')
        result = {'kernel':name,'count':count,'numerical_pass':True,'guards_pass':True}
        if repeats:
            for _ in range(5): driver.launch(kernel,parameters,count)
            driver.call('cuCtxSynchronize',[])
            for _ in range(2):
                event=PTR(); driver.call('cuEventCreate',[c.POINTER(PTR),U32],c.byref(event),0);events.append(event)
            samples=[]
            for _ in range(7):
                driver.call('cuEventRecord',[PTR,PTR],events[0],None)
                for _ in range(repeats): driver.launch(kernel,parameters,count)
                driver.call('cuEventRecord',[PTR,PTR],events[1],None)
                driver.call('cuEventSynchronize',[PTR],events[1])
                elapsed=c.c_float()
                driver.call('cuEventElapsedTime',[c.POINTER(c.c_float),PTR,PTR],c.byref(elapsed),*events)
                samples.append(elapsed.value/repeats)
            result['timing']={'method':'CUDA events around repeated launches after five warmups; allocation/JIT/copies excluded',
                              'repeats_per_sample':repeats,'milliseconds_per_launch':samples,
                              'median_milliseconds_per_launch':statistics.median(samples)}
        return result
    finally:
        for event in reversed(events): driver.call('cuEventDestroy',[PTR],event)
        for pointer in reversed(allocations): driver.call('cuMemFree',[U64],pointer)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('module',type=Path)
    parser.add_argument('--driver',default='libcuda.so.1')
    parser.add_argument('--kernel',choices=['wave2_float','wave2_shared','wave2_atomic','wave2_shuffle'],required=True)
    parser.add_argument('--counts',default='1,31,32,33,257,131072')
    parser.add_argument('--benchmark',action='store_true')
    parser.add_argument('--repeats',type=int,default=100)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.benchmark and args.driver!='libcuda.so.1':
        parser.error('benchmarking requires native NVIDIA libcuda.so.1; compatible drivers are numerical-only')
    counts=[int(v) for v in args.counts.split(',')]
    if any(n<1 or n>2**24 for n in counts) or not 1<=args.repeats<=10000:
        parser.error('counts must be 1..2^24 and repeats 1..10000')
    os.environ['CUMETAL_ENABLE_WORKLOAD_SPECIALIZATIONS']='0'
    os.environ['CUMETAL_TRACE_GPU']='1'
    driver=Driver(args.driver)
    driver.call('cuInit',[U32],0)
    device=c.create_string_buffer(256)
    driver.call('cuDeviceGetName',[PTR,c.c_int,c.c_int],device,len(device),0)
    version=c.c_int();driver.call('cuDriverGetVersion',[c.POINTER(c.c_int)],c.byref(version))
    context,module,kernel=PTR(),PTR(),PTR()
    driver.call('cuCtxCreate',[c.POINTER(PTR),U32,c.c_int],c.byref(context),0,0)
    report={'module_sha256':hashlib.sha256(args.module.read_bytes()).hexdigest(),'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'driver':args.driver,'driver_version':version.value,'device':device.value.decode(),
            'native_nvidia_driver_requested':args.driver=='libcuda.so.1','results':[]}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    try:
        driver.call('cuModuleLoad',[c.POINTER(PTR),c.c_char_p],c.byref(module),os.fsencode(args.module.resolve()))
        driver.call('cuModuleGetFunction',[c.POINTER(PTR),PTR,c.c_char_p],c.byref(kernel),module,args.kernel.encode())
        for count in counts:
            result=run_case(driver,kernel,args.kernel,count,args.repeats if args.benchmark else 0)
            report['results'].append(result)
            args.out.write_text(json.dumps(report,indent=2)+'\n')
            print(json.dumps(result),flush=True)
    except Exception as error:
        report['error']=str(error);args.out.write_text(json.dumps(report,indent=2)+'\n');raise
    finally:
        if module.value: driver.call('cuModuleUnload',[PTR],module)
        driver.call('cuCtxDestroy',[PTR],context)


if __name__=='__main__':
    main()
