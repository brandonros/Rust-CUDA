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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifacts', type=Path)
    args = parser.parse_args()
    out = args.artifacts.resolve()
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

    for tool in ('ptxas', 'nvdisasm', 'cuobjdump'):
        path = shutil.which(tool)
        if path is None:
            raise RuntimeError(f'{tool} is unavailable')
        run([path, '--version'], f'{tool}-version.txt')
    run(['ptxas', '-arch=' + target[1], '-O3', '--verbose', '--warn-on-spills',
         '--preserve-relocs', str(out / 'rust_kernels.ptx'), '-o', str(out / 'rust_kernels.cubin')],
        'ptxas-resource-report.txt')
    run(['nvdisasm', str(out / 'rust_kernels.cubin')], 'nvdisasm.txt')
    run(['cuobjdump', '--dump-sass', str(out / 'rust_kernels.cubin')], 'sass.txt')
    run(['cuobjdump', '--dump-resource-usage', str(out / 'rust_kernels.cubin')], 'resources.txt')
    summary = {'target': target[1], 'ptx': ptx_summary(source),
               'sass': sass_summary((out / 'sass.txt').read_text())}
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
    hashes = [f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(out)}'
              for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'SHA256SUMS']
    (out / 'SHA256SUMS').write_text('\n'.join(hashes) + '\n')


if __name__ == '__main__':
    main()
