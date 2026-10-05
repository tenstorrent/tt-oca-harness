# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The CPU trace port shows the one breakpoint trap and the call chain that the firmware reports.

The test boots fw/tests/cpu_trace_diag_test, which runs a known noinline call chain
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
  * CHK-DEPTH      -- while the trap frame is live, the shadow call stack
    held exactly the named chain, resolved through the firmware symbol
    listing: crt0 (_start) -> main -> diag_leaf1 -> diag_leaf2 -> diag_leaf3,
    then the breakpoint trap inside diag_leaf3. Each call frame's call site
    must lie in the caller and its target must be the callee's entry.

Standard boot-scoreboard checks (banner + firmware PASS + PC advance) apply on
top. The firmware image is fw/build/tests/cpu_trace_diag_test/*.{itcm,dtcm}.hex,
built by the c_compile stage (make dv-fw-tests TEST=cpu_trace_diag_test).

Stimulus is deterministic, because the checks need a known call chain and trap
site. The seeded clock-timing randomization from sep_base_test still applies.
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
# Trap-live shadow stack, outermost first: one (caller, callee) pair per
# linking call, then the trap frame inside the innermost callee. The crt0 entry
# symbol is _start (fw/startup/crt0.s `call main`); the rest is the noinline
# chain in fw/tests/cpu_trace_diag_test/cpu_trace_diag_test.c.
_CALL_CHAIN = (
    ("_start", "main"),
    ("main", "diag_leaf1"),
    ("diag_leaf1", "diag_leaf2"),
    ("diag_leaf2", "diag_leaf3"),
)
_TRAP_FUNC = "diag_leaf3"
_MCAUSE_BREAKPOINT = 3
_CHAIN_SYMBOLS = ("diag_leaf1", "diag_leaf2", "diag_leaf3", "main")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
_MAX_RUN_CYCLES = 2_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 2_000


@pyuvm.test()
class sep_cpu_trace_diag_test(sep_base_test):
    """The trace reconstruction of trap, chain and depth matches the firmware ground truth."""

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

        # CHK-DEPTH: the snapshot taken at the breakpoint push, not the
        # run-global max. Every frame is named through the symbol listing, so
        # a stale frame left by a missed return, a missing level, or a trap
        # outside diag_leaf3 fails here even when the depth still matches.
        def _func(pc) -> str:
            # Function that contains pc (call site or trap PC).
            return "<unfilled>" if pc is None else mon.symbols.lookup(pc).split("+")[0]

        def _entry(pc) -> str:
            # Exact symbol at pc; an offset means pc is not a function entry.
            return "<unfilled>" if pc is None else mon.symbols.lookup(pc)

        got_frames = [
            ("call", _func(f[1]), _entry(f[2])) if f[0] == "call" else (f[0], _func(f[1]))
            for f in mon.trap_stack
        ]
        want_frames = [("call", caller, callee) for caller, callee in _CALL_CHAIN]
        want_frames.append(("trap", _TRAP_FUNC))
        assert got_frames == want_frames, (
            f"CHK-DEPTH FAIL: trap-live shadow stack {got_frames} "
            f"(depth {mon.trap_depth}) is not the named chain {want_frames}"
        )
        self.logger.info(
            "CHK-DEPTH PASS: trap-live stack is %s -> trap in %s, depth %d "
            "(run-global max %d, resync notes %d)",
            " -> ".join([_CALL_CHAIN[0][0]] + [callee for _, callee in _CALL_CHAIN]),
            _TRAP_FUNC,
            mon.trap_depth,
            mon.max_depth,
            mon.resync_notes,
        )
