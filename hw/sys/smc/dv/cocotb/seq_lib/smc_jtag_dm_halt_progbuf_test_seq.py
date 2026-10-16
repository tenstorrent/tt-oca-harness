# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CPU Debug Module activation, hart halt, GPR access and program-buffer execution over the DMI.

Spec sources: hw/sys/smc/doc/cpu.adoc (Debug Module capability readbacks and DMI register
inventory tables), RISC-V External Debug Support 0.13.2 sections 3.12 and 4.1,
hw/sys/smc/regs/blocks/cpu_ctrl/cpu_ctrl.rdl (RESET_CTRL, SCRATCH).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time

from .smc_addr_map import smc_indexed_addr
from .smc_cpu_vip_utils import (
    CPU_CTRL_RESET_CTRL,
    CPU_RESET_CTRL_DEBUG_RELEASE,
    cpu_ctrl_u32,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_jtag_protocol_vip import SmcJtagTap

DEBUG_RESET_N = cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__DEBUG_RESET_N_N0_SCAN_bm")
SCRATCH_0 = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", 0)

DMI_DATA0 = 0x04
DMI_DMCONTROL = 0x10
DMI_DMSTATUS = 0x11
DMI_ABSTRACTCS = 0x16
DMI_COMMAND = 0x17
DMI_PROGBUF0 = 0x20
DMI_HALTSUM0 = 0x40

DMCONTROL_DMACTIVE = 1 << 0
DMCONTROL_HARTSELLO_SHIFT = 16
DMCONTROL_HARTSELLO_MASK = 0x3FF << DMCONTROL_HARTSELLO_SHIFT
DMCONTROL_HARTSELHI_SHIFT = 6
DMCONTROL_RESUMEREQ = 1 << 30
DMCONTROL_HALTREQ = 1 << 31

DMSTATUS_VERSION_MASK = 0xF
DMSTATUS_ANYHALTED = 1 << 8
DMSTATUS_ALLHALTED = 1 << 9
DMSTATUS_ANYRUNNING = 1 << 10
DMSTATUS_ALLRUNNING = 1 << 11
DMSTATUS_ALLUNAVAIL = 1 << 13
DMSTATUS_ALLRESUMEACK = 1 << 17
DMSTATUS_IMPEBREAK = 1 << 22

ABSTRACTCS_DATACOUNT_MASK = 0xF
ABSTRACTCS_BUSY = 1 << 12
ABSTRACTCS_CMDERR_SHIFT = 8
ABSTRACTCS_CMDERR_MASK = 0x7
ABSTRACTCS_PROGBUFSIZE_SHIFT = 24
ABSTRACTCS_PROGBUFSIZE_MASK = 0x1F

EXPECTED_DMSTATUS_VERSION = 2
EXPECTED_PROGBUFSIZE = 16
EXPECTED_DATACOUNT = 4
PROGBUF_WORDS = 16

AAR_SIZE_64 = 3
CMD_SIZE_SHIFT = 20
CMD_POSTEXEC = 1 << 18
CMD_TRANSFER = 1 << 17
CMD_WRITE = 1 << 16
GPR_BASE = 0x1000
X8 = 8
X9 = 9

PATTERN_X8 = 0x0F1E_2D3C_A5C3_1E4D
SENTINEL = 0x5E17_1AC3
DATA_PATTERNS = (0x1357_9BDF, 0x2468_ACE0, 0xDEAD_BEEF, 0xC0FF_EE11)

_POLL_BOUND = 16
VIP_FILE = "seq_lib/smc_jtag_protocol_vip.py"
VIP_DMI_BUSY_RETRIES = 4


def encode_addi(rd: int, rs1: int, imm: int) -> int:
    """RV64 addi rd, rs1, imm."""
    return ((imm & 0xFFF) << 20) | (rs1 << 15) | (0 << 12) | (rd << 7) | 0x13


def encode_sw(rs2: int, imm: int, rs1: int) -> int:
    """RV64 sw rs2, imm(rs1)."""
    return (
        (((imm >> 5) & 0x7F) << 25)
        | (rs2 << 20)
        | (rs1 << 15)
        | (2 << 12)
        | ((imm & 0x1F) << 7)
        | 0x23
    )


def access_register(regno: int, *, write: bool, transfer: bool, postexec: bool = False) -> int:
    """Access Register command word, cmdtype 0, 64-bit."""
    return (
        (AAR_SIZE_64 << CMD_SIZE_SHIFT)
        | (CMD_POSTEXEC if postexec else 0)
        | (CMD_TRANSFER if transfer else 0)
        | (CMD_WRITE if write else 0)
        | regno
    )


STORE_WORD = encode_sw(X8, 0, X9)
# Distinct harmless words: addi x0, x0, k.
PROGBUF_PATTERN = tuple(encode_addi(0, 0, k + 1) for k in range(PROGBUF_WORDS))

STEPS = tuple(f"S{i}" for i in range(1, 11))
CHK_AFTER_STEP = (
    ("CHK-DM-ACT-RESET-HELD", "S1"),
    ("CHK-DM-ACT-DMSTATUS", "S2"),
    ("CHK-DM-CAP-READBACK", "S2"),
    ("CHK-DM-HART-HALT", "S4"),
    ("CHK-DM-HALTSUM0", "S4"),
    ("CHK-DM-OTHER-HART-RUNS", "S5"),
    ("CHK-DM-GPR-DATA", "S6"),
    ("CHK-DM-PROGBUF-REGS", "S7"),
    ("CHK-DM-PROGBUF-STORE", "S9"),
    ("CHK-DM-PROGBUF-IMPEBREAK", "S9"),
)
FENCE_TERMS = {
    "S1": "RESET_HELD_READ",
    "S2": "RELEASED_ACTIVE_CAPS",
    "S3": "HART_RUNNING",
    "S4": "HART_HALTED",
    "S5": "OTHER_HART_RUNNING",
    "S6": "GPR_DATA",
    "S7": "PROGBUF_STAGED",
    "S8": "PROGBUF_RUN",
    "S9": "SCRATCH_AFTER_RUN",
    "S10": "RESUMED",
}


class smc_jtag_dm_halt_progbuf_test_seq(SmcCsrSeq):
    """Activate the Debug Module, halt hart 0, access a GPR and run a program-buffer store."""

    def __init__(self, name: str = "smc_jtag_dm_halt_progbuf_test_seq") -> None:
        super().__init__(name)
        self.dm_ok: bool = False
        self.scratch_after: int = 0
        self.expected_scratch: int = PATTERN_X8 & 0xFFFF_FFFF
        self._tap: SmcJtagTap | None = None
        self._abits: int = 7
        self._idle: int = 5
        self._events: list[tuple[str, str, int]] = []
        self._last_dmstatus = 0
        self._last_abstractcs = 0
        self._last_dmi = 0
        self._polls: dict[str, int] = {}

    async def _dmi_read(self, addr: int) -> int:
        assert self._tap is not None
        value = await self._tap.dmi_read(addr, abits=self._abits, idle=self._idle)
        self._last_dmi = value
        if addr == DMI_DMSTATUS:
            self._last_dmstatus = value
        elif addr == DMI_ABSTRACTCS:
            self._last_abstractcs = value
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
        return (
            f"last dmstatus=0x{self._last_dmstatus:08X} abstractcs=0x{self._last_abstractcs:08X} "
            f"last DMI response=0x{self._last_dmi:08X}"
        )

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

    async def _wait_idle(self, label: str) -> int:
        return await self._poll(label, DMI_ABSTRACTCS, lambda v: not v & ABSTRACTCS_BUSY)

    @staticmethod
    def _cmderr(abstractcs: int) -> int:
        return (abstractcs >> ABSTRACTCS_CMDERR_SHIFT) & ABSTRACTCS_CMDERR_MASK

    async def _command(self, label: str, command: int) -> int:
        """Write command, wait for busy 0; require cmderr 0; return abstractcs."""
        await self._dmi_write(DMI_COMMAND, command)
        abstractcs = await self._wait_idle(label)
        assert self._cmderr(abstractcs) == 0, (
            f"{label}: command 0x{command:08X} left cmderr={self._cmderr(abstractcs)} "
            f"abstractcs=0x{abstractcs:08X}"
        )
        return abstractcs

    async def _write_data64(self, value: int) -> None:
        await self._dmi_write(DMI_DATA0, value & 0xFFFF_FFFF)
        await self._dmi_write(DMI_DATA0 + 1, value >> 32)

    async def body(self) -> None:
        clk = cocotb.top.clk_smc_i
        reset_before = await self.csr_read(
            "CPU_CTRL_RESET_CTRL_BEFORE", CPU_CTRL_RESET_CTRL, length=8
        )
        self._step_done("S1")
        assert not reset_before & DEBUG_RESET_N, (
            f"debug_reset_n reads set before the release (RESET_CTRL=0x{reset_before:X})"
        )
        self._chk(
            "CHK-DM-ACT-RESET-HELD",
            f"LINKED-ISSUE 2-state zero reset value: RESET_CTRL=0x{reset_before:X} "
            f"debug_reset_n={int(bool(reset_before & DEBUG_RESET_N))} before the release",
        )

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
        self._tap = SmcJtagTap(name="smc_jtag_dm_halt")
        self._tap.init_signals()
        await self._tap.reset_tap()
        await self._tap.read_idcode(check=True)
        await self._tap.read_dmstatus()
        dtmcs = await self._tap.read_dtmcs()
        self._abits = ((dtmcs >> 4) & 0x3F) or 7
        self._idle = max((dtmcs >> 12) & 0x7, 5)
        dmstatus = await self._dmi_read(DMI_DMSTATUS)
        abstractcs = await self._dmi_read(DMI_ABSTRACTCS)
        version = dmstatus & DMSTATUS_VERSION_MASK
        impebreak = int(bool(dmstatus & DMSTATUS_IMPEBREAK))
        assert version == EXPECTED_DMSTATUS_VERSION, f"dmstatus=0x{dmstatus:08X} version={version}"
        assert impebreak == 1, f"dmstatus=0x{dmstatus:08X} impebreak={impebreak}"
        act_text = (
            f"dmstatus=0x{dmstatus:08X} version={version} impebreak={impebreak} after release "
            f"RESET_CTRL=0x{reset_ctrl:X} and dmactive=1 (dtmcs=0x{dtmcs:08X})"
        )
        progbufsize = (abstractcs >> ABSTRACTCS_PROGBUFSIZE_SHIFT) & ABSTRACTCS_PROGBUFSIZE_MASK
        datacount = abstractcs & ABSTRACTCS_DATACOUNT_MASK
        assert progbufsize == EXPECTED_PROGBUFSIZE, f"abstractcs=0x{abstractcs:08X} progbufsize"
        assert datacount == EXPECTED_DATACOUNT, f"abstractcs=0x{abstractcs:08X} datacount"
        await self._dmi_write(DMI_DMCONTROL, DMCONTROL_DMACTIVE | (3 << DMCONTROL_HARTSELLO_SHIFT))
        sel3 = await self._dmi_read(DMI_DMCONTROL)
        hartsello = (sel3 & DMCONTROL_HARTSELLO_MASK) >> DMCONTROL_HARTSELLO_SHIFT
        assert hartsello == 3, f"hartsello wrote 3 read back {hartsello} (dmcontrol=0x{sel3:08X})"
        await self._dmi_write(
            DMI_DMCONTROL, DMCONTROL_DMACTIVE | (0x5 << DMCONTROL_HARTSELHI_SHIFT)
        )
        selhi = await self._dmi_read(DMI_DMCONTROL)
        hartselhi = (selhi >> DMCONTROL_HARTSELHI_SHIFT) & 0x3FF
        assert hartselhi == 0, f"hartselhi wrote 5 read back {hartselhi} (dmcontrol=0x{selhi:08X})"
        await self._dmi_write(DMI_DMCONTROL, DMCONTROL_DMACTIVE)
        self._step_done("S2")
        self._chk("CHK-DM-ACT-DMSTATUS", act_text)
        self._chk(
            "CHK-DM-CAP-READBACK",
            f"abstractcs=0x{abstractcs:08X} progbufsize={progbufsize} datacount={datacount}; "
            f"dmcontrol hartsello 3 read back {hartsello} (0x{sel3:08X}); hartselhi 5 read "
            f"back {hartselhi} (0x{selhi:08X})",
        )

        running = await self._dmi_read(DMI_DMSTATUS)
        self._step_done("S3")
        assert running & DMSTATUS_ALLRUNNING and not running & DMSTATUS_ANYHALTED, (
            f"hart not running before haltreq: dmstatus=0x{running:08X}"
        )

        await self._dmi_write(DMI_DMCONTROL, DMCONTROL_DMACTIVE | DMCONTROL_HALTREQ)
        halted = await self._poll("halt_wait", DMI_DMSTATUS, lambda v: bool(v & DMSTATUS_ALLHALTED))
        await self._dmi_write(DMI_DMCONTROL, DMCONTROL_DMACTIVE)
        halted = await self._dmi_read(DMI_DMSTATUS)
        haltsum0 = await self._dmi_read(DMI_HALTSUM0)
        self._step_done("S4")
        assert halted & DMSTATUS_ALLHALTED and not halted & DMSTATUS_ANYRUNNING, (
            f"after haltreq dmstatus=0x{halted:08X}"
        )
        self._chk(
            "CHK-DM-HART-HALT",
            f"before haltreq dmstatus=0x{running:08X} allrunning=1 anyhalted=0; after haltreq "
            f"dmstatus=0x{halted:08X} allhalted=1 anyrunning=0 within {self._polls['halt_wait']} "
            f"polls of {_POLL_BOUND}",
        )
        assert haltsum0 & 0xF == 0b0001, f"haltsum0=0x{haltsum0:08X} with hart 0 halted"
        self._chk("CHK-DM-HALTSUM0", f"haltsum0=0x{haltsum0:08X} bits 3:0 = 0b0001")

        await self._dmi_write(DMI_DMCONTROL, DMCONTROL_DMACTIVE | (1 << DMCONTROL_HARTSELLO_SHIFT))
        other = await self._dmi_read(DMI_DMSTATUS)
        await self._dmi_write(DMI_DMCONTROL, DMCONTROL_DMACTIVE)
        self._step_done("S5")
        assert other & DMSTATUS_ALLRUNNING and not other & DMSTATUS_ANYHALTED, (
            f"hartsello=1 dmstatus=0x{other:08X}"
        )
        self._chk(
            "CHK-DM-OTHER-HART-RUNS",
            f"hartsello=1 dmstatus=0x{other:08X} allrunning=1 anyhalted=0 while hart 0 halted",
        )

        for k, pattern in enumerate(DATA_PATTERNS):
            await self._dmi_write(DMI_DATA0 + k, pattern)
        data_back = [await self._dmi_read(DMI_DATA0 + k) for k in range(len(DATA_PATTERNS))]
        assert tuple(data_back) == DATA_PATTERNS, (
            f"data0..data3 read {[hex(v) for v in data_back]} "
            f"wrote {[hex(v) for v in DATA_PATTERNS]}"
        )
        await self._write_data64(PATTERN_X8)
        await self._command("x8_write", access_register(GPR_BASE + X8, write=True, transfer=True))
        await self._write_data64(SCRATCH_0)
        await self._command("x9_write", access_register(GPR_BASE + X9, write=True, transfer=True))
        await self._write_data64(0)
        abstractcs = await self._command(
            "x8_read", access_register(GPR_BASE + X8, write=False, transfer=True)
        )
        x8_value = (await self._dmi_read(DMI_DATA0)) | ((await self._dmi_read(DMI_DATA0 + 1)) << 32)
        self._step_done("S6")
        assert x8_value == PATTERN_X8, f"x8 read 0x{x8_value:016X} wrote 0x{PATTERN_X8:016X}"
        self._chk(
            "CHK-DM-GPR-DATA",
            f"data0..data3 read back {','.join(f'0x{v:08X}' for v in data_back)}; x8 wrote "
            f"0x{PATTERN_X8:016X} read 0x{x8_value:016X}; x9 wrote 0x{SCRATCH_0:08X}; "
            f"abstractcs after the x8 read=0x{abstractcs:08X} busy=0 cmderr=0",
        )

        for k, word in enumerate(PROGBUF_PATTERN):
            await self._dmi_write(DMI_PROGBUF0 + k, word)
        progbuf_back = [await self._dmi_read(DMI_PROGBUF0 + k) for k in range(PROGBUF_WORDS)]
        assert tuple(progbuf_back) == PROGBUF_PATTERN, (
            f"progbuf read {[hex(v) for v in progbuf_back]} "
            f"wrote {[hex(v) for v in PROGBUF_PATTERN]}"
        )
        cocotb.log.info(
            "program buffer word0 sw x8,0(x9)=0x%08X; words 1..15 stay addi x0,x0,k",
            STORE_WORD,
        )
        await self._dmi_write(DMI_PROGBUF0, STORE_WORD)
        await self.csr_write("SCRATCH_SENTINEL", SCRATCH_0, SENTINEL, length=8)
        sentinel_back = await self.csr_read("SCRATCH_SENTINEL_RB", SCRATCH_0, length=8)
        self._step_done("S7")
        self._chk(
            "CHK-DM-PROGBUF-REGS",
            f"progbuf0..15 read back {','.join(f'0x{v:08X}' for v in progbuf_back)}",
        )
        assert sentinel_back == SENTINEL, f"SCRATCH[0] sentinel read 0x{sentinel_back:X}"

        await self._dmi_write(
            DMI_COMMAND, access_register(0, write=False, transfer=False, postexec=True)
        )
        first_poll = await self._dmi_read(DMI_ABSTRACTCS)
        abstractcs = first_poll
        if first_poll & ABSTRACTCS_BUSY:
            abstractcs = await self._wait_idle("progbuf_busy")
        self._step_done("S8")
        busy_first = int(bool(first_poll & ABSTRACTCS_BUSY))
        cmderr = self._cmderr(abstractcs)
        assert not abstractcs & ABSTRACTCS_BUSY and cmderr == 0, (
            f"after postexec abstractcs=0x{abstractcs:08X}"
        )

        self.scratch_after = await self.csr_read("SCRATCH_AFTER_RB", SCRATCH_0, length=8)
        self._step_done("S9")
        expected = self.expected_scratch
        assert SENTINEL != expected
        assert self.scratch_after == expected, (
            f"SCRATCH[0] reads 0x{self.scratch_after:X} after the program buffer ran, "
            f"expected 0x{expected:X} (sentinel 0x{SENTINEL:X})"
        )
        self._chk(
            "CHK-DM-PROGBUF-STORE",
            f"SCRATCH[0] 0x{sentinel_back:X} (sentinel) before and 0x{self.scratch_after:X} after "
            f"the program buffer ran; x8 low word 0x{expected:X}",
        )
        self._chk(
            "CHK-DM-PROGBUF-IMPEBREAK",
            f"postexec with no explicit ebreak: first abstractcs=0x{first_poll:08X} "
            f"busy={busy_first}, final abstractcs=0x{abstractcs:08X} busy=0 cmderr={cmderr}, "
            f"busy polls {self._polls.get('progbuf_busy', 0)} of {_POLL_BOUND}",
        )

        await self._dmi_write(DMI_DMCONTROL, DMCONTROL_DMACTIVE | DMCONTROL_RESUMEREQ)
        resumed = await self._poll(
            "resume_wait",
            DMI_DMSTATUS,
            lambda v: bool(v & DMSTATUS_ALLRESUMEACK) and bool(v & DMSTATUS_ALLRUNNING),
        )
        await self._dmi_write(DMI_DMCONTROL, DMCONTROL_DMACTIVE)
        await ClockCycles(clk, 2)
        self._step_done("S10")
        cocotb.log.info("resume dmstatus=0x%08X", resumed)

        self._assert_fence()
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: 5 bounded waits: dmi_busy_retry=%d enforced-by=%s "
            "fail-on-expiry=SmcJtagTapError last=%s; "
            "dm_active_poll=16 enforced-by=%s fail-on-expiry=AssertionError "
            "last=dmcontrol.dmactive; halt_wait=%d fail-on-expiry=AssertionError "
            "last=dmstatus; busy_wait=%d fail-on-expiry=AssertionError last=abstractcs; "
            "resume_wait=%d fail-on-expiry=AssertionError last=dmstatus",
            VIP_DMI_BUSY_RETRIES,
            VIP_FILE,
            self._state(),
            VIP_FILE,
            _POLL_BOUND,
            _POLL_BOUND,
            _POLL_BOUND,
        )
        self.dm_ok = True
