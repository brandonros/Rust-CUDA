"""Bounded LLVM 19 experiments. Explicit options are saved with each result."""
IC = 'instcombine<max-iterations=2;no-verify-fixpoint>'
SCALAR = f'function(sroa,{IC},simplifycfg,adce)'
INLINE = f'globaldce,cgscc(inline),{SCALAR},globaldce'
CORRELATED = f'function(correlated-propagation,{IC},simplifycfg,adce)'


def experiments(extended=False):
    pipelines = {
        'baseline': ('verify', []),
        'dce-only': ('globaldce,verify', []),
        'local-cleanup': (f'{SCALAR},verify', []),
        'inline-only': (f'{INLINE},verify', []),
        'inline-cleanup': (f'{INLINE},{CORRELATED},verify', []),
        'constrained-cleanup': (f'{INLINE},{CORRELATED},function(constraint-elimination,{IC},simplifycfg,adce),verify', []),
    }
    if extended:
        pipelines.update({
            'cfg-no-final': (f'{INLINE},function(correlated-propagation,{IC},adce),verify', []),
            'cfg-before-combine': (f'{INLINE},function(correlated-propagation,simplifycfg,{IC},adce),verify', []),
            'cfg-no-both': (f'globaldce,cgscc(inline),function(sroa,{IC},adce),globaldce,function(correlated-propagation,{IC},adce),verify', []),
            'dce-scalar': (f'globaldce,{SCALAR},globaldce,verify', []),
            'memory-early-cse': (f'{INLINE},function(early-cse<memssa>,{IC},adce),verify', []),
            'memory-gvn': (f'{INLINE},function(gvn,{IC},adce),verify', []),
            'memory-stores': (f'{INLINE},function(memcpyopt,dse,{IC},adce),verify', []),
            'memory-combined': (f'{INLINE},function(early-cse<memssa>,gvn,memcpyopt,dse,{IC},adce),verify', []),
            'inline-threshold-0': (f'{INLINE},{CORRELATED},verify', ['-inline-threshold=0', '-inlinehint-threshold=0']),
            'inline-threshold-50': (f'{INLINE},{CORRELATED},verify', ['-inline-threshold=50', '-inlinehint-threshold=50']),
            'inline-threshold-450': (f'{INLINE},{CORRELATED},verify', ['-inline-threshold=450', '-inlinehint-threshold=450']),
        })
    return pipelines


# Small constant-trip loops are a concrete source of residual RNG stack buffers.
# Disable runtime/partial/peeling expansion and cap full unrolling at four trips.
TINY_UNROLL = 'loop-unroll<O2;full-unroll-max=4;no-partial;no-peeling;no-profile-peeling;no-runtime;no-upperbound>'
TINY_LOOPS = f'loop-simplify,lcssa,loop(indvars),{TINY_UNROLL},sroa,{IC},simplifycfg,adce'


def wave2_experiments():
    return {
        'baseline': ('verify', []),
        'dce-only': ('globaldce,verify', []),
        'inline-only': (f'{INLINE},verify', []),
        'tiny-loops': (f'{INLINE},function({TINY_LOOPS}),verify', []),
        'correlated-tiny-loops': (f'{INLINE},{CORRELATED},function({TINY_LOOPS}),verify', []),
        'loop-idiom': (f'{INLINE},function(loop-simplify,lcssa,loop(loop-idiom),memcpyopt,sroa,{IC},simplifycfg,adce),verify', []),
    }
