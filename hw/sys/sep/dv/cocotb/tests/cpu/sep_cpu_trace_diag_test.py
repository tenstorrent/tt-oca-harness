# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP CPU-trace diagnostics test (PyUVM): prove the processor-state monitor.

Boots fw/tests/cpu_trace_diag_test, which runs a known noinline call chain
(main -> diag_leaf1 -> diag_leaf2 -> diag_leaf3), takes exactly one breakpoint
trap (uncompressed ebreak) inside the innermost frame, and prints the
architectural mcause/mepc on the console. The test then cross-checks the
trace monitor's reconstruction (env/sep_cpu_trace_monitor.py) against that
ground truth:

  * CHK-TRAP-EVENT -- the monitor captured exactly one exception retirement,
    cause = breakpoint (3), not an interrupt;
  * CHK-TRAP-SYM   -- the firmware-reported mepc symbolizes into diag_leaf3
    (nm-listing symbolization is correct on a CSR-true PC);
  * CHK-CHAIN-SYM  -- retired PCs cover every function of the chain (the
    monitor saw the chain execute, and each PC resolves to the right name);
  * CHK-DEPTH      -- the shadow call stack reached the chain's depth while
    the trap frame was live.

Standard boot-scoreboard checks (banner + firmware PASS + PC advance) apply on
top. The firmware image is fw/build/tests/cpu_trace_diag_test/*.{itcm,dtcm}.hex,
built by the c_compile stage (make dv-fw-tests TEST=cpu_trace_diag_test).

Stimulus is deterministic: the reconstruction is auditable only
against a known call chain and a known trap site, and the prebuilt image fixes
both at compile time (same shape as every cpu firmware test here). The seeded
clock-timing randomization from sep_base_test still applies on top, so the
trace sampling is exercised across timing variation run-to-run.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pyuvm
from env.sep_boot_scoreboard import SepBootScoreboard
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "cpu_trace_diag_test")
_ITCM_HEX = os.path.join(_FW_DIR, "cpu_trace_diag_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "cpu_trace_diag_test.dtcm.hex")

_EXPECTED_LINE = "SEP CPU trace diag test"
# main + diag_leaf1..3 are linking calls live at the ebreak; the trap frame
# stacks on top. crt0's `call main` may add one more -- assert the floor.
_MIN_STACK_DEPTH = 4
_MCAUSE_BREAKPOINT = 3
_CHAIN_SYMBOLS = ("diag_leaf1", "diag_leaf2", "diag_leaf3", "main")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
_MAX_RUN_CYCLES = 2_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 2_000


@pyuvm.test()
class sep_cpu_trace_diag_test(sep_base_test):
    """Boot the trace-diag firmware and audit the CPU trace monitor against it."""

    build_env = False

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    async def run_scenario(self) -> None:
        # Set after build (the scoreboard's own build_phase installs the
        # default banner and would overwrite an assignment made there).
        self.sb.expected_line = _EXPECTED_LINE
        await self.boot_firmware(
            self.sb,
            _ITCM_HEX,
            _DTCM_HEX,
            rst_vec=_ICCM_BASE >> 1,
            max_run_cycles=_MAX_RUN_CYCLES,
            no_boot_cycles=_NO_BOOT_CYCLES,
            progress_every=_PROGRESS_EVERY,
        )

        mon = self.cpu_trace_mon
        console = self.sb.console_text()

        # CHK-TRAP-EVENT: one breakpoint exception retirement, no interrupt.
        assert len(mon.trap_events) == 1, (
            f"CHK-TRAP-EVENT FAIL: monitor captured {len(mon.trap_events)} trap "
            f"event(s), expected exactly 1: {mon.trap_events}"
        )
        _cyc, trap_pc, ecause, interrupt, _tval = mon.trap_events[0]
        assert ecause == _MCAUSE_BREAKPOINT and not interrupt, (
            f"CHK-TRAP-EVENT FAIL: cause={ecause} interrupt={interrupt} "
            f"(expected breakpoint, ecause=3, interrupt=0)"
        )
        self.logger.info(
            "CHK-TRAP-EVENT PASS: 1 breakpoint trap, trace pc=0x%08x (%s)",
            trap_pc,
            mon.symbols.lookup(trap_pc),
        )

        # CHK-TRAP-SYM: the CSR-true mepc the firmware printed symbolizes into
        # diag_leaf3. Ground truth is architectural state, independent of the
        # trace port's exception-retirement PC convention.
        m = re.search(r"mepc=0x([0-9a-f]{8})", console)
        assert m, f"CHK-TRAP-SYM FAIL: no mepc report on the console: {console!r}"
        mepc = int(m.group(1), 16)
        mepc_sym = mon.symbols.lookup(mepc)
        assert mepc_sym.split("+")[0] == "diag_leaf3", (
            f"CHK-TRAP-SYM FAIL: mepc 0x{mepc:08x} symbolizes to {mepc_sym!r}, "
            f"expected inside diag_leaf3"
        )
        self.logger.info("CHK-TRAP-SYM PASS: mepc 0x%08x -> %s", mepc, mepc_sym)

        # CHK-CHAIN-SYM: the retired-PC set covers every chain function.
        seen = {mon.symbols.lookup(pc).split("+")[0] for pc in mon.pcs}
        missing = [name for name in _CHAIN_SYMBOLS if name not in seen]
        assert not missing, (
            f"CHK-CHAIN-SYM FAIL: no retired PC symbolized into {missing} "
            f"(saw {len(mon.pcs)} distinct PCs)"
        )
        self.logger.info("CHK-CHAIN-SYM PASS: retirements cover %s", ", ".join(_CHAIN_SYMBOLS))

        # CHK-DEPTH: the shadow stack tracked the chain plus the trap frame.
        assert mon.max_depth >= _MIN_STACK_DEPTH, (
            f"CHK-DEPTH FAIL: max shadow-stack depth {mon.max_depth} < {_MIN_STACK_DEPTH}"
        )
        self.logger.info(
            "CHK-DEPTH PASS: max call depth %d (resync notes %d)",
            mon.max_depth,
            mon.resync_notes,
        )
