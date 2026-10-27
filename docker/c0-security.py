#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Tomas Gonzalez
# SPDX-License-Identifier: MIT
"""Private image-construction security repairs; never a host launcher action."""
import ast
import hashlib
import json
import os
from pathlib import Path
import sys
import tarfile


def patch_python_tarfile(path):
    """Backport CPython gh-160097 without replacing the system interpreter."""
    source = path.read_text()
    before = hashlib.sha256(source.encode()).hexdigest()
    # The common check must apply to both tar_filter and data_filter. Keep any
    # older data-only guard too: removing it is unnecessary for this backport.
    # Upstream 3.13 fix: python/cpython commit 7a6bbf8ceb64aa4ffd12243f8ffbf0aad43e584b.
    anchor = '    # Limit permissions (no high bits, and go-w)\n'
    guard = ("    if ((member.islnk() or member.issym())\n"
             "            and os.path.normpath(name) == os.curdir):\n"
             "        raise OutsideDestinationError(member, target_path)\n")
    # Check actual behavior first; a distribution may already carry the fix.
    protected = True
    for name in ('', '.', './', 'nested/..'):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
            member = tarfile.TarInfo(name)
            member.type, member.linkname = kind, '.'
            try:
                tarfile.tar_filter(member, '/tmp/c0-tarfile-verification')
            except tarfile.OutsideDestinationError:
                continue
            protected = False
    if not protected:
        tree = ast.parse(source, filename=str(path))
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name == '_get_filtered_attrs']
        consumers = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name == 'tar_filter']
        expected_consumer = ast.parse('''def tar_filter(member, dest_path):
    new_attrs = _get_filtered_attrs(member, dest_path, False)
    if new_attrs:
        return member.replace(**new_attrs, deep=False)
    return member
''').body[0]
        if (len(functions) != 1 or len(consumers) != 1
                or ast.dump(consumers[0]) != ast.dump(expected_consumer)):
            raise ValueError('unrecognized system tarfile implementation; refusing an unverified repair')
        function = functions[0]
        lines = source.splitlines(keepends=True)
        body = ''.join(lines[function.lineno - 1:function.end_lineno])
        if (body.count(anchor) != 1 or function.decorator_list or function.returns is not None
                or [arg.arg for arg in function.args.args] != ['member', 'dest_path', 'for_data']
                or function.args.posonlyargs or function.args.kwonlyargs
                or function.args.vararg or function.args.kwarg
                or len(function.args.defaults) != 1
                or not isinstance(function.args.defaults[0], ast.Constant)
                or function.args.defaults[0].value is not True
                or any(arg.annotation is not None for arg in function.args.args)):
            raise ValueError('unrecognized system tarfile implementation; refusing an unverified repair')

        def protection(candidate):
            namespace = dict(vars(tarfile))
            parsed = ast.parse(candidate, filename=str(path))
            selected = next(node for node in parsed.body
                            if isinstance(node, ast.FunctionDef) and node.name == '_get_filtered_attrs')
            consumer = next(node for node in parsed.body
                            if isinstance(node, ast.FunctionDef) and node.name == 'tar_filter')
            try:
                exec(compile(ast.Module(body=[selected, consumer], type_ignores=[]), str(path), 'exec'), namespace)
            except Exception as error:
                raise ValueError('unrecognized system tarfile implementation') from error
            for name in ('', '.', './', 'nested/..'):
                for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                    member = tarfile.TarInfo(name)
                    member.type, member.linkname = kind, '.'
                    try:
                        namespace['tar_filter'](member, '/tmp/c0-tarfile-verification')
                    except tarfile.OutsideDestinationError:
                        continue
                    except Exception as error:
                        raise ValueError('unrecognized system tarfile implementation') from error
                    return False
            # A repair that merely rejects every member would break extraction.
            for name, kind in (('payload', tarfile.REGTYPE), ('alias', tarfile.SYMTYPE)):
                member = tarfile.TarInfo(name)
                member.type, member.linkname = kind, 'payload'
                try:
                    namespace['tar_filter'](member, '/tmp/c0-tarfile-verification')
                except Exception as error:
                    raise ValueError('system tarfile repair rejected ordinary archive members') from error
            return True

        if protection(source):
            protected = True  # A prior call repaired disk, but the module is cached.
        else:
            repaired = body.replace(anchor, guard + anchor, 1)
            updated = ''.join(lines[:function.lineno - 1]) + repaired + ''.join(lines[function.end_lineno:])
            compile(updated, str(path), 'exec')
            if not protection(updated):
                raise ValueError('system tarfile repair did not establish destination-link rejection')
            path.write_text(updated)
    return {'component': 'system-python-tarfile', 'advisory': 'CVE-2026-114583',
            'upstream_commit': '7a6bbf8ceb64aa4ffd12243f8ffbf0aad43e584b',
            'already_fixed': protected, 'before_sha256': before,
            'after_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def main(argv):
    if len(argv) != 2 or argv[1] != 'system-python':
        raise ValueError('usage: c0-security.py system-python')
    if sys.platform != 'linux' or os.geteuid() != 0:
        raise ValueError('system repair is restricted to privileged Linux image construction')
    result = patch_python_tarfile(Path(tarfile.__file__))
    directory = Path('/usr/share/c0/security')
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'system-python.json').write_text(json.dumps(result, sort_keys=True) + '\n')


if __name__ == '__main__':
    try:
        main(sys.argv)
    except (OSError, ValueError) as error:
        print('error: image security repair refused: ' + str(error), file=sys.stderr)
        sys.exit(1)
