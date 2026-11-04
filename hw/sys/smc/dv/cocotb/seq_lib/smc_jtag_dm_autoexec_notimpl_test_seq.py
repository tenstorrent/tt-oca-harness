# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CPU Debug Module abstractauto field widths, auto-execution across a cmderr clear, and the
not-implemented DMI registers, over the DMI.

Spec sources: hw/sys/smc/doc/cpu.adoc (Debug Module Configuration: capability readbacks table,
DMI register inventory table; Abstract Command Writes While cmderr Is Set), RISC-V External
Debug Support 0.13.2 sections 3.12.8 and 3.12.9.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time

from .smc_cpu_vip_utils import (
    CPU_CTRL_RESET_CTRL,
    CPU_RESET_CTRL_DEBUG_RELEASE,
    cpu_ctrl_u32,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_jtag_protocol_vip import SmcJtagTap

DEBUG_RESET_N = cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__DEBUG_RESET_N_N0_SCAN_bm")

DMI_DATA0 = 0x04
DMI_DATA3 = 0x07
DMI_DMCONTROL = 0x10
DMI_DMSTATUS = 0x11
DMI_ABSTRACTCS = 0x16
DMI_COMMAND = 0x17
DMI_ABSTRACTAUTO = 0x18

DMCONTROL_DMACTIVE = 1 << 0
DMCONTROL_RESUMEREQ = 1 << 30
DMCONTROL_HALTREQ = 1 << 31

DMSTATUS_ANYHALTED = 1 << 8
DMSTATUS_ALLHALTED = 1 << 9
DMSTATUS_ALLRUNNING = 1 << 11
DMSTATUS_ALLRESUMEACK = 1 << 17

ABSTRACTCS_DATACOUNT_MASK = 0xF
ABSTRACTCS_CMDERR_SHIFT = 8
ABSTRACTCS_CMDERR_MASK = 0x7
ABSTRACTCS_CMDERR_W1C = ABSTRACTCS_CMDERR_MASK << ABSTRACTCS_CMDERR_SHIFT
ABSTRACTCS_BUSY = 1 << 12
ABSTRACTCS_PROGBUFSIZE_SHIFT = 24
ABSTRACTCS_PROGBUFSIZE_MASK = 0x1F

EXPECTED_DATACOUNT = 4
EXPECTED_PROGBUFSIZE = 16
AUTOEXECDATA_MASK = (1 << EXPECTED_DATACOUNT) - 1
AUTOEXECPROGBUF_SHIFT = 16
AUTOEXECPROGBUF_MASK = ((1 << EXPECTED_PROGBUFSIZE) - 1) << AUTOEXECPROGBUF_SHIFT
AUTOEXEC_EXPECTED = AUTOEXECPROGBUF_MASK | AUTOEXECDATA_MASK
AUTOEXEC_DATA0 = 1 << 0

CMDERR_NONE = 0
CMDERR_NOT_SUPPORTED = 2

AAR_SIZE_32 = 2
CMD_SIZE_SHIFT = 20
CMD_TRANSFER = 1 << 17
CMD_WRITE = 1 << 16
GPR_BASE = 0x1000
X8 = 8
CMD_READ_X8 = (AAR_SIZE_32 << CMD_SIZE_SHIFT) | CMD_TRANSFER | (GPR_BASE + X8)
CMD_WRITE_X8 = CMD_READ_X8 | CMD_WRITE
CMD_QUICK_ACCESS = 0x0100_0000

X8_PATTERN = 0x5A3C_9E17
DATA3_PATTERN = 0xC3A5_1E4B
JUNK_BEFORE_AUTOEXEC = 0x0BAD_0000
JUNK_WHILE_CLEAR = 0x0BAD_0001
JUNK_WHILE_ERR = 0x0BAD_0002
JUNK_AFTER_CLEAR = 0x0BAD_0003
ALL_ONES = 0xFFFF_FFFF

# DMI addresses cpu.adoc lists as not implemented beyond those
# smc_jtag_dm_sba_scratchpad_test already grades.
NOT_IMPLEMENTED_DMI = (
    ("data4", 0x08),
    ("data5", 0x09),
    ("data6", 0x0A),
    ("data7", 0x0B),
    ("data8", 0x0C),
    ("data9", 0x0D),
    ("data10", 0x0E),
    ("data11", 0x0F),
    ("confstrptr1", 0x1A),
    ("confstrptr2", 0x1B),
    ("confstrptr3", 0x1C),
    ("haltsum3", 0x35),
    ("sbaddress3", 0x37),
    ("sbaddress2", 0x3B),
    ("sbdata2", 0x3E),
    ("sbdata3", 0x3F),
)

STEPS = tuple(f"S{i}" for i in range(1, 9))
CHK_AFTER_STEP = (
    ("CHK-DM-AUTOEXEC-FIELD-WIDTHS", "S2"),
    ("CHK-DM-NOT-IMPL-DMI-FULL", "S3"),
    ("CHK-DM-AUTOEXEC-REEXEC-AFTER-CLEAR", "S7"),
)
FENCE_TERMS = {
    "S1": "RELEASED_ACTIVE_CAPS",
    "S2": "AUTOEXEC_WIDTHS",
    "S3": "NOT_IMPLEMENTED_DMI",
    "S4": "HART_HALTED_X8_LOADED",
    "S5": "AUTOEXEC_RUNS_WHILE_CLEAR",
    "S6": "AUTOEXEC_IDLE_WHILE_CMDERR",
    "S7": "AUTOEXEC_RUNS_AFTER_CLEAR",
    "S8": "RESUMED",
}
_POLL_BOUND = 16
VIP_FILE = "seq_lib/smc_jtag_protocol_vip.py"
VIP_DMI_BUSY_RETRIES = 4


class smc_jtag_dm_autoexec_notimpl_test_seq(SmcCsrSeq):
    """Read the abstractauto widths, walk the not-implemented DMI registers, then auto-execute
    a stored Access Register command before, during and after a cmderr."""

    def __init__(self, name: str = "smc_jtag_dm_autoexec_notimpl_test_seq") -> None:
        super().__init__(name)
        self.dm_ok: bool = False
        self.data0_trace: list[int] = []
        self._tap: SmcJtagTap | None = None
        self._abits: int = 7
        self._idle: int = 5
        self._events: list[tuple[str, str, int]] = []
        self._last_dmi = 0
        self._last_abstractcs = 0
        self._polls: dict[str, int] = {}

    async def _dmi_read(self, addr: int) -> int:
        assert self._tap is not None
        value = await self._tap.dmi_read(addr, abits=self._abits, idle=self._idle)
        self._last_dmi = value
        if addr == DMI_ABSTRACTCS:
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
            f"last abstractcs=0x{self._last_abstractcs:08X} "
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

    async def _command(self, label: str, command: int, cmderr: int) -> int:
        """Write command, wait for busy 0, require cmderr; return abstractcs."""
        await self._dmi_write(DMI_COMMAND, command)
        abstractcs = await self._wait_idle(label)
        assert self._cmderr(abstractcs) == cmderr, (
            f"{label}: command 0x{command:08X} left cmderr={self._cmderr(abstractcs)} "
            f"want {cmderr} abstractcs=0x{abstractcs:08X}"
        )
        return abstractcs

    async def _data0_cycle(self, label: str, junk: int) -> tuple[int, int]:
        """Write junk to data0, wait for busy 0, read data0 and wait again; return (data0, cs)."""
        await self._dmi_write(DMI_DATA0, junk)
        await self._wait_idle(f"{label}_after_write")
        data0 = await self._dmi_read(DMI_DATA0)
        abstractcs = await self._wait_idle(f"{label}_after_read")
        self.data0_trace.append(data0)
        return data0, abstractcs

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
        self._tap = SmcJtagTap(name="smc_jtag_dm_autoexec")
        self._tap.init_signals()
        await self._tap.reset_tap()
        await self._tap.read_idcode(check=True)
        await self._tap.read_dmstatus()
        dtmcs = await self._tap.read_dtmcs()
        self._abits = ((dtmcs >> 4) & 0x3F) or 7
        self._idle = max((dtmcs >> 12) & 0x7, 5)
        abstractcs = await self._wait_idle("activate_idle")
        datacount = abstractcs & ABSTRACTCS_DATACOUNT_MASK
        progbufsize = (abstractcs >> ABSTRACTCS_PROGBUFSIZE_SHIFT) & ABSTRACTCS_PROGBUFSIZE_MASK
        self._step_done("S1")
        assert datacount == EXPECTED_DATACOUNT, f"abstractcs=0x{abstractcs:08X} datacount"
        assert progbufsize == EXPECTED_PROGBUFSIZE, f"abstractcs=0x{abstractcs:08X} progbufsize"
        assert self._cmderr(abstractcs) == CMDERR_NONE, f"abstractcs=0x{abstractcs:08X} cmderr"

        auto_reset = await self._dmi_read(DMI_ABSTRACTAUTO)
        await self._dmi_write(DMI_ABSTRACTAUTO, ALL_ONES)
        auto_ones = await self._dmi_read(DMI_ABSTRACTAUTO)
        await self._dmi_write(DMI_ABSTRACTAUTO, 0)
        auto_zero = await self._dmi_read(DMI_ABSTRACTAUTO)
        self._step_done("S2")
        data_bits = bin(auto_ones & 0xFFFF).count("1")
        progbuf_bits = bin(auto_ones >> AUTOEXECPROGBUF_SHIFT).count("1")
        assert auto_ones == AUTOEXEC_EXPECTED, (
            f"abstractauto wrote 0x{ALL_ONES:08X} read 0x{auto_ones:08X} "
            f"want 0x{AUTOEXEC_EXPECTED:08X}: autoexecdata bits {data_bits} (want "
            f"{EXPECTED_DATACOUNT}), autoexecprogbuf bits {progbuf_bits} (want "
            f"{EXPECTED_PROGBUFSIZE})"
        )
        assert auto_reset == 0 and auto_zero == 0, (
            f"abstractauto reset 0x{auto_reset:08X} after-zero 0x{auto_zero:08X}"
        )
        self._chk(
            "CHK-DM-AUTOEXEC-FIELD-WIDTHS",
            f"abstractauto reset 0x{auto_reset:08X}, after all-ones 0x{auto_ones:08X}: "
            f"autoexecdata {data_bits} bits (bits 3:0) = datacount {datacount}, "
            f"autoexecprogbuf {progbuf_bits} bits (bits 31:16) = progbufsize {progbufsize}, "
            f"bits 15:4 = 0x{(auto_ones >> 4) & 0xFFF:03X}; after zero 0x{auto_zero:08X}",
        )

        rows = []
        for name, addr in NOT_IMPLEMENTED_DMI:
            before = await self._dmi_read(addr)
            await self._dmi_write(addr, ALL_ONES)
            after = await self._dmi_read(addr)
            assert before == 0 and after == 0, (
                f"{name} (DMI 0x{addr:02X}) read 0x{before:08X} before and 0x{after:08X} after "
                f"a write of 0x{ALL_ONES:08X}"
            )
            rows.append(f"{name}@0x{addr:02X}=0x{before:08X}/0x{after:08X}")
        await self._dmi_write(DMI_DATA3, DATA3_PATTERN)
        data3 = await self._dmi_read(DMI_DATA3)
        self._step_done("S3")
        assert data3 == DATA3_PATTERN, f"data3 wrote 0x{DATA3_PATTERN:08X} read 0x{data3:08X}"
        self._chk(
            "CHK-DM-NOT-IMPL-DMI-FULL",
            f"{len(NOT_IMPLEMENTED_DMI)} registers before/after a write of 0x{ALL_ONES:08X}: "
            f"{', '.join(rows)}; positive control data3 wrote 0x{DATA3_PATTERN:08X} "
            f"read 0x{data3:08X}",
        )

        running = await self._dmi_read(DMI_DMSTATUS)
        assert running & DMSTATUS_ALLRUNNING and not running & DMSTATUS_ANYHALTED, (
            f"hart 0 not running before haltreq: dmstatus=0x{running:08X}"
        )
        await self._dmi_write(DMI_DMCONTROL, DMCONTROL_DMACTIVE | DMCONTROL_HALTREQ)
        halted = await self._poll("halt_wait", DMI_DMSTATUS, lambda v: bool(v & DMSTATUS_ALLHALTED))
        await self._dmi_write(DMI_DMCONTROL, DMCONTROL_DMACTIVE)
        await self._dmi_write(DMI_DATA0, X8_PATTERN)
        await self._command("x8_write", CMD_WRITE_X8, CMDERR_NONE)
        await self._dmi_write(DMI_DATA0, 0)
        await self._command("x8_read", CMD_READ_X8, CMDERR_NONE)
        x8_direct = await self._dmi_read(DMI_DATA0)
        command_stored = await self._dmi_read(DMI_COMMAND)
        self._step_done("S4")
        assert x8_direct == X8_PATTERN, f"x8 read 0x{x8_direct:08X} wrote 0x{X8_PATTERN:08X}"
        assert command_stored == CMD_READ_X8, f"command read 0x{command_stored:08X}"
        cocotb.log.info(
            "hart 0 halted (dmstatus=0x%08X in %d polls); x8=0x%08X read back through data0; "
            "command stores 0x%08X (Access Register read x8, aarsize 2)",
            halted,
            self._polls["halt_wait"],
            x8_direct,
            command_stored,
        )

        await self._dmi_write(DMI_DATA0, JUNK_BEFORE_AUTOEXEC)
        data0_plain = await self._dmi_read(DMI_DATA0)
        assert data0_plain == JUNK_BEFORE_AUTOEXEC, (
            f"data0 wrote 0x{JUNK_BEFORE_AUTOEXEC:08X} read 0x{data0_plain:08X} with abstractauto 0"
        )
        await self._dmi_write(DMI_ABSTRACTAUTO, AUTOEXEC_DATA0)
        auto_set = await self._dmi_read(DMI_ABSTRACTAUTO)
        assert auto_set == AUTOEXEC_DATA0, f"abstractauto read 0x{auto_set:08X}"
        data0_clear, cs_clear = await self._data0_cycle("autoexec_clear", JUNK_WHILE_CLEAR)
        self._step_done("S5")
        assert data0_clear == X8_PATTERN and self._cmderr(cs_clear) == CMDERR_NONE, (
            f"with autoexecdata[0] and cmderr 0: data0 wrote 0x{JUNK_WHILE_CLEAR:08X} read "
            f"0x{data0_clear:08X} want 0x{X8_PATTERN:08X} abstractcs=0x{cs_clear:08X}"
        )

        await self._command("quick_access", CMD_QUICK_ACCESS, CMDERR_NOT_SUPPORTED)
        command_quick = await self._dmi_read(DMI_COMMAND)
        await self._dmi_write(DMI_COMMAND, CMD_READ_X8)
        cs_err = await self._wait_idle("store_under_cmderr")
        command_under_err = await self._dmi_read(DMI_COMMAND)
        data0_err, cs_after_err = await self._data0_cycle("autoexec_cmderr", JUNK_WHILE_ERR)
        self._step_done("S6")
        assert self._cmderr(cs_err) == CMDERR_NOT_SUPPORTED, (
            f"command write while cmderr=2 left abstractcs=0x{cs_err:08X}"
        )
        assert command_quick == CMD_QUICK_ACCESS, (
            f"command read 0x{command_quick:08X} after the Quick Access write, want "
            f"0x{CMD_QUICK_ACCESS:08X}"
        )
        assert command_under_err == CMD_READ_X8, f"command read 0x{command_under_err:08X}"
        assert data0_err == JUNK_WHILE_ERR, (
            f"with cmderr=2: data0 wrote 0x{JUNK_WHILE_ERR:08X} read 0x{data0_err:08X}; "
            f"abstractcs=0x{cs_after_err:08X}"
        )
        assert self._cmderr(cs_after_err) == CMDERR_NOT_SUPPORTED, (
            f"cmderr changed under the data0 access: abstractcs=0x{cs_after_err:08X}"
        )

        await self._dmi_write(DMI_ABSTRACTCS, ABSTRACTCS_CMDERR_W1C)
        cs_cleared = await self._wait_idle("cmderr_clear")
        assert self._cmderr(cs_cleared) == CMDERR_NONE, f"abstractcs=0x{cs_cleared:08X}"
        data0_after, cs_after = await self._data0_cycle("autoexec_after_clear", JUNK_AFTER_CLEAR)
        command_after = await self._dmi_read(DMI_COMMAND)
        self._step_done("S7")
        assert data0_after == X8_PATTERN and self._cmderr(cs_after) == CMDERR_NONE, (
            f"after the cmderr clear: data0 wrote 0x{JUNK_AFTER_CLEAR:08X} read "
            f"0x{data0_after:08X} want 0x{X8_PATTERN:08X} abstractcs=0x{cs_after:08X}"
        )
        assert command_after == CMD_READ_X8, f"command read 0x{command_after:08X}"
        self._chk(
            "CHK-DM-AUTOEXEC-REEXEC-AFTER-CLEAR",
            f"data0 held 0x{data0_plain:08X} with abstractauto 0; autoexecdata[0]=1 with "
            f"command 0x{command_after:08X} stored: cmderr 0, data0 wrote "
            f"0x{JUNK_WHILE_CLEAR:08X} read 0x{data0_clear:08X} (x8); Quick Access stored "
            f"(command read 0x{command_quick:08X}, cmderr 2) and the command rewrite "
            f"(0x{cs_err:08X}), data0 wrote "
            f"0x{JUNK_WHILE_ERR:08X} read 0x{data0_err:08X} abstractcs=0x{cs_after_err:08X}; "
            f"cmderr cleared (0x{cs_cleared:08X}), data0 wrote 0x{JUNK_AFTER_CLEAR:08X} read "
            f"0x{data0_after:08X} abstractcs=0x{cs_after:08X}",
        )

        await self._dmi_write(DMI_ABSTRACTAUTO, 0)
        await self._dmi_write(DMI_DMCONTROL, DMCONTROL_DMACTIVE | DMCONTROL_RESUMEREQ)
        resumed = await self._poll(
            "resume_wait",
            DMI_DMSTATUS,
            lambda v: bool(v & DMSTATUS_ALLRESUMEACK) and bool(v & DMSTATUS_ALLRUNNING),
        )
        await self._dmi_write(DMI_DMCONTROL, DMCONTROL_DMACTIVE)
        await ClockCycles(clk, 2)
        self._step_done("S8")
        cocotb.log.info("resume dmstatus=0x%08X", resumed)

        self._assert_fence()
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: 5 bounded waits: dmi_busy_retry=%d enforced-by=%s "
            "fail-on-expiry=SmcJtagTapError last=%s; "
            "dm_active_poll=16 enforced-by=%s fail-on-expiry=AssertionError "
            "last=dmcontrol.dmactive; halt_wait=%d fail-on-expiry=AssertionError "
            "last=dmstatus; busy_wait=%d fail-on-expiry=AssertionError last=abstractcs "
            "(max reads used %d); resume_wait=%d fail-on-expiry=AssertionError last=dmstatus",
            VIP_DMI_BUSY_RETRIES,
            VIP_FILE,
            self._state(),
            VIP_FILE,
            _POLL_BOUND,
            _POLL_BOUND,
            max(self._polls.values()),
            _POLL_BOUND,
        )
        self.dm_ok = True
