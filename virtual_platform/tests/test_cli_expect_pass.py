# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""sepvp.cli exit status: with --expect-pass only the PASS marker exits 0.

A run that times out or whose VP exits without printing PASS has not shown that the
test passed. Without the flag those outcomes keep exiting 0, which boot-run relies on.
"""

import pexpect
import pytest
from sepvp import cli

pytestmark = pytest.mark.hostonly

# Index of each outcome in the pattern list cli.main() expects on.
ERROR, FAIL, PASS, EOF, TIMEOUT = range(5)


class FakeChild:
    def __init__(self, outcome):
        self.outcome = outcome
        self.after = b""

    def expect(self, patterns, timeout):
        assert patterns[EOF] is pexpect.EOF and patterns[TIMEOUT] is pexpect.TIMEOUT
        return self.outcome


def run_cli(monkeypatch, tmp_path, outcome, *extra):
    class FakeHarness:
        def __init__(self, cfg, **kwargs):
            self.run_dir = tmp_path
            self.log_path = tmp_path / "sep-vp.log"
            self.child = FakeChild(outcome)

        def spawn(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(cli, "SepVpHarness", FakeHarness)
    return cli.main(["--bin", str(tmp_path / "test.elf"), *extra])


@pytest.mark.parametrize(
    "outcome, expect_pass, rc",
    [
        (PASS, True, 0),
        (FAIL, True, 2),
        (ERROR, True, 2),
        (EOF, True, 2),
        (TIMEOUT, True, 2),
        (PASS, False, 0),
        (FAIL, False, 2),
        (EOF, False, 0),
        (TIMEOUT, False, 0),
    ],
)
def test_exit_status(monkeypatch, tmp_path, outcome, expect_pass, rc):
    extra = ["--expect-pass"] if expect_pass else []
    assert run_cli(monkeypatch, tmp_path, outcome, *extra) == rc
