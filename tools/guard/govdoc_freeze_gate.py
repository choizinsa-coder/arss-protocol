#!/usr/bin/env python3
# govdoc_freeze_gate.py - Governance/Goal-1 freeze pre-flight gate.
# EAG-S251-GOVDOC-PROTECT-001 (Part 2).
# Runs tests/test_goal1_freeze.py under ENV=test as a fast non-destructive
# blocking gate for boot/close. Exit 0 = intact; exit 1 = tamper (REPORT and WAIT).
import os
import subprocess
import sys

ROOT = '/opt/arss/engine/arss-protocol'


def main():
    env = dict(os.environ)
    env['ENV'] = 'test'
    r = subprocess.run(
        [sys.executable, '-m', 'pytest', 'tests/test_goal1_freeze.py', '-q', '--no-header'],
        cwd=ROOT, env=env,
    )
    if r.returncode != 0:
        print('[GOVDOC-FREEZE-GATE] FAIL - governance/Goal-1 frozen file tamper detected.')
        print('[GOVDOC-FREEZE-GATE] ACTION: REPORT and WAIT.')
        return 1
    print('[GOVDOC-FREEZE-GATE] PASS - frozen integrity intact.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
