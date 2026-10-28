# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Each inbound mailbox threshold interrupt reaches the CPU on PIC source ch+1 and not the SMC line.

OCAH provenance: ``sep_mailbox_plic_test`` checks mailbox interrupt delivery
through the PIC to the CPU.

The test boots the VeeR EL2 core and runs the mailbox_plic firmware, which walks all eight
inbound mailbox channels (axil_mailbox @ 0x10A0_0800, stride 0x1000). Each channel self-triggers its
threshold interrupt by pushing a word into that FIFO, and proves the interrupt
reaches the CPU through the VeeR PIC (WFI + ISR):
PIC source ``ch+1`` (``interrupts.adoc`` Mailbox interrupt ``ch``) -> CPU trap
-> ISR.

Like the other FW-boot tests this is firmware-self-checking: the firmware
returns its error count and fw/startup/crt0.s emits the PASS (0xCAFEBABE) / FAIL
(0xDEADBEEF) magic on the 0x8000_0000 mailbox, which the boot scoreboard gates
on. The firmware self-checks the exact PIC claim id (== ch+1), the asserted IRQP/
IRQS write bit, the IRQS/IRQP W1C-clear readback, and the absence of an
interrupt storm; a failed check makes fw/startup/crt0.s emit FAIL. The host also counts
eight ``CHK-DELIVER`` / ``CHK-RW1C`` / ``CHK-NOSTORM`` lines so a skip of one
channel cannot hide behind the PASS magic. The scoreboard also checks the
firmware banner and that the core executed out of ICCM.

The host also grades the direction:
  CHK-DIRECTION : the firmware's outbound channel-0 push raises none of the eight
                  inbound PIC sources.
  CHK-SMC-LINE  : no inbound pending interrupt appears on smc_mailbox_interrupt_o,
                  and the outbound channel-0 push leaves exactly bit 0 set.

Half-zero legs (the half of WRITE_DATA that a 32-bit store does not write):
``doc/programmer/src/sep-smc-common.adoc:435-437`` states that SEP writes to
the mailbox write zeroes to the half of the data register not written, and
``hw/ip/axi_lite_mailbox_unit/regs/axil_mailbox.rdl:24-26`` states that byte
lanes whose strobe is 0 are pushed as 0. After the direction leg the firmware
stores one drawn word with a 32-bit ``sw`` to the low half of the outbound
``WRITE_DATA`` of one drawn mailbox, then to the high half of another, and
after each store spins with no mailbox access while the bench pops the entry
with one 64-bit read of the inbound ``READ_DATA`` of the same mailbox
(external master, through an inbound filter window the firmware opens). The
CPU drives 0 on the unstrobed lanes, so the bench mailbox lane inject
(``mbox_lane_inject_*_i``, docs/SEP_TB_ARCH.adoc) puts a drawn non-zero value
on the unstrobed lanes of that W beat at the mailbox unit port.

  CHK-HALF-ZERO-LANES : on the mailbox unit AW/W tap (``mbox_axil_*_o``) the
                        beat of the leg has WSTRB 0x0F (low) or 0xF0 (high), its
                        strobed half equals the drawn word and its unstrobed
                        half equals the drawn non-zero inject value, and the
                        pop of the earlier leg is complete; else CTRL-MISSING.
  CHK-HALF-ZERO       : the 64-bit pop returns exactly ``word << (32 * half)``:
                        the written half holds the word and the other half
                        reads 0. Both legs must grade.
  OBS-HALF-ZERO-RESP  : the response of each pop, logged only (no TT text
                        states the response of a pop of a non-empty FIFO).

The graded window of this leaf opens once the CPU is released and closes after
the console is parsed; the first FAIL closes it at once.

No fuse data is read, so the testlist entry uses ``+skip_fuse_sense``.
"""

from __future__ import annotations

import os
from collections import deque
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import (
    ClockCycles,
    Edge,
    FallingEdge,
    First,
    NextTimeStep,
    ReadOnly,
    RisingEdge,
)
from cocotb.utils import get_sim_time
from env.sep_axi_agent import SepAxiAgent
from env.sep_axi_monitor import SepAxiMonitor
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_dtcm_param_patch import patch_param_block
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_seeded_rng import SepSeededRng
from env.sep_spec_tables import pic
from sep_base_test import sep_base_test
from sep_reg_meta import sym
from seq_lib.sep_mailbox_walk_seq import MAILBOX_COUNT
from seq_lib.sep_mbox_port_ops import SepMboxPortOps, resp_name

_TEST = "sep_mailbox_plic_test"
_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "mailbox_plic_test")
_ITCM_HEX = os.path.join(_FW_DIR, "mailbox_plic_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "mailbox_plic_test.dtcm.hex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
# Arm + trigger + ISR + a 256-iteration quiet window, eight channels, then two
# half-zero legs; the run loop early-exits on fw_done, so this is an upper bound.
_MAX_RUN_CYCLES = 8_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_BANNER = "SEP mailbox PLIC test"
_MBOX_N = pic("Mailbox interrupt 7")

# g_hz in fw/tests/mailbox_plic_test/mailbox_plic_test.c: the magic, then the
# mailbox and the word of the low-half leg, then of the high-half leg.
_HZ_MAGIC = 0x6A2F1D93
_HALF_BITS = 32
_HALF_MASK = (1 << _HALF_BITS) - 1
# WSTRB of a 32-bit store at each half of the 64-bit WRITE_DATA beat.
_HALF_STRB = (0x0F, 0xF0)
# Mailbox 0 is left out of the draw: the direction leg leaves one entry in its
# outbound FIFO, and each half-zero leg pushes into an empty FIFO.
_HZ_FIRST_MBX = 1
# Bound on the wait for the last pop after the firmware ends (clk_i cycles; no
# spec bound, a pop still open at the bound is a FAIL).
_HZ_POP_WAIT_CYCLES = 20_000


def _draw_hz(seed: int) -> dict[str, int]:
    """Mailboxes, words and inject value of the half-zero legs, a pure function of the seed."""
    rng = SepSeededRng(seed)
    m_lo, m_hi = rng.sample(range(_HZ_FIRST_MBX, MAILBOX_COUNT), 2)
    return {
        "m_lo": m_lo,
        "word_lo": rng.randrange(1, 1 << _HALF_BITS),
        "m_hi": m_hi,
        "word_hi": rng.randrange(1, 1 << _HALF_BITS),
        # Unstrobed-lane value: both halves non-zero, so each leg carries a
        # non-zero value on the half it does not write.
        "inj": (rng.randrange(1, 1 << _HALF_BITS) << _HALF_BITS)
        | rng.randrange(1, 1 << _HALF_BITS),
    }


@pyuvm.test()
class sep_mailbox_plic_test(sep_base_test):
    """Inbound mailbox interrupts reach the PIC with the exact claim id and skip the SMC line."""

    build_env = False
    required_evidence = ("CHK-HALF-ZERO", "CHK-HALF-ZERO-LANES")

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)
        # The CPU owns the CPU-LSU port; the SMN master pops the half-zero entries.
        self.ext_agent = SepAxiAgent("ext_axi_agent", self)
        self.ext_agent.axi_prefix = "m_axi"
        self.ext_monitor = SepAxiMonitor("ext_axi_monitor", self)
        self.ext_monitor.bus_prefix = "m_axi"

    async def start_ext_seq(self, seq) -> None:
        await seq.start(self.ext_agent.sequencer)

    def _stage_dtcm(self) -> tuple[str, dict[str, int]]:
        seed = self.random_seed()
        hz = _draw_hz(seed)
        patched = os.path.join(os.getcwd(), "sep_dtcm_mailbox_plic.hex")
        patch_param_block(
            _DTCM_HEX,
            patched,
            _HZ_MAGIC,
            [_HZ_MAGIC, hz["m_lo"], hz["word_lo"], hz["m_hi"], hz["word_hi"]],
        )
        self.logger.info(
            "MBOX-HZ RANDCFG seed=%d m_lo=%d word_lo=0x%08x m_hi=%d word_hi=0x%08x inj=0x%016x",
            seed,
            hz["m_lo"],
            hz["word_lo"],
            hz["m_hi"],
            hz["word_hi"],
            hz["inj"],
        )
        return patched, hz

    def _hz_fail(self, msg: str) -> None:
        """Record a half-zero FAIL; the first one closes the graded window at once."""
        if not self.hz_err:
            close_graded_window(self.logger)
        self.hz_err.append(msg)
        self.logger.error(msg)

    async def _hz_pop(self, leg: dict) -> None:
        """Pop the entry of ``leg`` with one 64-bit read of the inbound READ_DATA and grade it."""
        half = leg["half"]
        # Leave the read-only phase of the beat before the master drives.
        await RisingEdge(cocotb.top.clk_i)
        try:
            resp, data = await self.hz_ops[half].pop("in")
        except Exception as exc:
            leg["popped"] = True
            self._hz_fail(f"CHK-HALF-ZERO FAIL: {leg['name']} pop raised {exc!r}")
            return
        leg["popped"] = True
        word = leg["word"]
        exp = word << (_HALF_BITS * half)
        written = (data >> (_HALF_BITS * half)) & _HALF_MASK
        other = (data >> (_HALF_BITS * (1 - half))) & _HALF_MASK
        self.logger.info(
            "OBS-HALF-ZERO-RESP LOG %s m=%d resp=%s", leg["name"], leg["m"], resp_name(resp)
        )
        line = (
            f"{leg['name']} m={leg['m']} half={half} "
            f"rdata=0x{data:016x} exp=0x{exp:016x} written=0x{written:08x} "
            f"word=0x{word:08x} other=0x{other:08x} "
            f"w_unstrobed=0x{leg['w_unstrobed']:08x} clk={self.hz_clk}"
        )
        if data != exp:
            self._hz_fail(f"CHK-HALF-ZERO FAIL: {line}")
            return
        leg["graded"] = True
        self.logger.info("CHK-HALF-ZERO PASS: %s", line)

    async def _hz_watch(self) -> None:
        """Follow the mailbox unit AW and W taps; grade the beat of each leg and start its pop.

        The taps are read in the read-only phase after each falling edge. The
        lane inject forces the W data on the falling edge before the rising
        edge at which the mailbox unit takes the beat, so a read after the
        rising edge shows the beat before the force. A handshake seen after a
        falling edge is the one the mailbox unit takes at the next rising
        edge, with the data it takes. A FAIL leaves the read-only phase before
        it closes the graded window.
        """
        dut = cocotb.top
        # AXI keeps W beats in AW order, so each W beat belongs to the oldest
        # accepted write address.
        aw_q: deque[int] = deque()
        by_addr = {leg["addr"]: leg for leg in self.hz_legs}
        while True:
            await FallingEdge(dut.clk_i)
            await ReadOnly()
            self.hz_clk += 1
            if self.rd_known(dut.mbox_axil_aw_hs_o):
                aw_q.append(self.rd_known(dut.mbox_axil_aw_addr_o))
            if not self.rd_known(dut.mbox_axil_w_hs_o):
                continue
            if not aw_q:
                await NextTimeStep()
                self._hz_fail(
                    "CHK-HALF-ZERO-LANES FAIL: a W beat at the mailbox unit port has no "
                    f"accepted write address at or before it (clk={self.hz_clk})"
                )
                continue
            leg = by_addr.get(aw_q.popleft())
            if leg is None:
                continue
            strb = self.rd_known(dut.mbox_axil_w_strb_o)
            wdata = self.rd_known(dut.mbox_axil_w_data_o)
            half = leg["half"]
            strobed = (wdata >> (_HALF_BITS * half)) & _HALF_MASK
            unstrobed = (wdata >> (_HALF_BITS * (1 - half))) & _HALF_MASK
            inj_half = (self.hz["inj"] >> (_HALF_BITS * (1 - half))) & _HALF_MASK
            prev_popped = all(p["popped"] for p in self.hz_legs if p["seen"])
            leg["seen"] = True
            leg["w_unstrobed"] = unstrobed
            line = (
                f"{leg['name']} m={leg['m']} half={half} addr=0x{leg['addr']:08x} "
                f"strb=0x{strb:02x} exp_strb=0x{_HALF_STRB[half]:02x} wdata=0x{wdata:016x} "
                f"strobed=0x{strobed:08x} word=0x{leg['word']:08x} "
                f"unstrobed=0x{unstrobed:08x} inj=0x{inj_half:08x} "
                f"prev_popped={prev_popped} clk={self.hz_clk}"
            )
            if (
                strb != _HALF_STRB[half]
                or strobed != leg["word"]
                or unstrobed != inj_half
                or not prev_popped
            ):
                leg["popped"] = True
                await NextTimeStep()
                self._hz_fail(f"CHK-HALF-ZERO-LANES FAIL: CTRL-MISSING {line}")
                continue
            self.logger.info("CHK-HALF-ZERO-LANES PASS: %s", line)
            cocotb.start_soon(self._hz_pop(leg))

    async def run_scenario(self) -> None:
        dut = cocotb.top
        # Override the boot scoreboard's expected banner here (after its own
        # build_phase, which resets it to the hello_world default).
        self.sb.expected_line = _BANNER
        dtcm, self.hz = self._stage_dtcm()
        self.hz_err: list[str] = []
        self.hz_clk = 0
        # Index = half: the low-half leg on mailbox m_lo, the high-half leg on m_hi.
        self.hz_ops = (
            SepMboxPortOps(self, self.hz["m_lo"], in_prot1=0, in_user=0),
            SepMboxPortOps(self, self.hz["m_hi"], in_prot1=0, in_user=0),
        )
        self.hz_legs = [
            {
                "name": name,
                "m": self.hz[m_key],
                "half": half,
                "word": self.hz[w_key],
                # 8-byte WRITE_DATA address of the AW beat (a 32-bit store at
                # either half carries the address of its half).
                "addr": self.hz_ops[half].addr("out", "WRITE_DATA", half=half),
                "seen": False,
                "popped": False,
                "graded": False,
                "w_unstrobed": 0,
            }
            for name, m_key, w_key, half in (
                ("lo", "m_lo", "word_lo", 0),
                ("hi", "m_hi", "word_hi", 1),
            )
        ]

        # Baseline: the SMC-facing line is idle once reset is released and
        # before the firmware pushes anything, so a 1 at the end of the run is
        # this run's doing. Sampled in the post-bring-up hook rather than at
        # time 0: under a four-state simulator the port is X before reset, and
        # a compare there would raise on a healthy run.
        smc_irq = cocotb.top.smc_mailbox_interrupt_o
        irq_vec = cocotb.top.sep_internal_interrupts_probe_o
        inbound_mask = (1 << _MBOX_N) - 1
        # Inbound channel ch drives sep_internal_interrupts[ch] (PIC source ch+1,
        # interrupts.adoc). Every change of that vector or of the SMC-facing
        # line is sampled, so each inbound pending window is seen while it is
        # open, not after the firmware has cleared it.
        inbound_seen = [False] * _MBOX_N
        leaks: list[str] = []

        async def _watch_inbound_vs_smc_line() -> None:
            while True:
                await First(Edge(irq_vec), Edge(smc_irq))
                await ReadOnly()
                inbound = self.rd_known(irq_vec, inbound_mask) & inbound_mask
                smc_now = self.rd_known(smc_irq) & inbound_mask
                for ch in range(_MBOX_N):
                    if (inbound >> ch) & 1:
                        inbound_seen[ch] = True
                        if (smc_now >> ch) & 1:
                            leaks.append(
                                f"inbound ch{ch} pending and smc_mailbox_interrupt_o[{ch}]=1 "
                                f"at {get_sim_time('ns')} ns"
                            )

        async def _after_bring_up() -> None:
            assert self.rd_known(smc_irq) == 0, (
                "smc_mailbox_interrupt_o is already asserted after reset; the "
                "end-of-run check below could not attribute it to the outbound push"
            )
            cocotb.start_soon(_watch_inbound_vs_smc_line())
            # The CPU is released; the half-zero pushes and pops of this run
            # are the graded stimulus of this leaf.
            open_graded_window(_TEST, self.logger)
            dut.mbox_lane_inject_mbx_i.value = (1 << self.hz["m_lo"]) | (1 << self.hz["m_hi"])
            dut.mbox_lane_inject_data_i.value = self.hz["inj"]
            dut.mbox_lane_inject_arm_i.value = 1
            cocotb.start_soon(self._hz_watch())

        try:
            await self.boot_firmware(
                self.sb,
                _ITCM_HEX,
                dtcm,
                rst_vec=_ICCM_BASE >> 1,
                max_run_cycles=_MAX_RUN_CYCLES,
                no_boot_cycles=_NO_BOOT_CYCLES,
                progress_every=_PROGRESS_EVERY,
                after_bring_up_hook=_after_bring_up,
            )
            # Bounded wait for a pop still in flight; a leg never seen fails below.
            for _ in range(_HZ_POP_WAIT_CYCLES):
                if all(leg["popped"] or not leg["seen"] for leg in self.hz_legs):
                    break
                await ClockCycles(dut.clk_i, 1)
            await RisingEdge(dut.clk_i)
            dut.mbox_lane_inject_arm_i.value = 0
            self._grade_console_and_hz()
        finally:
            close_graded_window(self.logger)

        # Direction, observed rather than reported. The spec gives PIC sources
        # 1-8 to the SMC-to-SEP (inbound) mailbox channels
        # (hw/sys/sep/doc/interrupts.adoc) and gives smc_mailbox_interrupt_o to
        # the mailbox interrupts toward the SMC (hw/sys/sep/doc/port_table.adoc).
        # The firmware left its outbound channel-0 entry pending and cleared
        # every inbound one, so bit 0 must be set and the rest clear. An
        # outbound push routed to the PIC instead leaves this line at 0. The
        # half-zero legs push into outbound FIFOs whose interrupt enable keeps
        # its reset value, and the bench pops each entry.
        console = self.sb.console_text()
        assert "CHK-DIRECTION PASS:" in console, (
            "firmware console has no CHK-DIRECTION line, so the outbound push "
            f"never ran or reached the CPU. Console was:\n{console}"
        )
        # Positive control: every inbound interrupt was observed pending, so the
        # leak check below ran inside each window rather than on an idle line.
        missing = [ch for ch in range(_MBOX_N) if not inbound_seen[ch]]
        assert not missing, (
            f"CHK-SMC-LINE FAIL: inbound mailbox interrupt(s) {missing} were never seen "
            "pending on sep_internal_interrupts; the per-window check did not run"
        )
        assert not leaks, "CHK-SMC-LINE FAIL: " + "; ".join(leaks)
        smc_bits = self.rd_known(smc_irq)
        assert smc_bits == 0b1, (
            f"smc_mailbox_interrupt_o = 0b{smc_bits:08b}, expected 0b00000001: "
            "bit 0 is the pending outbound push, and the inbound pushes "
            "that reached the CPU must not appear on this line at all"
        )
        self.logger.info(
            "CHK-SMC-LINE PASS: all %d inbound interrupts were seen pending with "
            "smc_mailbox_interrupt_o clear of each, and the outbound push left "
            "0b%s at the end",
            _MBOX_N,
            f"{smc_bits:08b}",
        )

    def _grade_console_and_hz(self) -> None:
        """Grade the firmware console and the half-zero legs; a FAIL closes the window first."""
        console = self.sb.console_text()
        errs: list[str] = list(self.hz_err)
        for label in ("CHK-DELIVER PASS:", "CHK-RW1C PASS:", "CHK-NOSTORM PASS:"):
            got = console.count(label)
            if got != _MBOX_N:
                errs.append(
                    f"firmware emitted {got} {label!r} lines, expected {_MBOX_N} "
                    "(one per inbound mailbox channel)"
                )
        if not (self.sb.fw_done and self.sb.fw_pass):
            errs.append(
                "firmware did not signal a PASS verdict; the console needles above "
                "are not a verdict on their own"
            )
        for leg in self.hz_legs:
            fw_line = f"HZ-LEG m=0x{leg['m']:08x} half=0x{leg['half']:08x} word=0x{leg['word']:08x}"
            if fw_line not in console:
                errs.append(
                    f"CHK-HALF-ZERO FAIL: firmware console has no {fw_line!r} line, so the "
                    f"{leg['name']} leg did not run with the patched parameters"
                )
        # Live minimum: both legs graded, one per half.
        graded = sum(1 for leg in self.hz_legs if leg["graded"])
        if graded != len(self.hz_legs):
            errs.append(
                f"CHK-HALF-ZERO FAIL: {graded} of {len(self.hz_legs)} half-zero legs graded "
                f"(seen={[leg['seen'] for leg in self.hz_legs]} "
                f"popped={[leg['popped'] for leg in self.hz_legs]})"
            )
        if errs:
            close_graded_window(self.logger)
            raise AssertionError("; ".join(errs))
        self.logger.info(
            "CHK-DELIVER PASS: all %d inbound mailbox channels reached the CPU "
            "with RW1C clear and no storm",
            _MBOX_N,
        )
