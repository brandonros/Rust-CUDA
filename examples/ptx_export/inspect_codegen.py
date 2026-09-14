#!/usr/bin/env python3
"""Collect offline NVIDIA codegen evidence; instruction counts are not timings."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


INSPECTION_OUTPUTS = ('rust_kernels.cubin', 'ptxas-resource-report.txt', 'nvdisasm.txt',
                      'sass.txt', 'resources.txt', 'codegen-summary.json', 'codegen-summary.md')


def reuse_inspection(candidate, out):
    """Reuse offline reports only for identical PTX, tools and inspector code."""
    if candidate.resolve() == out.resolve():
        return False
    required = (*INSPECTION_OUTPUTS, 'inspection-producer-sha256.txt', 'inspection-tools-sha256.json', 'inspection-commands.json',
                'ptxas-version.txt', 'nvdisasm-version.txt', 'cuobjdump-version.txt', 'rust_kernels.ptx')
    if not all((candidate/name).is_file() for name in required):
        return False
    for name in ('rust_kernels.ptx', 'inspection-producer-sha256.txt', 'inspection-tools-sha256.json',
                 'ptxas-version.txt', 'nvdisasm-version.txt', 'cuobjdump-version.txt'):
        if (candidate/name).read_bytes() != (out/name).read_bytes():
            return False
    copied = {}
    for name in INSPECTION_OUTPUTS:
        shutil.copy2(candidate/name, out/name)
        copied[name] = hashlib.sha256((out/name).read_bytes()).hexdigest()
    (out/'reused-inspection.json').write_text(json.dumps({
        'source':str(candidate.resolve()),
        'ptx_sha256':hashlib.sha256((out/'rust_kernels.ptx').read_bytes()).hexdigest(),
        'original_commands':json.loads((candidate/'inspection-commands.json').read_text()),
        'copied_sha256':copied,
        'note':'Identical PTX, inspector source and tool version outputs; assembly/disassembly not rerun.'
    },indent=2)+'\n')
    return True


def write_hashes(out):
    hashes = [f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(out)}'
              for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'SHA256SUMS']
    (out/'SHA256SUMS').write_text('\n'.join(hashes)+'\n')


def ptx_functions(source):
    # Only function definitions; prototypes end with ';' and are excluded.
    pattern = r'\.(?:entry|func)\s+(?:\([^)]*\)\s*)?([\w.$]+)\s*\([^;{}]*\)[^;{}]*\{'
    for match in re.finditer(pattern, source):
        depth, end = 1, match.end()
        while end < len(source) and depth:
            depth += (source[end] == '{') - (source[end] == '}')
            end += 1
        if depth:
            raise ValueError('unclosed PTX function body')
        yield match[1], source[match.end():end - 1]


def ptx_summary(source):
    result = {}
    for name, body in ptx_functions(source):
        ops, selects = Counter(), []
        for line in body.splitlines():
            line = line.split('//', 1)[0].strip()
            match = re.match(r'(?:@!?%[\w.$]+\s+)?([a-z][\w.]*)\s*(.*?)\s*;', line)
            if not match:
                continue
            opcode, operands = match.groups()
            ops[opcode] += 1
            if opcode.startswith('selp.'):
                parts = [part.strip() for part in operands.split(',')]
                if len(parts) == 4 and parts[0] == parts[2]:
                    selects.append(line)
        result[name] = {'opcode_histogram': dict(ops), 'self_false_selects': selects}
    return result


def sass_summary(source):
    result = {}
    for chunk in re.split(r'Function\s*:\s*', source)[1:]:
        name, _, body = chunk.partition('\n')
        ops = Counter(re.findall(r'/\*[0-9a-fA-F]+\*/\s+(?:@!?[\w]+\s+)?([A-Z][A-Z0-9_.]*)\b', body))
        result[name.strip()] = dict(ops)
    return result


def sass_symbols(source):
    """Use nvdisasm symbol extents; entry extents may include helper bodies."""
    labels = {m[1]: m.end() for m in re.finditer(r'^([\w.$]+):[ \t]*$', source, re.M)}
    result = {}
    for m in re.finditer(r'^\s*\.size\s+([\w.$]+),\(([\w.$]+)\s*-\s*([\w.$]+)\)', source, re.M):
        name, end, start = m.groups()
        if name != start or start not in labels or end not in labels:
            raise ValueError(f'unresolved SASS symbol extent: {m[0].strip()}')
        if labels[end] <= labels[start]: raise ValueError(f'invalid SASS extent: {name}')
        body = source[labels[start]:labels[end]]
        ops = Counter(re.findall(r'/\*[0-9a-fA-F]+\*/\s+(?:@!?[\w]+\s+)?([A-Z][A-Z0-9_.]*)\b', body))
        result[name] = {'opcode_histogram': dict(ops),
                        'non_nop_instructions': sum(ops.values()) - ops.get('NOP', 0),
                        'scope': 'helper' if name.startswith('$') else 'entry_including_helpers',
                        'end_label': end}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifacts', type=Path)
    parser.add_argument('--reuse-from', type=Path, action='append', default=[])
    args = parser.parse_args()
    out = args.artifacts.resolve()
    (out/'inspection-producer-sha256.txt').write_text(hashlib.sha256(Path(__file__).read_bytes()).hexdigest()+'\n')
    source = (out / 'rust_kernels.ptx').read_text()
    target = re.search(r'^\s*\.target\s+(sm_\d+[af]?)\b', source, re.M)
    if not target:
        raise ValueError('PTX target missing; refusing to guess an architecture')
    commands = []

    def run(argv, filename):
        commands.append(argv)
        (out / 'inspection-commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        with (out / filename).open('w') as log:
            subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT, check=True)

    tool_hashes = {}
    for tool in ('ptxas', 'nvdisasm', 'cuobjdump'):
        path = shutil.which(tool)
        if path is None:
            raise RuntimeError(f'{tool} is unavailable')
        run([path, '--version'], f'{tool}-version.txt')
        tool_hashes[tool] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    (out/'inspection-tools-sha256.json').write_text(json.dumps(tool_hashes,sort_keys=True)+'\n')
    for candidate in args.reuse_from:
        if reuse_inspection(candidate.resolve(), out):
            write_hashes(out)
            print(f'reused identical PTX inspection from {candidate}',flush=True)
            return
    run(['ptxas', '-arch=' + target[1], '-O3', '--verbose', '--warn-on-spills',
         '--preserve-relocs', str(out / 'rust_kernels.ptx'), '-o', str(out / 'rust_kernels.cubin')],
        'ptxas-resource-report.txt')
    run(['nvdisasm', str(out / 'rust_kernels.cubin')], 'nvdisasm.txt')
    run(['cuobjdump', '--dump-sass', str(out / 'rust_kernels.cubin')], 'sass.txt')
    run(['cuobjdump', '--dump-resource-usage', str(out / 'rust_kernels.cubin')], 'resources.txt')
    summary = {'target': target[1], 'ptx': ptx_summary(source),
               'sass': sass_summary((out / 'sass.txt').read_text()),
               'sass_symbols': sass_symbols((out / 'nvdisasm.txt').read_text()),
               'ptx_bytes': (out / 'rust_kernels.ptx').stat().st_size,
               'cubin_bytes': (out / 'rust_kernels.cubin').stat().st_size}
    (out / 'codegen-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    lines = ['# Guarded-select codegen inventory', '',
             'Static instruction counts only; no GPU execution or performance claim.',
             'Names absent below may have been inlined, merged or removed; inspect raw output.', '',
             '| PTX symbol | Static instructions | Self-false selects |', '| --- | ---: | ---: |']
    for name, data in summary['ptx'].items():
        if any(word in name for word in ('preserved', 'direct', 'observed', 'guarded_select')):
            lines.append(f"| `{name}` | {sum(data['opcode_histogram'].values())} | {len(data['self_false_selects'])} |")
    lines += ['', 'SASS opcode histograms are in `codegen-summary.json`; use `resources.txt`',
              'and `ptxas-resource-report.txt` for registers, stack and spill reports.',
              'Matching histograms do not establish equivalent machine code.', '']
    (out / 'codegen-summary.md').write_text('\n'.join(lines))
    write_hashes(out)


if __name__ == '__main__':
    main()
