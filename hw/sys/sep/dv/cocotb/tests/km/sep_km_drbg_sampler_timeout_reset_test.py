# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KM DRBG sampler: read timeout, warm reset of a pending read, and the live control.

no_cpu / +skip_fuse_sense / +esrc_noise_force /
+km_rom_hex=km_rom_drbg_sampler.parhex. Directed: the image carries one
CFG.TIMEOUT value. Not ``rom_main``: only code on the KM CPU reads the sampler.

Contract. ``hw/ip/key_manager/doc/architecture.adoc`` (DRBG sampler, Errors and
reset) and ``km_drbg_sampler.rdl``: the counter loads ``CFG.TIMEOUT - 1`` and an
active ``DATA`` read times out after exactly ``CFG.TIMEOUT`` active cycles;
``ST_REQUEST`` asserts TREADY; a timeout completes the read with SLVERR and zero
data, sets the sticky ``STATUS.TIMEOUT_ERR``, increments ``COUNT_BAD`` and pulses
the KMCSR DRBG error source (``IRQ_STATUS.DRBG_ERR``); ``TIMEOUT = 0`` disables
the timeout. A warm or cold KM reset restores configuration defaults, counters,
error bits and request control. ``reset_controller.adoc`` (Resetting the Key
Manager) makes the sequenced KM reset the KM warm reset, and ``km_csr.rdl``
keeps ``BOOT_STATUS.COLD_BOOT_DONE`` across it.

The entropy chain stays at its reset (CSRNG and EDN disabled) until the control
leg, so no beat reaches the KM before then. The host watches the sampler's
TREADY on ``km_entropy_tready_o`` and the image's KM SRAM dump. Each TREADY
checker also fails on any X/Z TREADY, or X/Z TVALID while TREADY is not low,
in its own window, since an unknown read as 0 is the passing value.

  CHK-SMP-TIMEOUT        the timed-out read: TREADY high for exactly
                         TIMEOUT_CYCLES with no handshake; DATA read 0; the
                         load set AXI_SLVERR and DRBG_ERR; STATUS has
                         TIMEOUT_ERR=1, STREAM_ERR=0, COUNT_BAD=1, COUNT_GOOD=0.
  CHK-SMP-NO-TIMEOUT     with CFG = 0 the read holds TREADY with no handshake
                         for four reset timeout budgets and does not complete.
  CHK-SMP-WARM-CANCEL    the sequenced KM reset drops TREADY while the read is
                         pending, and TREADY stays low while the reset is held.
  CHK-SMP-WARM-RESET     after the reset the image runs its warm path
                         (COLD_BOOT_DONE=1), and CFG, STATUS and the DRBG
                         IRQ_STATUS bit read their RDL resets, although the
                         image left CFG=0 and TIMEOUT_ERR, COUNT_BAD and
                         DRBG_ERR set.
  CHK-SMP-CONTROL        control: the same TIMEOUT_CYCLES budget with a beat
                         waiting (DRBG_READY=1) completes OKAY in one handshake
                         and less than the budget; DATA equals the word on the
                         KM AXI-Stream; no error bit sets; COUNT_GOOD=1.
  CHK-ALERTS-ZERO        after the control leg, CSRNG and EDN ERR_CODE and
                         RECOV_ALERT_STS read zero, so the control beat came
                         from a chain with no error.

The control leg makes the timeout leg discriminating: same image, same budget,
same DATA load, differing only in whether the chain delivers. Expected values
come from the RDL resets in the generated headers and from the AXI-Stream word
the DUT handed the KM.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from sep_base_test import sep_base_test
from seq_lib.sep_km_drbg_sampler_seq import (
    CFG_RESET,
    COLD_BOOT_DONE,
    DUMP_WORDS,
    IRQ_AXI_DECERR,
    IRQ_AXI_SLVERR,
    IRQ_DRBG_ERR,
    IRQ_WATCHED,
    MK_BLOCK,
    MK_DONE,
    MK_WARM,
    STATUS_RESET,
    TIMEOUT_CYCLES,
    W_P_CFG,
    W_P_CLEAN,
    W_P_DATA,
    W_P_IRQ,
    W_P_STATUS,
    W_P_STATUS_PRE,
    W_R_CFG,
    W_R_STATUS,
    W_T_BOOT,
    W_T_CFG,
    W_T_CLEAN,
    W_T_DATA,
    W_T_IRQ,
    W_T_STATUS,
    W_T_STATUS_PRE,
    W_W_BOOT,
    W_W_CFG,
    W_W_IRQ,
    W_W_STATUS,
    WORD_BITS,
    WORD_MASK,
    SepKmTreadyMonitor,
    cfg_value,
    field,
    irq_names,
    status_str,
)
from seq_lib.sep_sw_reset_seq import SepSwReset

# Four reset timeout budgets: a read the disabled timeout did not hold would
# have ended long before this.
_HOLD_CYCLES = 4 * field("CFG_REG", "TIMEOUT", CFG_RESET)
_RESET_DROP_CYCLES = 500
_RESET_HOLD_CYCLES = 50
_MARKER_CYCLES = 40_000


@pyuvm.test()
class sep_km_drbg_sampler_timeout_reset_test(sep_base_test):
    """Sampler timeout, warm reset of a pending read, and a live control read."""

    required_evidence = (
        "CHK-SMP-TIMEOUT",
        "CHK-SMP-NO-TIMEOUT",
        "CHK-SMP-WARM-CANCEL",
        "CHK-SMP-WARM-RESET",
        "CHK-SMP-CONTROL",
        "CHK-ALERTS-ZERO",
    )

    async def _await_marker(self, marker: int, what: str) -> None:
        dut = cocotb.top
        word = 0
        for _ in range(_MARKER_CYCLES):
            await RisingEdge(dut.clk_i)
            word = self.rd(dut.km_sram_word0_o, allow_unknown=True)
            if word == marker:
                return
        raise AssertionError(
            f"KM image liveness FAIL: KM SRAM word0=0x{word:08x} after {_MARKER_CYCLES} "
            f"cycles, expected 0x{marker:08x} ({what}); KM ROM fetches="
            f"{self.rd(dut.km_rom_req_count_o)}"
        )

    def _dump(self, first: int, last: int) -> dict[int, int]:
        """KM SRAM words ``first..last``, each required fully known."""
        assert last < DUMP_WORDS
        mask = ((1 << (WORD_BITS * (last + 1 - first))) - 1) << (WORD_BITS * first)
        value = self.rd_known(cocotb.top.km_sram_probe_o, mask)
        return {i: (value >> (WORD_BITS * i)) & WORD_MASK for i in range(first, last + 1)}

    async def run_scenario(self) -> None:
        dut = cocotb.top
        await self.bring_up_no_cpu()
        if getattr(self, "swrst", None) is None:
            self.swrst = SepSwReset(self)
        mon = SepKmTreadyMonitor(self)
        mon.start()
        await self.swrst.release("km")

        # --- timeout leg + the pending read --------------------------------
        await self._await_marker(MK_BLOCK, "timeout leg dumped, reset-leg read issued")
        w = self._dump(W_T_BOOT, W_R_STATUS)
        self._check_timeout(w, mon)

        # The read stays pending: wait until TREADY has been high for the hold
        # window in the second run.
        for _ in range(_HOLD_CYCLES + _MARKER_CYCLES):
            await RisingEdge(dut.clk_i)
            if len(mon.runs) >= 2 and mon.high and mon.runs[1][1] >= _HOLD_CYCLES:
                break
        self._check_no_timeout(w, mon)

        # --- sequenced KM reset while the read is pending ------------------
        park_cycle = mon.cycle
        await self.swrst.park("km")
        for _ in range(_RESET_DROP_CYCLES):
            await RisingEdge(dut.clk_i)
            if not mon.high:
                break
        drop_cycle = mon.cycle
        runs_at_drop = len(mon.runs)
        await ClockCycles(dut.clk_i, _RESET_HOLD_CYCLES)
        xz = mon.take_xz()
        faults = []
        if xz:
            faults.append(f"{xz} cycle(s) with TREADY or TVALID X/Z")
        if mon.high or drop_cycle - park_cycle >= _RESET_DROP_CYCLES:
            faults.append(
                f"TREADY still high {drop_cycle - park_cycle} cycles after the KM reset write"
            )
        if len(mon.runs) != runs_at_drop or mon.high:
            faults.append("TREADY rose again while the KM reset was held")
        if mon.runs[1][2]:
            faults.append(f"the pending read took {mon.runs[1][2]} handshake(s)")
        assert not faults, "CHK-SMP-WARM-CANCEL FAIL: " + "; ".join(faults)
        self.logger.info(
            "CHK-SMP-WARM-CANCEL PASS: pending read held TREADY %d cycles; TREADY fell "
            "%d cycles after the SW_RESET_N KM park write and stayed low for %d held cycles; "
            "X/Z cycles=%d",
            mon.runs[1][1],
            drop_cycle - park_cycle,
            _RESET_HOLD_CYCLES,
            xz,
        )
        await self.swrst.release("km")

        # --- warm path -----------------------------------------------------
        await self._await_marker(MK_WARM, "warm-path dump")
        w.update(self._dump(W_W_BOOT, W_W_IRQ))
        self._check_warm_reset(w)

        # --- control leg: the chain delivers -------------------------------
        await self.bring_up_entropy(strict=True, score_km=True)
        self.start_fifo_drain()
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        await self._await_marker(MK_DONE, "control-leg dump")
        w.update(self._dump(W_P_CFG, W_P_STATUS))
        mon.stop()
        self._check_control(w, mon)

        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report()

    def _check_timeout(self, w: dict[int, int], mon: SepKmTreadyMonitor) -> None:
        want_cfg = cfg_value(TIMEOUT=TIMEOUT_CYCLES, PREFETCH=0)
        pre = []
        if w[W_T_BOOT] & COLD_BOOT_DONE:
            pre.append(f"BOOT_STATUS=0x{w[W_T_BOOT]:08x} on the first boot")
        if w[W_T_STATUS_PRE] != STATUS_RESET:
            pre.append(
                f"STATUS=0x{w[W_T_STATUS_PRE]:08x} ({status_str(w[W_T_STATUS_PRE])}) before "
                f"the read, expected the RDL reset 0x{STATUS_RESET:08x}"
            )
        if w[W_T_CFG] != want_cfg:
            pre.append(f"CFG read 0x{w[W_T_CFG]:08x} after the image wrote 0x{want_cfg:08x}")
        if w[W_T_CLEAN] & IRQ_WATCHED:
            pre.append(f"IRQ_STATUS=0x{w[W_T_CLEAN]:08x} after the clear")
        assert not pre, "CHK-SMP-TIMEOUT FAIL (precondition): " + "; ".join(pre)

        st = w[W_T_STATUS]
        irq = w[W_T_IRQ]
        xz = mon.take_xz()
        faults = []
        if xz:
            faults.append(f"{xz} cycle(s) with TREADY or TVALID X/Z")
        if not mon.runs:
            faults.append("TREADY never rose for the DATA read")
        else:
            start, length, hs = mon.runs[0]
            if length != TIMEOUT_CYCLES:
                faults.append(f"TREADY high {length} cycles, expected CFG.TIMEOUT={TIMEOUT_CYCLES}")
            if hs:
                faults.append(f"{hs} handshake(s) while the chain was disabled")
        if w[W_T_DATA] != 0:
            faults.append(f"DATA read 0x{w[W_T_DATA]:08x}, expected 0")
        if irq & (IRQ_AXI_SLVERR | IRQ_DRBG_ERR) != IRQ_AXI_SLVERR | IRQ_DRBG_ERR or (
            irq & IRQ_AXI_DECERR
        ):
            faults.append(
                f"IRQ_STATUS=0x{irq:08x} ({irq_names(irq)}), expected AXI_SLVERR|DRBG_ERR"
            )
        got = {
            n: field("STATUS_REG", n, st)
            for n in ("TIMEOUT_ERR", "STREAM_ERR", "COUNT_BAD", "COUNT_GOOD")
        }
        if got != {"TIMEOUT_ERR": 1, "STREAM_ERR": 0, "COUNT_BAD": 1, "COUNT_GOOD": 0}:
            faults.append(f"STATUS=0x{st:08x} ({status_str(st)})")
        assert not faults, (
            "CHK-SMP-TIMEOUT FAIL: architecture.adoc times an active read out after exactly "
            "CFG.TIMEOUT cycles with SLVERR, zero data, TIMEOUT_ERR, COUNT_BAD+1 and the "
            "DRBG error pulse: " + "; ".join(faults)
        )
        self.logger.info(
            "CHK-SMP-TIMEOUT PASS: before the read BOOT_STATUS=0x%08x (first boot), "
            "STATUS=0x%08x == RDL reset 0x%08x, IRQ_STATUS=0x%08x after the clear; "
            "CFG=0x%08x; TREADY high %d cycles (TIMEOUT=%d) from "
            "cycle %d, 0 handshakes, X/Z cycles=%d; DATA=0x%08x; IRQ_STATUS=0x%08x (%s); "
            "STATUS=0x%08x (%s)",
            w[W_T_BOOT],
            w[W_T_STATUS_PRE],
            STATUS_RESET,
            w[W_T_CLEAN],
            w[W_T_CFG],
            mon.runs[0][1],
            TIMEOUT_CYCLES,
            mon.runs[0][0],
            xz,
            w[W_T_DATA],
            irq,
            irq_names(irq),
            st,
            status_str(st),
        )

    def _check_no_timeout(self, w: dict[int, int], mon: SepKmTreadyMonitor) -> None:
        marker = self.rd(cocotb.top.km_sram_word0_o)
        xz = mon.take_xz()
        faults = []
        if xz:
            faults.append(f"{xz} cycle(s) with TREADY or TVALID X/Z")
        if w[W_R_CFG] != 0:
            faults.append(f"CFG read 0x{w[W_R_CFG]:08x} after the image wrote 0")
        if len(mon.runs) < 2 or not mon.high or mon.runs[1][1] < _HOLD_CYCLES:
            held = mon.runs[1][1] if len(mon.runs) >= 2 else 0
            faults.append(
                f"TREADY held {held} cycles (still high={mon.high}), expected >= {_HOLD_CYCLES}"
            )
        elif mon.runs[1][2]:
            faults.append(f"{mon.runs[1][2]} handshake(s) while the chain was disabled")
        if marker != MK_BLOCK:
            faults.append(f"KM SRAM word0=0x{marker:08x}: the read completed")
        assert not faults, (
            "CHK-SMP-NO-TIMEOUT FAIL: CFG.TIMEOUT=0 disables the timeout, so the read "
            "must stay in ST_REQUEST: " + "; ".join(faults)
        )
        self.logger.info(
            "CHK-SMP-NO-TIMEOUT PASS: CFG=0x%08x; TREADY held %d cycles (>= %d) with "
            "0 handshakes, X/Z cycles=%d; KM SRAM word0=0x%08x (read pending)",
            w[W_R_CFG],
            mon.runs[1][1],
            _HOLD_CYCLES,
            xz,
            marker,
        )

    def _check_warm_reset(self, w: dict[int, int]) -> None:
        before = w[W_R_STATUS]
        pre = []
        if (
            field("STATUS_REG", "TIMEOUT_ERR", before) != 1
            or field("STATUS_REG", "COUNT_BAD", before) != 1
        ):
            pre.append(f"STATUS=0x{before:08x} ({status_str(before)}) before the reset")
        assert not pre, (
            "CHK-SMP-WARM-RESET FAIL (precondition): the error state the reset must "
            "clear was not set: " + "; ".join(pre)
        )
        faults = []
        if not w[W_W_BOOT] & COLD_BOOT_DONE:
            faults.append(f"BOOT_STATUS=0x{w[W_W_BOOT]:08x}: not the warm path")
        if w[W_W_CFG] != CFG_RESET:
            faults.append(f"CFG=0x{w[W_W_CFG]:08x}, expected the RDL reset 0x{CFG_RESET:08x}")
        if w[W_W_STATUS] != STATUS_RESET:
            faults.append(
                f"STATUS=0x{w[W_W_STATUS]:08x} ({status_str(w[W_W_STATUS])}), expected the "
                f"RDL reset 0x{STATUS_RESET:08x}"
            )
        if w[W_W_IRQ] & IRQ_WATCHED:
            faults.append(f"IRQ_STATUS=0x{w[W_W_IRQ]:08x} ({irq_names(w[W_W_IRQ])})")
        assert not faults, (
            "CHK-SMP-WARM-RESET FAIL: a warm KM reset restores sampler configuration, "
            "counters and error bits: " + "; ".join(faults)
        )
        self.logger.info(
            "CHK-SMP-WARM-RESET PASS: BOOT_STATUS=0x%08x; CFG 0x%08x -> 0x%08x; "
            "STATUS 0x%08x (%s) -> 0x%08x; IRQ_STATUS=0x%08x",
            w[W_W_BOOT],
            w[W_R_CFG],
            w[W_W_CFG],
            before,
            status_str(before),
            w[W_W_STATUS],
            w[W_W_IRQ],
        )

    def _check_control(self, w: dict[int, int], mon: SepKmTreadyMonitor) -> None:
        want_cfg = cfg_value(TIMEOUT=TIMEOUT_CYCLES, PREFETCH=0)
        delivered = self.drbg_sb.km_words()
        pre = []
        if w[W_P_CFG] != want_cfg:
            pre.append(f"CFG read 0x{w[W_P_CFG]:08x} after the image wrote 0x{want_cfg:08x}")
        if not field("STATUS_REG", "DRBG_READY", w[W_P_STATUS_PRE]):
            pre.append(f"STATUS=0x{w[W_P_STATUS_PRE]:08x} before the read")
        if w[W_P_CLEAN] & IRQ_WATCHED:
            pre.append(f"IRQ_STATUS=0x{w[W_P_CLEAN]:08x} after the clear")
        assert not pre, "CHK-SMP-CONTROL FAIL (precondition): " + "; ".join(pre)

        st = w[W_P_STATUS]
        xz = mon.take_xz()
        faults = []
        if xz:
            faults.append(f"{xz} cycle(s) with TREADY or TVALID X/Z")
        if len(mon.runs) != 3:
            faults.append(f"{len(mon.runs)} TREADY runs, expected 3 (timeout, pending, control)")
        else:
            _, length, hs = mon.runs[2]
            if hs != 1 or length >= TIMEOUT_CYCLES:
                faults.append(f"TREADY high {length} cycles with {hs} handshake(s)")
        if not delivered or w[W_P_DATA] != delivered[0]:
            faults.append(
                f"DATA=0x{w[W_P_DATA]:08x}, KM AXI-Stream words {[hex(x) for x in delivered[:2]]}"
            )
        if w[W_P_IRQ] & IRQ_WATCHED:
            faults.append(f"IRQ_STATUS=0x{w[W_P_IRQ]:08x} ({irq_names(w[W_P_IRQ])})")
        got = {
            n: field("STATUS_REG", n, st)
            for n in ("TIMEOUT_ERR", "STREAM_ERR", "COUNT_BAD", "COUNT_GOOD")
        }
        if got != {"TIMEOUT_ERR": 0, "STREAM_ERR": 0, "COUNT_BAD": 0, "COUNT_GOOD": 1}:
            faults.append(f"STATUS=0x{st:08x} ({status_str(st)})")
        assert not faults, (
            "CHK-SMP-CONTROL FAIL: with a beat waiting the same budget must complete "
            "the read through ST_RESPOND: " + "; ".join(faults)
        )
        self.logger.info(
            "CHK-SMP-CONTROL PASS: CFG=0x%08x, DRBG_READY=1; TREADY high %d cycle(s), "
            "1 handshake, X/Z cycles=%d; DATA=0x%08x == KM AXI-Stream word; "
            "IRQ_STATUS=0x%08x; STATUS=0x%08x (%s)",
            w[W_P_CFG],
            mon.runs[2][1],
            xz,
            w[W_P_DATA],
            w[W_P_IRQ],
            st,
            status_str(st),
        )
