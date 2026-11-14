"""Run pinned tools with interpreters allowed by the existing sandbox."""
import os
import sys


def command(tool, args):
    node = '/opt/agent/node/bin/node'
    if tool == 'openspec':
        return [node, '/opt/sdd-tools/openspec/node_modules/@fission-ai/openspec/bin/openspec.js', *args]
    if tool == 'cc-sdd':
        return [node, '/opt/sdd-tools/cc-sdd/node_modules/cc-sdd/dist/cli.js', *args]
    if tool == 'specify':
        os.environ['PYTHONPATH'] = f'/opt/sdd-tools/speckit/lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages'
        return ['/usr/local/bin/python3', '/opt/sdd-tools/speckit/bin/specify', *args]
    raise ValueError('UNKNOWN_PUBLIC_TOOL')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit('Usage: python3 tool.py openspec|specify|cc-sdd ARGS')
    argv = command(sys.argv[1], sys.argv[2:])
    os.execv(argv[0], argv)
