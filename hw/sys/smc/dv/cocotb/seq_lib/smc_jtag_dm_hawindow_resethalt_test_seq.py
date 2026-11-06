# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CPU Debug Module hart array mask (hawindow) selection and halt-on-reset over the DMI.

Spec sources: hw/sys/smc/doc/cpu.adoc (Debug Module Configuration: the hawindowsel,
hawindow, setresethaltreq and clrresethaltreq sentences and the DMI register inventory
table), RISC-V External Debug Support 0.13.2 sections 3.12.1, 3.12.4 and 3.12.5,
hw/sys/smc/regs/blocks/cpu_ctrl/cpu_ctrl.rdl (RESET_CTRL core reset pulses).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time

from .smc_addr_map import smc_addr
from .smc_cpu_vip_utils import (
    CPU_CTRL_RESET_CTRL,
    CPU_RESET_CTRL_DEBUG_RELEASE,
    cpu_ctrl_u32,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_jtag_protocol_vip import SmcJtagTap

DEBUG_RESET_N = cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__DEBUG_RESET_N_N0_SCAN_bm")
CORE1_PULSE = cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__CORE1_RESET_PULSE_START_N0_SCAN_bm")
CORE2_PULSE = cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__CORE2_RESET_PULSE_START_N0_SCAN_bm")
PULSE_COUNT = smc_addr("SMC_TOP_SMC_CPU_CTRL_CORE_RESET_PULSE_COUNT_BASE_ADDR")
DONE_BP = cpu_ctrl_u32("CPU_CTRL__CORE_RESET_PULSE_COUNT__CORE_RESETS_DONE_bp")
DONE_BM = cpu_ctrl_u32("CPU_CTRL__CORE_RESET_PULSE_COUNT__CORE_RESETS_DONE_bm")
PRE_BP = cpu_ctrl_u32("CPU_CTRL__CORE_RESET_PULSE_COUNT__PRE_RESET_COUNT_bp")
POST_BP = cpu_ctrl_u32("CPU_CTRL__CORE_RESET_PULSE_COUNT__POST_RESET_COUNT_bp")
# A hold long enough for SEP_IN polling to read core_resets_done low while the pulse runs.
HELD_PULSE = (8 << PRE_BP) | (64 << POST_BP)

NUM_HARTS = 4
DMI_DMCONTROL = 0x10
DMI_DMSTATUS = 0x11
DMI_HAWINDOWSEL = 0x14
DMI_HAWINDOW = 0x15
DMI_ABSTRACTCS = 0x16
DMI_HALTSUM0 = 0x40

DMCONTROL_DMACTIVE = 1 << 0
DMCONTROL_CLRRESETHALTREQ = 1 << 2
DMCONTROL_SETRESETHALTREQ = 1 << 3
DMCONTROL_HARTSELLO_SHIFT = 16
DMCONTROL_HASEL = 1 << 26
DMCONTROL_ACKHAVERESET = 1 << 28
DMCONTROL_RESUMEREQ = 1 << 30
DMCONTROL_HALTREQ = 1 << 31

DMSTATUS_ANYHALTED = 1 << 8
DMSTATUS_ALLHALTED = 1 << 9
DMSTATUS_ANYRUNNING = 1 << 10
DMSTATUS_ALLRUNNING = 1 << 11
DMSTATUS_ALLRESUMEACK = 1 << 17
DMSTATUS_ANYHAVERESET = 1 << 18
DMSTATUS_ALLHAVERESET = 1 << 19

ABSTRACTCS_BUSY = 1 << 12

ALL_ONES = 0xFFFF_FFFF
HAWINDOWSEL_ALL = 0x7FFF
HAWINDOW_MASK = (1 << NUM_HARTS) - 1
# (hawindow, hartsel): hartsel is inside the mask so the mask alone decides the others.
MASK_CASES = ((0b0110, 1), (0b1001, 0))
HALT_ON_RESET_HART = 1
CONTROL_PULSED_HART = 2

STEPS = tuple(f"S{i}" for i in range(1, 7))
CHK_AFTER_STEP = (
    ("CHK-DM-HAWINDOW-MASK", "S4"),
    ("CHK-DM-RESETHALTREQ-HALTS", "S5"),
)
FENCE_TERMS = {
    "S1": "RELEASED_ACTIVE",
    "S2": "HAWINDOW_READBACKS",
    "S3": "MASK_0110_HALTS_1_2",
    "S4": "MASK_1001_HALTS_0_3",
    "S5": "RESET_PULSE_HALTS_HART_1",
    "S6": "RESUMED",
}
_POLL_BOUND = 16
_CSR_POLL_BOUND = 64
VIP_FILE = "seq_lib/smc_jtag_protocol_vip.py"
VIP_DMI_BUSY_RETRIES = 4


def _dmcontrol(hartsel: int, *flags: int) -> int:
    word = DMCONTROL_DMACTIVE | (hartsel << DMCONTROL_HARTSELLO_SHIFT)
    for flag in flags:
        word |= flag
    return word


class smc_jtag_dm_hawindow_resethalt_test_seq(SmcCsrSeq):
    """Halt and resume hart sets through hawindow, then halt one hart on its reset pulse."""

    def __init__(self, name: str = "smc_jtag_dm_hawindow_resethalt_test_seq") -> None:
        super().__init__(name)
        self.dm_ok: bool = False
        self.haltsum_trace: list[int] = []
        self._tap: SmcJtagTap | None = None
        self._abits: int = 7
        self._idle: int = 5
        self._events: list[tuple[str, str, int]] = []
        self._last_dmi = 0
        self._last_dmstatus = 0
        self._polls: dict[str, int] = {}

    async def _dmi_read(self, addr: int) -> int:
        assert self._tap is not None
        value = await self._tap.dmi_read(addr, abits=self._abits, idle=self._idle)
        self._last_dmi = value
        if addr == DMI_DMSTATUS:
            self._last_dmstatus = value
        return value

    async def _dmi_write(self, addr: int, data: int) -> None:
        assert self._tap is not None
        await self._tap.dmi_write(addr, data, abits=self._abits, idle=self._idle)

    def _step_done(self, step: str) -> None:
        self._events.append(("step", step, int(get_sim_time("ps"))))

    def _chk(self, cid: str, text: str) -> None:
        cocotb.log.info("%s: %s", cid, text)
        self._events.append(("chk", cid, int(get_sim_time("ps"))))

    def _assert_fence(self) -> None:
        steps = [e for e in self._events if e[0] == "step"]
        assert [e[1] for e in steps] == list(STEPS), f"step order {[e[1] for e in steps]}"
        stamps = [e[2] for e in steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        chks = [e for e in self._events if e[0] == "chk"]
        assert [c[1] for c in chks] == [c for c, _ in CHK_AFTER_STEP], (
            f"checker order {[c[1] for c in chks]}"
        )
        index = {e: i for i, e in enumerate(self._events)}
        for chk, (cid, step) in zip(chks, CHK_AFTER_STEP):
            step_event = steps[STEPS.index(step)]
            assert index[chk] > index[step_event], f"{cid} printed before {step} completed"
            assert chk[2] >= step_event[2], f"{cid} printed before the {step} stamp"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(FENCE_TERMS[e[1]] for e in steps),
            ", ".join(c[1] for c in chks),
            ",".join(str(s) for s in stamps),
        )

    def _state(self) -> str:
        return f"last dmstatus=0x{self._last_dmstatus:08X} last DMI response=0x{self._last_dmi:08X}"

    async def _poll(self, label: str, addr: int, done) -> int:
        """Read addr until done(value) holds; raise after _POLL_BOUND reads."""
        for n in range(1, _POLL_BOUND + 1):
            value = await self._dmi_read(addr)
            if done(value):
                self._polls[label] = n
                return value
        raise AssertionError(
            f"{label}: not satisfied after {_POLL_BOUND} DMI reads of 0x{addr:02X}; {self._state()}"
        )

    async def _poll_haltsum(self, label: str, want: int) -> int:
        value = await self._poll(label, DMI_HALTSUM0, lambda v: (v & HAWINDOW_MASK) == want)
        self.haltsum_trace.append(value)
        return value

    async def _hart_status(self, hartsel: int) -> int:
        """Select one hart without hasel and return its dmstatus."""
        await self._dmi_write(DMI_DMCONTROL, _dmcontrol(hartsel))
        return await self._dmi_read(DMI_DMSTATUS)

    async def _all_status(self) -> list[int]:
        return [await self._hart_status(h) for h in range(NUM_HARTS)]

    @staticmethod
    def _halted_bits(status: list[int]) -> int:
        return sum(
            (1 << h)
            for h, word in enumerate(status)
            if word & DMSTATUS_ALLHALTED and not word & DMSTATUS_ANYRUNNING
        )

    @staticmethod
    def _running_bits(status: list[int]) -> int:
        return sum(
            (1 << h)
            for h, word in enumerate(status)
            if word & DMSTATUS_ALLRUNNING and not word & DMSTATUS_ANYHALTED
        )

    async def _mask_halt_resume(self, label: str, mask: int, hartsel: int) -> tuple[int, int, int]:
        """Halt the hawindow set through hasel, read every hart, resume the set; return
        (haltsum0 while halted, halted bits from dmstatus, haltsum0 after the resume)."""
        await self._dmi_write(DMI_HAWINDOW, mask)
        window = await self._dmi_read(DMI_HAWINDOW)
        assert window == mask, f"{label}: hawindow wrote 0b{mask:04b} read 0x{window:08X}"
        await self._dmi_write(
            DMI_DMCONTROL, _dmcontrol(hartsel, DMCONTROL_HASEL, DMCONTROL_HALTREQ)
        )
        halted_sum = await self._poll_haltsum(f"{label}_halt", mask)
        await self._dmi_write(DMI_DMCONTROL, _dmcontrol(hartsel, DMCONTROL_HASEL))
        status = await self._all_status()
        halted_bits = self._halted_bits(status)
        running_bits = self._running_bits(status)
        assert halted_bits == mask and running_bits == (~mask & HAWINDOW_MASK), (
            f"{label}: hawindow 0b{mask:04b} hartsel {hartsel} hasel: halted harts "
            f"0b{halted_bits:04b} running harts 0b{running_bits:04b} "
            f"dmstatus {[f'0x{w:08X}' for w in status]}"
        )
        await self._dmi_write(
            DMI_DMCONTROL, _dmcontrol(hartsel, DMCONTROL_HASEL, DMCONTROL_RESUMEREQ)
        )
        resumed_sum = await self._poll_haltsum(f"{label}_resume", 0)
        await self._dmi_write(DMI_DMCONTROL, _dmcontrol(hartsel, DMCONTROL_HASEL))
        await self._dmi_write(DMI_DMCONTROL, _dmcontrol(0))
        cocotb.log.info(
            "%s: hawindow 0b%s hartsel %d hasel: haltsum0=0x%08X in %d polls, dmstatus %s, "
            "haltsum0 after resumereq=0x%08X in %d polls",
            label,
            f"{mask:04b}",
            hartsel,
            halted_sum,
            self._polls[f"{label}_halt"],
            [f"0x{w:08X}" for w in status],
            resumed_sum,
            self._polls[f"{label}_resume"],
        )
        return halted_sum, halted_bits, resumed_sum

    async def _poll_resets_done(self, label: str, bits: int, want_low: bool) -> int:
        """Read CORE_RESET_PULSE_COUNT until core_resets_done has `bits` all clear (want_low)
        or all set; return the field; raise after _CSR_POLL_BOUND reads."""
        word = 0
        for n in range(1, _CSR_POLL_BOUND + 1):
            word = await self.csr_read(f"{label}_{n}", PULSE_COUNT, length=8)
            done = (word & DONE_BM) >> DONE_BP
            if (done & bits) == (0 if want_low else bits):
                self._polls[label] = n
                return done
        raise AssertionError(
            f"{label}: core_resets_done bits 0b{bits:04b} not {'low' if want_low else 'set'} "
            f"after {_CSR_POLL_BOUND} reads (CORE_RESET_PULSE_COUNT=0x{word:X})"
        )

    async def body(self) -> None:
        clk = cocotb.top.clk_smc_i
        await self.csr_write(
            "CPU_CTRL_DEBUG_RESET_RELEASE",
            CPU_CTRL_RESET_CTRL,
            CPU_RESET_CTRL_DEBUG_RELEASE,
            length=8,
        )
        await ClockCycles(clk, 64)
        reset_ctrl = await self.csr_read("CPU_CTRL_RESET_CTRL_RB", CPU_CTRL_RESET_CTRL, length=8)
        assert reset_ctrl & DEBUG_RESET_N, (
            f"debug_reset_n not set in RESET_CTRL (got 0x{reset_ctrl:X})"
        )
        self._tap = SmcJtagTap(name="smc_jtag_dm_hawindow")
        self._tap.init_signals()
        await self._tap.reset_tap()
        await self._tap.read_idcode(check=True)
        await self._tap.read_dmstatus()
        dtmcs = await self._tap.read_dtmcs()
        self._abits = ((dtmcs >> 4) & 0x3F) or 7
        self._idle = max((dtmcs >> 12) & 0x7, 5)
        abstractcs = await self._poll(
            "activate_idle", DMI_ABSTRACTCS, lambda v: not v & ABSTRACTCS_BUSY
        )
        status0 = await self._all_status()
        self._step_done("S1")
        assert self._running_bits(status0) == HAWINDOW_MASK, (
            f"not every hart runs before the test: dmstatus {[f'0x{w:08X}' for w in status0]} "
            f"abstractcs=0x{abstractcs:08X}"
        )

        sel_reset = await self._dmi_read(DMI_HAWINDOWSEL)
        await self._dmi_write(DMI_HAWINDOWSEL, HAWINDOWSEL_ALL)
        sel_written = await self._dmi_read(DMI_HAWINDOWSEL)
        window_reset = await self._dmi_read(DMI_HAWINDOW)
        await self._dmi_write(DMI_HAWINDOW, ALL_ONES)
        window_ones = await self._dmi_read(DMI_HAWINDOW)
        await self._dmi_write(DMI_HAWINDOW, 0)
        window_zero = await self._dmi_read(DMI_HAWINDOW)
        self._step_done("S2")
        assert sel_reset == 0 and sel_written == 0, (
            f"hawindowsel reset 0x{sel_reset:08X}, after a write of 0x{HAWINDOWSEL_ALL:04X} "
            f"0x{sel_written:08X}"
        )
        assert window_ones == HAWINDOW_MASK and window_zero == 0, (
            f"hawindow after all-ones 0x{window_ones:08X} (want 0x{HAWINDOW_MASK:X}), "
            f"after zero 0x{window_zero:08X} (reset readback 0x{window_reset:08X})"
        )

        case_text = []
        for step, (mask, hartsel) in zip(("S3", "S4"), MASK_CASES):
            halted_sum, halted_bits, resumed_sum = await self._mask_halt_resume(step, mask, hartsel)
            self._step_done(step)
            case_text.append(
                f"hawindow 0b{mask:04b} hartsel {hartsel} hasel haltreq: haltsum0 "
                f"0b{halted_sum & HAWINDOW_MASK:04b}, halted harts 0b{halted_bits:04b}, running "
                f"harts 0b{~halted_bits & HAWINDOW_MASK:04b}; after resumereq haltsum0 "
                f"0x{resumed_sum:08X}"
            )
        self._chk(
            "CHK-DM-HAWINDOW-MASK",
            f"hawindowsel reset 0x{sel_reset:08X} and 0x{sel_written:08X} after a write of "
            f"0x{HAWINDOWSEL_ALL:04X}; hawindow after all-ones 0x{window_ones:08X} (bits 3:0), "
            f"after zero 0x{window_zero:08X} (reset readback 0x{window_reset:08X}, printed, "
            f"not compared); " + "; ".join(case_text),
        )

        pulse_count_idle = await self.csr_read("PULSE_COUNT_IDLE", PULSE_COUNT, length=8)
        await self.csr_write("PULSE_COUNT_HELD", PULSE_COUNT, HELD_PULSE, length=8)
        before = await self._hart_status(HALT_ON_RESET_HART)
        control_before = await self._hart_status(CONTROL_PULSED_HART)
        await self._dmi_write(
            DMI_DMCONTROL, _dmcontrol(HALT_ON_RESET_HART, DMCONTROL_SETRESETHALTREQ)
        )
        await self.csr_write(
            "CORE1_CORE2_RESET_PULSE",
            CPU_CTRL_RESET_CTRL,
            CPU_RESET_CTRL_DEBUG_RELEASE | CORE1_PULSE | CORE2_PULSE,
            length=8,
        )
        pulsed = (1 << HALT_ON_RESET_HART) | (1 << CONTROL_PULSED_HART)
        in_pulse = await self._poll_resets_done("pulse_low", pulsed, want_low=True)
        done = await self._poll_resets_done("pulse_done", pulsed, want_low=False)
        await self._dmi_write(DMI_DMCONTROL, _dmcontrol(HALT_ON_RESET_HART))
        halted = await self._poll(
            "reset_halt_wait", DMI_DMSTATUS, lambda v: bool(v & DMSTATUS_ALLHALTED)
        )
        await self._dmi_write(DMI_DMCONTROL, _dmcontrol(CONTROL_PULSED_HART))
        control_after = await self._poll(
            "control_reset_wait", DMI_DMSTATUS, lambda v: bool(v & DMSTATUS_ALLRUNNING)
        )
        haltsum = await self._dmi_read(DMI_HALTSUM0)
        self.haltsum_trace.append(haltsum)
        self._step_done("S5")
        assert before & DMSTATUS_ALLRUNNING and not before & DMSTATUS_ANYHALTED, (
            f"hart {HALT_ON_RESET_HART} before the pulse: dmstatus=0x{before:08X}"
        )
        assert control_before & DMSTATUS_ALLRUNNING and not control_before & DMSTATUS_ANYHALTED, (
            f"hart {CONTROL_PULSED_HART} before the pulse: dmstatus=0x{control_before:08X}"
        )
        assert done & pulsed == pulsed, f"core_resets_done 0b{done:04b} after the pulse"
        assert halted & DMSTATUS_ALLHALTED and not halted & DMSTATUS_ANYRUNNING, (
            f"hart {HALT_ON_RESET_HART} after its reset pulse with setresethaltreq: "
            f"dmstatus=0x{halted:08X}"
        )
        assert (haltsum & HAWINDOW_MASK) == (1 << HALT_ON_RESET_HART), (
            f"haltsum0=0x{haltsum:08X} after the pulse, want only hart {HALT_ON_RESET_HART}"
        )
        self._chk(
            "CHK-DM-RESETHALTREQ-HALTS",
            f"setresethaltreq with hartsel {HALT_ON_RESET_HART}, then RESET_CTRL pulses of cores "
            f"{HALT_ON_RESET_HART} and {CONTROL_PULSED_HART} with post_reset_count 64 "
            f"(core_resets_done 0b{in_pulse:04b} while the pulses run, read "
            f"{self._polls['pulse_low']}; 0b{done:04b} after, read {self._polls['pulse_done']}): "
            f"hart {HALT_ON_RESET_HART} dmstatus 0x{before:08X} before, 0x{halted:08X} after "
            f"(allhalted=1, {self._polls['reset_halt_wait']} polls); hart "
            f"{CONTROL_PULSED_HART} without the request dmstatus 0x{control_before:08X} "
            f"before, 0x{control_after:08X} after (allrunning=1); havereset bits printed, "
            f"not compared: anyhavereset {int(bool(halted & DMSTATUS_ANYHAVERESET))}/"
            f"{int(bool(control_after & DMSTATUS_ANYHAVERESET))}; haltsum0=0x{haltsum:08X}",
        )

        await self._dmi_write(
            DMI_DMCONTROL,
            _dmcontrol(CONTROL_PULSED_HART, DMCONTROL_ACKHAVERESET),
        )
        await self._dmi_write(
            DMI_DMCONTROL,
            _dmcontrol(
                HALT_ON_RESET_HART,
                DMCONTROL_ACKHAVERESET,
                DMCONTROL_CLRRESETHALTREQ,
                DMCONTROL_RESUMEREQ,
            ),
        )
        resumed = await self._poll(
            "resume_wait",
            DMI_DMSTATUS,
            lambda v: bool(v & DMSTATUS_ALLRESUMEACK) and bool(v & DMSTATUS_ALLRUNNING),
        )
        await self._dmi_write(DMI_DMCONTROL, _dmcontrol(0))
        await self.csr_write("PULSE_COUNT_RESTORE", PULSE_COUNT, pulse_count_idle, length=8)
        await self.csr_read(
            "PULSE_COUNT_RESTORE_RB", PULSE_COUNT, length=8, expected=pulse_count_idle
        )
        await ClockCycles(clk, 2)
        self._step_done("S6")
        cocotb.log.info("hart %d resume dmstatus=0x%08X", HALT_ON_RESET_HART, resumed)

        self._assert_fence()
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: 5 bounded waits: dmi_busy_retry=%d enforced-by=%s "
            "fail-on-expiry=SmcJtagTapError last=%s; "
            "dm_active_poll=16 enforced-by=%s fail-on-expiry=AssertionError "
            "last=dmcontrol.dmactive; haltsum_wait=%d fail-on-expiry=AssertionError "
            "last=haltsum0; dmstatus_wait=%d fail-on-expiry=AssertionError last=dmstatus; "
            "resets_done_wait=%d fail-on-expiry=AssertionError last=CORE_RESET_PULSE_COUNT "
            "(max reads used %d)",
            VIP_DMI_BUSY_RETRIES,
            VIP_FILE,
            self._state(),
            VIP_FILE,
            _POLL_BOUND,
            _POLL_BOUND,
            _CSR_POLL_BOUND,
            max(self._polls.values()),
        )
        self.dm_ok = True
