#!/usr/bin/env python3
"""Compare opt-in per-codegen-unit cleanup with independent LLVM replay."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import subprocess
import sys
from optimization_pipelines import SCALAR


def canonical_phi(line):
    # PHI incoming pairs are unordered. Keep each value attached to its block;
    # this is applied only after LLVM has verified and stripped local names.
    if ' = phi ' not in line:
        return line
    groups = []
    depth = 0
    quoted = escaped = False
    start = 0
    for index, char in enumerate(line):
        if not quoted:
            if char == '[':
                if depth == 0: start = index
                depth += 1
            elif char == ']':
                depth -= 1
                if depth == 0:
                    group = line[start:index + 1]
                    if re.search(r',\s*%[\w.$-]+\s*\]$', group):
                        groups.append((start, index + 1, group))
        if char == '"' and not escaped: quoted = not quoted
        escaped = char == "\\" and not escaped
    if len(groups) < 2:
        return line
    if any(line[a[1]:b[0]].strip() != ',' for a, b in zip(groups, groups[1:])):
        return line
    return line[:groups[0][0]] + ', '.join(sorted(g[2] for g in groups)) + line[groups[-1][1]:]


def canonical(ir):
    # Ignore LLVM printer comments (including predecessor order), but preserve
    # semicolons inside quoted identifiers, inline assembly and string constants.
    lines = []
    for line in ir.splitlines():
        quoted = escaped = False
        end = len(line)
        for index, char in enumerate(line):
            if char == ';' and not quoted:
                end = index
                break
            if char == '"' and not escaped:
                quoted = not quoted
            escaped = char == "\\" and not escaped
        text = line[:end].rstrip()
        if text.strip(): lines.append(canonical_phi(text))
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifacts', type=Path)
    args = parser.parse_args()
    root = args.artifacts.resolve()
    results = []
    for mode in ('module-scalar', 'module-inline'):
        out = root/'module-cleanup'/mode; out.mkdir(parents=True, exist_ok=True)
        command = ['cargo', 'run', '-vv', '-p', 'ptx_export', '--features', 'llvm19', '--', str(out), mode]
        (out/'compiler-command.json').write_text(json.dumps(command, indent=2)+'\n')
        with (out/'build.log').open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        before = sorted((out/'per-module').glob('*.before.ll'))
        if not before: raise RuntimeError('no per-module before/after evidence')
        checked = []
        for path in before:
            after = path.with_name(path.name.replace('.before.ll', '.after.ll'))
            replay = path.with_name(path.name.replace('.before.ll', '.replay.ll'))
            normalized = path.with_name(path.name.replace('.before.ll', '.normalized.ll'))
            subprocess.run(['opt-19', '-passes='+SCALAR+',strip-nondebug,verify', '-verify-each', '-S', str(path), '-o', str(replay)], check=True)
            subprocess.run(['opt-19', '-passes=strip-nondebug,verify', '-S', str(after), '-o', str(normalized)], check=True)
            if canonical(replay.read_text()) != canonical(normalized.read_text()):
                raise RuntimeError(f'per-module replay mismatch: {path.name}')
            checked.append({'module':path.name.removesuffix('.before.ll'),
                            'before_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                            'after_sha256':hashlib.sha256(after.read_bytes()).hexdigest()})
        if not any(x['module'].startswith('core') for x in checked):
            raise RuntimeError('missing dependency module coverage')
        subprocess.run(['opt-19', '-passes=verify', '-disable-output', str(out/'final-module.ll')], check=True)
        subprocess.run([sys.executable, str(Path(__file__).with_name('inspect_codegen.py')), str(out)], check=True)
        if mode == 'module-inline':
            subprocess.run([sys.executable, str(Path(__file__).with_name('check_cleanup_ir.py')),
                            str(out/'final-module.ll'), '--out', str(out/'host-ir-check')], check=True)
        results.append({'mode':mode, 'checked_modules':checked})
        (root/'module-cleanup'/'comparison.json').write_text(json.dumps(results, indent=2)+'\n')
        print(f'{mode}: {len(checked)} modules match standalone replay; final PTX assembled', flush=True)


if __name__ == '__main__':
    main()
