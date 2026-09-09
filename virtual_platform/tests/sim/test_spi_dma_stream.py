# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""SPI-controller -> secure-DMA streaming integration check on sep-vp.

Drives the in-repo bare-metal test firmware (sw/sep-vp-tests/sep-spi-dma-test) through its
own Makefile, which builds with the RISC-V toolchain and runs the in-tree sep-vp with the
flash fixture staged:

  * sim        : several back-to-back hardware-handshake DMA drains of flash into SRAM,
                 each framed by CTRL.SW_RST (the boot ROM's per-read pattern), verifying
                 the DMA-drained bytes against the fixture oracle (byte[i] = i & 0xFF).

This is the integration counterpart to the per-model unit suites: it wires the REAL
spi_controller and REAL secure_dma together and exercises the second-read TX-command-drop
window (a SW_RST landing while the previous read is still in flight). The firmware
self-checks and prints "SEP_SPI_DMA_TEST: ALL PASS" / "All tests PASSED!"; we assert that.
Skips cleanly if the RISC-V toolchain or the sep-vp binary is absent.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from sepvp import paths

pytestmark = pytest.mark.spi_dma

FW_DIR = paths.SIM_DIR / "sw" / "sep-vp-tests" / "sep-spi-dma-test"
TIMEOUT = 300

PASS_MARK = "SEP_SPI_DMA_TEST: ALL PASS"
FAIL_MARK = "SEP_SPI_DMA_TEST: FAIL"


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


# Number of seconds the VP is allowed to run. sep-vp never self-terminates: tt-oca-harness-model 0ec43f9cc
# replaced the self-timing sim-unstaged/sim-staged targets with a plain `sim` that runs the
# VP directly, so the timeout has to come from here. Mirrors the upstream default this test
# used to get for free.
SIM_TIMEOUT = 60


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


def test_spi_dma_streaming_drain(request):
    """Several DMA-drained flash reads (SW_RST-framed) deliver byte-exact data to SRAM."""
    _require_prereqs(request)
    out = _run_make(request, "sim")
    assert FAIL_MARK not in out, f"a DMA transfer failed verification:\n{out[-4000:]}"
    assert PASS_MARK in out, f"firmware self-check did not report all-pass:\n{out[-4000:]}"
