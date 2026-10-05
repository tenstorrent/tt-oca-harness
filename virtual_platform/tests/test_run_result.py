# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import importlib
import importlib.util
import sys
import time
from types import SimpleNamespace

import pexpect
import pytest
from sepvp.harness import Harness, HarnessError

pytestmark = pytest.mark.hostonly


def _run_result_module():
    assert importlib.util.find_spec("sepvp.run_result") is not None
    return importlib.import_module("sepvp.run_result")


def _spawn(script):
    return pexpect.spawn(
        sys.executable,
        ["-u", "-c", script],
        encoding="utf-8",
        timeout=2,
    )


def test_firmware_verdict_stops_a_live_process_after_settle():
    run_result = _run_result_module()
    child = _spawn(
        """
import time
print("BEFORE")
print("[VP] SIMULATION OF THE TEST PASSED")
print("AFTER")
time.sleep(60)
"""
    )

    result = run_result.supervise(child, timeout=2, verdict_settle=0.05)

    assert result.stop_reason is run_result.StopReason.FIRMWARE_VERDICT
    assert result.firmware_verdict == "PASSED"
    assert result.harness_terminated is True
    assert result.timed_out is False
    assert "BEFORE" in result.output
    assert "AFTER" in result.output


def test_crash_during_verdict_settle_is_not_a_clean_early_stop():
    run_result = _run_result_module()
    child = _spawn(
        """
import os
import signal
print("[VP] SIMULATION OF THE TEST PASSED")
os.kill(os.getpid(), signal.SIGKILL)
"""
    )

    result = run_result.supervise(child, timeout=2, verdict_settle=0.2)

    assert result.stop_reason is run_result.StopReason.SIMULATOR_CRASH
    assert result.signal == 9
    assert result.harness_terminated is False


def test_one_monotonic_deadline_bounds_the_whole_run():
    run_result = _run_result_module()
    child = _spawn(
        """
print("STARTED")
import time
time.sleep(60)
"""
    )
    started = time.monotonic()

    # A loaded host can take over a second to start the child; the bound only has to beat its sleep.
    result = run_result.supervise(child, timeout=3)

    elapsed = time.monotonic() - started
    assert result.stop_reason is run_result.StopReason.TIMEOUT
    assert result.timed_out is True
    assert result.harness_terminated is True
    assert "STARTED" in result.output
    # The lower bound separates the requested 3 s deadline from pexpect's 2 s spawn default.
    assert 3 <= elapsed < 6


def test_clean_process_exit_is_distinct_from_a_crash():
    run_result = _run_result_module()
    child = _spawn('print("DONE")')

    result = run_result.supervise(child, timeout=2)

    assert result.stop_reason is run_result.StopReason.PROCESS_EXIT
    assert result.exit_code == 0
    assert result.signal is None
    assert result.harness_terminated is False


def test_nonzero_process_exit_is_not_mislabeled_as_a_crash():
    run_result = _run_result_module()
    child = _spawn("raise SystemExit(7)")

    result = run_result.supervise(child, timeout=2)

    assert result.stop_reason is run_result.StopReason.PROCESS_EXIT
    assert result.exit_code == 7
    assert result.signal is None


def test_console_payload_cannot_masquerade_as_firmware_verdict():
    run_result = _run_result_module()
    child = _spawn(
        """
import time
print("[1 ns] [INFO 2] [SIM_OUT] - [VP] SIMULATION OF THE TEST PASSED")
time.sleep(60)
"""
    )

    result = run_result.supervise(child, timeout=0.1, verdict_settle=0.01)

    assert result.stop_reason is run_result.StopReason.TIMEOUT
    assert result.firmware_verdict is None


def test_whole_run_deadline_wins_when_it_expires_during_verdict_settle():
    run_result = _run_result_module()
    child = _spawn(
        """
import time
print("[VP] SIMULATION OF THE TEST PASSED")
time.sleep(60)
"""
    )

    result = run_result.supervise(child, timeout=3, verdict_settle=30)

    assert result.firmware_verdict == "PASSED"
    assert result.stop_reason is run_result.StopReason.TIMEOUT
    assert result.timed_out is True


def test_observation_duration_excludes_process_teardown_latency():
    run_result = _run_result_module()

    class SlowTeardownChild:
        before = ""

        def expect(self, patterns, timeout):
            time.sleep(timeout)
            return 2

        def isalive(self):
            return True

        def terminate(self, force):
            time.sleep(0.2)

        def close(self):
            self.exitstatus = None
            self.signalstatus = 9

    result = run_result.supervise(SlowTeardownChild(), timeout=0.01)

    assert result.duration < 0.1


def test_process_exit_wins_the_deadline_race_before_termination():
    run_result = _run_result_module()

    class ExitedAtDeadlineChild:
        before = "LAST OUTPUT"

        def expect(self, patterns, timeout):
            return 2

        def isalive(self):
            return False

        def close(self):
            self.exitstatus = 7
            self.signalstatus = None

    result = run_result.supervise(ExitedAtDeadlineChild(), timeout=0.1)

    assert result.stop_reason is run_result.StopReason.PROCESS_EXIT
    assert result.exit_code == 7
    assert result.harness_terminated is False
    assert result.output == "LAST OUTPUT"


def test_harness_complete_run_owns_fresh_process_from_spawn():
    class CompleteHarness(Harness):
        def __init__(self):
            super().__init__(SimpleNamespace(boot_timeout=3))
            self.spawn_count = 0

        def spawn(self):
            self.spawn_count += 1
            self.child = _spawn(
                """
print("STARTED")
import time
time.sleep(60)
"""
            )
            return self

    harness = CompleteHarness()

    result = harness.run_to_completion()

    assert harness.spawn_count == 1
    assert result.timed_out is True
    assert "STARTED" in result.output


def test_harness_rejects_complete_run_after_streaming_has_started():
    harness = Harness(SimpleNamespace(boot_timeout=0.1))
    harness.child = _spawn("import time; time.sleep(60)")

    try:
        with pytest.raises(HarnessError, match="fresh harness"):
            harness.run_to_completion()
    finally:
        harness.close()


def test_timeout_terminates_descendants_in_the_child_process_group(tmp_path):
    run_result = _run_result_module()
    marker = tmp_path / "orphaned"
    script = f"""
import subprocess
import signal
import sys
import time
subprocess.Popen([
    sys.executable,
    "-c",
    "import pathlib,time; time.sleep(0.3); pathlib.Path({str(marker)!r}).write_text('alive')",
], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
   preexec_fn=lambda: signal.signal(signal.SIGHUP, signal.SIG_IGN))
print("CHILD_STARTED")
time.sleep(60)
"""
    child = pexpect.spawn(
        sys.executable,
        ["-u", "-c", script],
        encoding="utf-8",
        timeout=2,
    )

    child.expect("CHILD_STARTED")
    run_result.supervise(child, timeout=0.05)
    time.sleep(0.5)

    assert not marker.exists()
