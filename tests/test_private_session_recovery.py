"""Exercise the host collector against a fake CDP transport, without FPL access."""
import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize('error,recover,expected_calls', [
    ('FPL_AUTH_REQUIRED', True, 2),
    ('FPL_AUTH_REQUIRED', False, 2),
    ('FPL_API_ERROR', False, 1),
])
def test_single_session_refresh_is_read_only_and_bounded(tmp_path, error, recover, expected_calls):
    binary = tmp_path / 'bin'; binary.mkdir()
    calls = tmp_path / 'calls'; count = tmp_path / 'count'
    docker = binary / 'docker'
    docker.write_text('''#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$TEST_CALLS"
if [[ "$*" == *'private-team-state.js'* ]]; then
  n=0; [[ ! -f "$TEST_COUNT" ]] || read -r n < "$TEST_COUNT"
  n=$((n+1)); echo "$n" > "$TEST_COUNT"
  if [[ "$n" == 2 && "$TEST_RECOVER" == yes ]]; then echo '{"schema":"fixture"}'; exit 0; fi
  echo "Evaluation error: Error: $TEST_ERROR" >&2; exit 1
fi
if [[ "$*" == *' eval '* ]]; then
  if [[ "$*" == *'account.premierleague.com'* ]]; then echo false; else echo true; fi
fi
''')
    docker.chmod(0o755)
    curl = binary / 'curl'; curl.write_text('#!/bin/sh\nexit 0\n'); curl.chmod(0o755)
    env = dict(os.environ, PATH=str(binary)+':'+os.environ['PATH'],
               MOVA_REPO_DIR=str(tmp_path), MOVA_DEPLOY_ENV='/dev/null',
               TEST_CALLS=str(calls), TEST_COUNT=str(count), TEST_ERROR=error,
               TEST_RECOVER='yes' if recover else 'no')
    result = subprocess.run(['bash', str(Path('deploy/bin/browser-session.sh').resolve()), 'collect'],
                            env=env, capture_output=True, text=True, timeout=10)
    assert int(count.read_text()) == expected_calls
    assert (result.returncode == 0) is recover
    commands = calls.read_text().splitlines()
    assert sum(line.endswith(' reload') for line in commands) == int(error == 'FPL_AUTH_REQUIRED')
    assert not any(' click ' in line or ' fill ' in line or ' cookies ' in line for line in commands)
    if recover: assert '"schema":"fixture"' in result.stdout
