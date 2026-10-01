# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""SPI mux register + flash-loader checks on sep-vp.

Drives the in-repo bare-metal test firmware (sw/sep-vp-tests/sep-spi-mux-test) through its own
Makefile targets, which build with the RISC-V toolchain and run the in-tree sep-vp:

  * sim          : no image staged -> mux RW/reset checks pass; flash reads erased 0xFF; the
                   loader logs the "... not found" no-op line.
  * sim STAGED=1 : the fixture is staged to data/flash_memory.bin -> the controller read returns
                   the fixture bytes and the loader logs "loaded N bytes from ...".

The firmware self-checks and prints "All tests PASSED!"; we assert that plus the loader's log
line for each mode. Skips cleanly if the RISC-V toolchain or the sep-vp binary is absent.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from sepvp import paths

pytestmark = pytest.mark.spi_mux

FW_DIR = paths.SIM_DIR / "sw" / "sep-vp-tests" / "sep-spi-mux-test"
TIMEOUT = 180

PASS_MARK = "All tests PASSED!"
LOADED_MARK = "Backdoor: loaded"  # staged: "[spi_flash] Backdoor: loaded N bytes ..."


def _env(request):
    """Toolchain bin on PATH for the firmware build."""
    env = paths.vp_env()
    tc = request.config.getoption("--riscv-toolchain")
    if tc and (Path(tc) / "bin").is_dir():
        env["PATH"] = f"{Path(tc) / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    return env


def _require_prereqs(request):
    tc = request.config.getoption("--riscv-toolchain")
    if not (
        (tc and (Path(tc) / "bin" / "riscv64-unknown-elf-gcc").exists())
        or shutil.which("riscv64-unknown-elf-gcc")
    ):
        pytest.skip("RISC-V toolchain not found (PATH or --riscv-toolchain/RISCV_TOOLCHAIN)")
    if not paths.sep_vp_bin().is_file():
        pytest.skip(f"sep-vp not built ({paths.sep_vp_bin()})")
    if not FW_DIR.is_dir():
        pytest.skip(f"test firmware dir missing ({FW_DIR})")


# sep-vp never self-terminates, so the run limit comes from here.
SIM_TIMEOUT = 20


def _run_make(request, *make_args):
    """Run a test-Makefile target with the VP wrapped in a timeout.

    The Makefile declares `VP = ...` (a plain recursive assignment), so a command-line value
    wins. Overriding it puts the timeout on the *VP process*, not on make -- killing make
    alone would orphan a running sep-vp. A timeout exit is expected and not an error: the
    assertions are on the captured output, not the return code.
    """
    vp = f"timeout -k 5 {SIM_TIMEOUT} {paths.sep_vp_bin()}"
    res = subprocess.run(
        ["make", *make_args, f"VP={vp}"],
        cwd=str(FW_DIR),
        env=_env(request),
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    return res.stdout + "\n" + res.stderr


@pytest.fixture(autouse=True)
def _cleanup(request):
    yield
    subprocess.run(
        ["make", "distclean"], cwd=str(FW_DIR), env=_env(request), capture_output=True, text=True
    )


def test_mux_rw_and_flash_noop_unstaged(request):
    """Mux store/load + reset default pass; flash is erased 0xFF; loader no-ops when unstaged.

    The backdoor loader is opt-in (`spiBackdoorFile`), so an unstaged run must not log a
    load at all -- the firmware's own erased-0xFF check is what proves the flash is blank.
    The model used to attempt an implicit data/flash_memory.bin and log a "not found"
    no-op line; asserting its *absence* is the same assertion against current behaviour.
    """
    _require_prereqs(request)
    out = _run_make(request, "sim")
    assert PASS_MARK in out, f"firmware self-check failed:\n{out[-3000:]}"
    assert LOADED_MARK not in out, f"loader ran with no image staged:\n{out[-2000:]}"


def test_flash_loaded_staged(request):
    """With the fixture staged, the controller read returns staged bytes and the loader logs."""
    _require_prereqs(request)
    out = _run_make(request, "sim", "STAGED=1")
    assert PASS_MARK in out, f"firmware self-check failed:\n{out[-3000:]}"
    assert LOADED_MARK in out, f"expected the loader 'loaded N bytes' line:\n{out[-2000:]}"
