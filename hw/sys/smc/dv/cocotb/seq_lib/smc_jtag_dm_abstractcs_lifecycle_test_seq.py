# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CPU Debug Module abstractcs.busy and abstractcs.cmderr lifecycle over the DMI.

Spec sources: hw/sys/smc/doc/cpu.adoc (Access Register support, abstract command writes while
cmderr is set), RISC-V External Debug Support 0.13.2 sections 3.12.6 and 3.12.7,
hw/sys/smc/regs/blocks/cpu_ctrl/cpu_ctrl.rdl (RESET_CTRL).
"""

from __future__ import annotations

import math

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time
from env.smc_env_cfg import measure_clock_period_ns

from .smc_cpu_vip_utils import (
    CPU_CTRL_RESET_CTRL,
    CPU_RESET_CTRL_DEBUG_RELEASE,
    cpu_ctrl_u32,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_jtag_protocol_vip import SmcJtagTap

DEBUG_RESET_N = cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__DEBUG_RESET_N_N0_SCAN_bm")

DMI_DATA0 = 0x04
DMI_DATA1 = 0x05
DMI_DMCONTROL = 0x10
DMI_DMSTATUS = 0x11
DMI_ABSTRACTCS = 0x16
DMI_COMMAND = 0x17
DMI_PROGBUF0 = 0x20

DMCONTROL_DMACTIVE = 1 << 0
DMCONTROL_HALTREQ = 1 << 31
DMSTATUS_VERSION_MASK = 0xF
DMSTATUS_ALLHALTED = 1 << 9
DMSTATUS_ANYRUNNING = 1 << 10

ABSTRACTCS_BUSY = 1 << 12
ABSTRACTCS_CMDERR_SHIFT = 8
ABSTRACTCS_CMDERR_MASK = 0x7
ABSTRACTCS_CMDERR_W1C = ABSTRACTCS_CMDERR_MASK << ABSTRACTCS_CMDERR_SHIFT

CMDERR_NONE = 0
CMDERR_BUSY = 1
CMDERR_NOT_SUPPORTED = 2

AARSIZE_32 = 2
AARSIZE_64 = 3
AARSIZE_16 = 1
CMD_SIZE_SHIFT = 20
CMD_POSTEXEC = 1 << 18
CMD_TRANSFER = 1 << 17
CMD_WRITE = 1 << 16
CMD_QUICK_ACCESS = 0x0100_0000
GPR_BASE = 0x1000
REGNO_OUT_OF_RANGE = 0x1020
X5 = 5
X6 = 6
X8 = 8

PATTERN_A = 0x0F1E_2D3C_A5C3_1E4D
PATTERN_B = 0xB7A6_9584_7362_5140
PATTERN_C = 0xC3A5_5A3C
X6_INITIAL = 0x6161_2929_1357_9BDF
X6_BUSY_WRITE = 0x7E7E_5A5A_2468_ACE0

PROGBUF_WORDS = 16
NOP = 0x0000_0013
TCK_PERIOD_NS = 10
# Upper bound of TCK cycles one DMI access costs on this bench: two 41-bit scans, the TAP state
# moves around them and the idle cycles the VIP inserts after the launch and capture scans.
TCK_PER_DMI_ACCESS = 160
# DMI accesses the busy window must outlast: the abstractcs read that observes busy and the
# command write that follows it, with margin.
WINDOW_DMI_ACCESSES = 4
# The counted loop takes two instructions per iteration at best, one clock each.
LOOP_CLOCKS_PER_ITERATION = 2

LIFECYCLE_LEGS = ("set", "observed", "cleared", "checked_cleared")
POLL_BOUND = 16
BUSY_BOUND = 64
VIP_FILE = "seq_lib/smc_jtag_protocol_vip.py"
VIP_DMI_BUSY_RETRIES = 4

STEPS = tuple(f"S{i}" for i in range(1, 8))
CHK_AFTER_STEP = (
    ("CHK-DM-BUSY-LIFECYCLE", "S3"),
    ("CHK-DM-BUSY-WRITE", "S4"),
    ("CHK-DM-CMDERR-CMDTYPE", "S5"),
    ("CHK-DM-CMDERR-REGNO", "S5"),
    ("CHK-DM-CMDERR-AARSIZE", "S5"),
    ("CHK-DM-CMDERR-NOTRANSFER", "S5"),
    ("CHK-DM-CMDERR-STORE", "S6"),
    ("CHK-DM-CMDERR-REPLACE", "S4"),
    ("CHK-DM-CMDERR-NOEXEC", "S6"),
    ("CHK-DM-CMDERR-RECOVER-GPR32", "S7"),
)
FENCE_TERMS = {
    "S1": "HALTED_IDLE",
    "S2": "LOOP_LOADED",
    "S3": "BUSY_OBSERVED",
    "S4": "BUSY_WRITE",
    "S5": "CMDERR_LEGS",
    "S6": "STORE_WHILE_CMDERR",
    "S7": "GPR32_RECOVERY",
}


def encode_addi(rd: int, rs1: int, imm: int) -> int:
    """RV64 addi rd, rs1, imm."""
    return ((imm & 0xFFF) << 20) | (rs1 << 15) | (0 << 12) | (rd << 7) | 0x13


def encode_bne(rs1: int, rs2: int, offset: int) -> int:
    """RV64 bne rs1, rs2, offset (even byte offset, 13-bit signed)."""
    imm = offset & 0x1FFF
    return (
        (((imm >> 12) & 1) << 31)
        | (((imm >> 5) & 0x3F) << 25)
        | (rs2 << 20)
        | (rs1 << 15)
        | (1 << 12)
        | (((imm >> 1) & 0xF) << 8)
        | (((imm >> 11) & 1) << 7)
        | 0x63
    )


def access_register(
    regno: int,
    *,
    write: bool,
    transfer: bool,
    postexec: bool = False,
    aarsize: int = AARSIZE_64,
) -> int:
    """Access Register command word, cmdtype 0."""
    return (
        (aarsize << CMD_SIZE_SHIFT)
        | (CMD_POSTEXEC if postexec else 0)
        | (CMD_TRANSFER if transfer else 0)
        | (CMD_WRITE if write else 0)
        | regno
    )


LOOP_DECREMENT = encode_addi(X5, X5, -1)
LOOP_BRANCH = encode_bne(X5, 0, -4)
PROGBUF = (LOOP_DECREMENT, LOOP_BRANCH) + (NOP,) * (PROGBUF_WORDS - 2)


class smc_jtag_dm_abstractcs_lifecycle_test_seq(SmcCsrSeq):
    """Observe abstractcs.busy during a program-buffer loop and walk the cmderr codes 1 and 2."""

    def __init__(self, name: str = "smc_jtag_dm_abstractcs_lifecycle_test_seq") -> None:
        super().__init__(name)
        self.dm_ok: bool = False
        self.x8_low: int = 0
        self._tap: SmcJtagTap | None = None
        self._abits: int = 7
        self._idle: int = 5
        self._events: list[tuple[str, str, int]] = []
        self._last_dmstatus = 0
        self._last_abstractcs = 0
        self._last_command = 0
        self._last_dmi = 0
        self._lines: dict[str, str] = {}
        self._lifecycle: dict[str, tuple[str, str, str, str]] = {}

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
        if addr == DMI_COMMAND:
            self._last_command = data
        await self._tap.dmi_write(addr, data, abits=self._abits, idle=self._idle)

    def _step_done(self, step: str) -> None:
        self._events.append(("step", step, int(get_sim_time("ps"))))

    def _set_chk(self, cid: str, text: str) -> None:
        self._lines[cid] = text

    def _set_lifecycle(
        self, cid: str, set_: str, observed: str, cleared: str, checked: str
    ) -> None:
        self._lifecycle[cid] = (set_, observed, cleared, checked)

    def _emit_checkers(self) -> None:
        for cid, _ in CHK_AFTER_STEP:
            cocotb.log.info("%s: %s", cid, self._lines[cid])
            for leg, text in zip(LIFECYCLE_LEGS, self._lifecycle.get(cid, ())):
                cocotb.log.info("LIFECYCLE %s %s: %s", cid, leg, text)
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
        cocotb.log.info("fence checker order: %s", " < ".join(c[1] for c in chks))
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; %d checker lines after the steps; stamps %s",
            " < ".join(FENCE_TERMS[e[1]] for e in steps),
            len(chks),
            ",".join(str(s) for s in stamps),
        )

    def _state(self) -> str:
        return (
            f"last dmstatus=0x{self._last_dmstatus:08X} abstractcs=0x{self._last_abstractcs:08X} "
            f"command=0x{self._last_command:08X} last DMI response=0x{self._last_dmi:08X}"
        )

    async def _poll(self, label: str, addr: int, done, bound: int = POLL_BOUND) -> tuple[int, int]:
        """Read addr until done(value) holds; return (value, reads); raise after bound reads."""
        for n in range(1, bound + 1):
            value = await self._dmi_read(addr)
            if done(value):
                return value, n
        raise AssertionError(
            f"{label}: not satisfied after {bound} DMI reads of 0x{addr:02X}; {self._state()}"
        )

    async def _wait_idle(self, label: str, bound: int = POLL_BOUND) -> tuple[int, int]:
        return await self._poll(label, DMI_ABSTRACTCS, lambda v: not v & ABSTRACTCS_BUSY, bound)

    @staticmethod
    def _cmderr(abstractcs: int) -> int:
        return (abstractcs >> ABSTRACTCS_CMDERR_SHIFT) & ABSTRACTCS_CMDERR_MASK

    async def _write_data64(self, value: int) -> None:
        await self._dmi_write(DMI_DATA0, value & 0xFFFF_FFFF)
        await self._dmi_write(DMI_DATA1, value >> 32)

    async def _read_data64(self) -> int:
        low = await self._dmi_read(DMI_DATA0)
        return low | ((await self._dmi_read(DMI_DATA1)) << 32)

    async def _command(self, label: str, command: int, *, expect_cmderr: int = CMDERR_NONE) -> int:
        """Write command, wait for busy 0, require the expected cmderr; return abstractcs."""
        await self._dmi_write(DMI_COMMAND, command)
        abstractcs, _ = await self._wait_idle(label)
        assert self._cmderr(abstractcs) == expect_cmderr, (
            f"{label}: command 0x{command:08X} left cmderr={self._cmderr(abstractcs)} "
            f"expected {expect_cmderr}, abstractcs=0x{abstractcs:08X}"
        )
        return abstractcs

    async def _clear_cmderr(self, label: str) -> int:
        """Write 1s to cmderr, then return abstractcs after requiring cmderr 0 and busy 0."""
        await self._dmi_write(DMI_ABSTRACTCS, ABSTRACTCS_CMDERR_W1C)
        abstractcs, _ = await self._wait_idle(label)
        assert self._cmderr(abstractcs) == CMDERR_NONE, (
            f"{label}: cmderr={self._cmderr(abstractcs)} after writing 1s, "
            f"abstractcs=0x{abstractcs:08X}"
        )
        return abstractcs

    async def _write_gpr(self, label: str, regno: int, value: int) -> None:
        await self._write_data64(value)
        await self._command(label, access_register(GPR_BASE + regno, write=True, transfer=True))

    async def _read_gpr(self, label: str, regno: int, *, aarsize: int = AARSIZE_64) -> int:
        await self._write_data64(0)
        await self._command(
            label,
            access_register(GPR_BASE + regno, write=False, transfer=True, aarsize=aarsize),
        )
        return await self._read_data64()

    async def _issue_leg(self, label: str, command: int) -> tuple[int, int, int]:
        """Write command; return (abstractcs, cmderr, abstractcs after the cmderr clear)."""
        await self._dmi_write(DMI_COMMAND, command)
        abstractcs, _ = await self._wait_idle(label)
        cmderr = self._cmderr(abstractcs)
        cleared = abstractcs
        if cmderr != CMDERR_NONE:
            cleared = await self._clear_cmderr(f"{label}_clear")
        return abstractcs, cmderr, cleared

    async def body(self) -> None:
        clk = cocotb.top.clk_smc_i
        clk_period_ns = await measure_clock_period_ns(clk)
        window_ns = WINDOW_DMI_ACCESSES * TCK_PER_DMI_ACCESS * TCK_PERIOD_NS
        loop_count = math.ceil(window_ns / (LOOP_CLOCKS_PER_ITERATION * clk_period_ns))
        cocotb.log.info(
            "busy window: tck=%d ns clk_smc_i=%.4f ns; %d DMI accesses x %d TCK = %d ns; "
            "%d clocks per iteration at best -> loop count N=%d",
            TCK_PERIOD_NS,
            clk_period_ns,
            WINDOW_DMI_ACCESSES,
            TCK_PER_DMI_ACCESS,
            window_ns,
            LOOP_CLOCKS_PER_ITERATION,
            loop_count,
        )
        for k, word in enumerate(PROGBUF[:2]):
            cocotb.log.info("program word progbuf%d=0x%08X", k, word)
        cocotb.log.info("program words progbuf2..15 = nop 0x%08X", NOP)
        assert LOOP_BRANCH == 0xFE02_9EE3, f"bne x5,x0,-4 encodes 0x{LOOP_BRANCH:08X}"

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
        self._tap = SmcJtagTap(name="smc_jtag_dm_lifecycle", tck_period_ns=TCK_PERIOD_NS)
        self._tap.init_signals()
        await self._tap.reset_tap()
        await self._tap.read_idcode(check=True)
        await self._tap.read_dmstatus()
        dtmcs = await self._tap.read_dtmcs()
        self._abits = ((dtmcs >> 4) & 0x3F) or 7
        self._idle = max((dtmcs >> 12) & 0x7, 5)
        await self._dmi_write(DMI_DMCONTROL, DMCONTROL_DMACTIVE)
        await self._poll("dm_active_poll", DMI_DMSTATUS, lambda v: (v & DMSTATUS_VERSION_MASK) == 2)
        await self._dmi_write(DMI_DMCONTROL, DMCONTROL_DMACTIVE | DMCONTROL_HALTREQ)
        halted, halt_polls = await self._poll(
            "halt_wait", DMI_DMSTATUS, lambda v: bool(v & DMSTATUS_ALLHALTED)
        )
        await self._dmi_write(DMI_DMCONTROL, DMCONTROL_DMACTIVE)
        assert not halted & DMSTATUS_ANYRUNNING, f"after haltreq dmstatus=0x{halted:08X}"
        idle_abstractcs = await self._dmi_read(DMI_ABSTRACTCS)
        assert not idle_abstractcs & ABSTRACTCS_BUSY and self._cmderr(idle_abstractcs) == 0, (
            f"abstractcs=0x{idle_abstractcs:08X} before any command"
        )
        await self._write_gpr("x8_pattern_a", X8, PATTERN_A)
        self._step_done("S1")

        await self._write_gpr("x5_count", X5, loop_count)
        for k, word in enumerate(PROGBUF):
            await self._dmi_write(DMI_PROGBUF0 + k, word)
        self._step_done("S2")

        postexec = access_register(0, write=False, transfer=False, postexec=True)
        await self._dmi_write(DMI_COMMAND, postexec)
        trace: list[int] = []
        first_busy = 0
        busy_polls = 0
        for busy_polls in range(1, BUSY_BOUND + 1):
            abstractcs = await self._dmi_read(DMI_ABSTRACTCS)
            trace.append((abstractcs >> 12) & 1)
            if abstractcs & ABSTRACTCS_BUSY and not first_busy:
                first_busy = abstractcs
            if not abstractcs & ABSTRACTCS_BUSY:
                break
        else:
            raise AssertionError(
                f"loop_wait: busy still 1 after {BUSY_BOUND} DMI reads; {self._state()}"
            )
        loop_cmderr = self._cmderr(abstractcs)
        self._step_done("S3")
        assert 1 in trace, (
            f"abstractcs.busy never read 1 (trace {trace}, N={loop_count}); {self._state()}"
        )
        assert loop_cmderr == CMDERR_NONE, (
            f"cmderr={loop_cmderr} after the loop, 0x{abstractcs:08X}"
        )
        self._set_lifecycle(
            "CHK-DM-BUSY-LIFECYCLE",
            f"abstractcs.busy reads 1 during the loop (trace {trace})",
            f"a JTAG abstractcs read returned busy=1 (abstractcs=0x{first_busy:08X})",
            "no software action: the loop ended and the implicit ebreak returned the hart",
            f"abstractcs=0x{abstractcs:08X} busy=0 cmderr=0",
        )
        self._set_chk(
            "CHK-DM-BUSY-LIFECYCLE",
            f"abstractcs=0x{idle_abstractcs:08X} busy=0 cmderr=0 before any command; busy trace "
            f"{trace} over {busy_polls} polls (bench bound {BUSY_BOUND}); final abstractcs="
            f"0x{abstractcs:08X} busy=0 cmderr=0; halt wait {halt_polls} of {POLL_BOUND}; "
            f"loop count N={loop_count}",
        )

        await self._write_gpr("x6_initial", X6, X6_INITIAL)
        await self._write_gpr("x5_rearm", X5, loop_count)
        await self._write_data64(X6_BUSY_WRITE)
        await self._dmi_write(DMI_COMMAND, postexec)
        before_busy, _ = await self._poll(
            "busy_observe", DMI_ABSTRACTCS, lambda v: bool(v & ABSTRACTCS_BUSY), BUSY_BOUND
        )
        busy_write = access_register(GPR_BASE + X6, write=True, transfer=True)
        await self._dmi_write(DMI_COMMAND, busy_write)
        after_busy, wait_polls = await self._wait_idle("busy_write_wait", BUSY_BOUND)
        busy_cmderr = self._cmderr(after_busy)
        assert busy_cmderr == CMDERR_BUSY, (
            f"command written while busy left cmderr={busy_cmderr}, abstractcs=0x{after_busy:08X}"
        )
        await self._dmi_write(DMI_COMMAND, CMD_QUICK_ACCESS)
        replaced, _ = await self._wait_idle("replace_wait")
        replace_cmderr = self._cmderr(replaced)
        assert replace_cmderr == CMDERR_NOT_SUPPORTED and not replaced & ABSTRACTCS_BUSY, (
            f"Quick Access with cmderr 1 held left abstractcs=0x{replaced:08X}"
        )
        cleared = await self._clear_cmderr("busy_write_clear")
        x6_after = await self._read_gpr("x6_after_busy_write", X6)
        self._step_done("S4")
        assert x6_after == X6_INITIAL, (
            f"x6 reads 0x{x6_after:016X} after the command written while busy, "
            f"initial 0x{X6_INITIAL:016X}, busy-write data 0x{X6_BUSY_WRITE:016X}"
        )
        self._set_lifecycle(
            "CHK-DM-BUSY-WRITE",
            f"abstractcs.cmderr reads 1 after command 0x{busy_write:08X} written while busy=1",
            f"abstractcs=0x{after_busy:08X} cmderr=1 busy=0 after the loop",
            "write 1s to abstractcs.cmderr",
            f"abstractcs=0x{cleared:08X} cmderr=0",
        )
        self._set_chk(
            "CHK-DM-BUSY-WRITE",
            f"abstractcs=0x{before_busy:08X} busy=1 before the write; command 0x{busy_write:08X} "
            f"written while busy left abstractcs=0x{after_busy:08X} cmderr=1 busy=0 after "
            f"{wait_polls} polls (bench bound {BUSY_BOUND}); x6 0x{x6_after:016X} unchanged from "
            f"0x{X6_INITIAL:016X}; after writing 1s abstractcs=0x{cleared:08X} cmderr=0",
        )
        self._set_chk(
            "CHK-DM-CMDERR-REPLACE",
            f"cmderr 1 held (abstractcs=0x{after_busy:08X}), Quick Access 0x{CMD_QUICK_ACCESS:08X} "
            f"left abstractcs=0x{replaced:08X} cmderr=2 busy=0",
        )

        legs = {}
        cmd_a = CMD_QUICK_ACCESS
        cmd_b = access_register(REGNO_OUT_OF_RANGE, write=False, transfer=True)
        cmd_c = access_register(GPR_BASE + X8, write=False, transfer=True, aarsize=AARSIZE_16)
        cmd_d = access_register(REGNO_OUT_OF_RANGE, write=False, transfer=False, aarsize=AARSIZE_16)
        for leg, command in (("a", cmd_a), ("b", cmd_b), ("c", cmd_c), ("d", cmd_d)):
            abstractcs, cmderr, cleared_word = await self._issue_leg(f"leg_{leg}", command)
            legs[leg] = (command, abstractcs, cmderr, cleared_word)
            cocotb.log.info(
                "leg %s: command=0x%08X abstractcs=0x%08X cmderr=%d",
                leg,
                command,
                abstractcs,
                cmderr,
            )
        self._step_done("S5")
        for leg in "abc":
            command, abstractcs, cmderr, _ = legs[leg]
            assert cmderr == CMDERR_NOT_SUPPORTED and not abstractcs & ABSTRACTCS_BUSY, (
                f"leg {leg} command 0x{command:08X} left abstractcs=0x{abstractcs:08X}"
            )
        command_d, abstractcs_d, cmderr_d, _ = legs["d"]
        assert cmderr_d == CMDERR_NONE and not abstractcs_d & ABSTRACTCS_BUSY, (
            f"transfer-clear command 0x{command_d:08X} left abstractcs=0x{abstractcs_d:08X}"
        )
        self._set_lifecycle(
            "CHK-DM-CMDERR-CMDTYPE",
            f"abstractcs.cmderr reads 2 after Quick Access command 0x{cmd_a:08X}",
            f"abstractcs=0x{legs['a'][1]:08X} cmderr=2 busy=0",
            "write 1s to abstractcs.cmderr",
            f"abstractcs=0x{legs['a'][3]:08X} cmderr=0",
        )
        self._set_chk(
            "CHK-DM-CMDERR-CMDTYPE",
            f"Quick Access command=0x{cmd_a:08X} left abstractcs=0x{legs['a'][1]:08X} "
            f"cmderr=2 busy=0",
        )
        self._set_chk(
            "CHK-DM-CMDERR-REGNO",
            f"transfer=1 aarsize=3 regno=0x{REGNO_OUT_OF_RANGE:04X} command=0x{cmd_b:08X} left "
            f"abstractcs=0x{legs['b'][1]:08X} cmderr=2",
        )
        self._set_chk(
            "CHK-DM-CMDERR-AARSIZE",
            f"transfer=1 aarsize=1 regno=0x{GPR_BASE + X8:04X} command=0x{cmd_c:08X} left "
            f"abstractcs=0x{legs['c'][1]:08X} cmderr=2",
        )
        self._set_chk(
            "CHK-DM-CMDERR-NOTRANSFER",
            f"transfer=0 aarsize=1 regno=0x{REGNO_OUT_OF_RANGE:04X} command=0x{cmd_d:08X} left "
            f"abstractcs=0x{abstractcs_d:08X} cmderr=0 busy=0; rejected legs "
            f"0x{legs['b'][1]:08X} (regno), 0x{legs['c'][1]:08X} (aarsize)",
        )

        await self._write_data64(PATTERN_B)
        await self._command("store_leg_a", cmd_a, expect_cmderr=CMDERR_NOT_SUPPORTED)
        store_command = access_register(GPR_BASE + X8, write=True, transfer=True)
        await self._dmi_write(DMI_COMMAND, store_command)
        command_back = await self._dmi_read(DMI_COMMAND)
        store_abstractcs, _ = await self._wait_idle("store_wait")
        await self._clear_cmderr("store_clear")
        x8_after = await self._read_gpr("x8_after_store", X8)
        self._step_done("S6")
        assert command_back == store_command, (
            f"command read back 0x{command_back:08X}, written 0x{store_command:08X}"
        )
        assert self._cmderr(store_abstractcs) == CMDERR_NOT_SUPPORTED, (
            f"cmderr changed to {self._cmderr(store_abstractcs)}, 0x{store_abstractcs:08X}"
        )
        assert x8_after == PATTERN_A, (
            f"x8 reads 0x{x8_after:016X}, pattern A 0x{PATTERN_A:016X}, "
            f"pattern B 0x{PATTERN_B:016X}"
        )
        self._set_chk(
            "CHK-DM-CMDERR-STORE",
            f"command written while busy=0 cmderr=2 read back 0x{command_back:08X} (earlier "
            f"0x{cmd_a:08X}); abstractcs=0x{store_abstractcs:08X} cmderr=2",
        )
        self._set_chk(
            "CHK-DM-CMDERR-NOEXEC",
            f"x8 reads 0x{x8_after:016X} after the pattern-B write command issued with cmderr=2 "
            f"and the clear; pattern A 0x{PATTERN_A:016X} written in S1, pattern B "
            f"0x{PATTERN_B:016X} not stored",
        )

        await ClockCycles(clk, 2)
        await self._write_data64(PATTERN_C)
        write32 = access_register(GPR_BASE + X8, write=True, transfer=True, aarsize=AARSIZE_32)
        write_abstractcs = await self._command("gpr32_write", write32)
        await self._write_data64(0)
        read32 = access_register(GPR_BASE + X8, write=False, transfer=True, aarsize=AARSIZE_32)
        read_abstractcs = await self._command("gpr32_read", read32)
        x8_low = await self._dmi_read(DMI_DATA0)
        self.x8_low = x8_low
        self._step_done("S7")
        assert x8_low == PATTERN_C, f"x8 low word reads 0x{x8_low:08X}, wrote 0x{PATTERN_C:08X}"
        self._set_chk(
            "CHK-DM-CMDERR-RECOVER-GPR32",
            f"aarsize=2 write command=0x{write32:08X} left abstractcs=0x{write_abstractcs:08X} "
            f"cmderr=0 busy=0; read command=0x{read32:08X} left abstractcs="
            f"0x{read_abstractcs:08X}; x8 low word 0x{x8_low:08X} wrote 0x{PATTERN_C:08X}",
        )

        self._emit_checkers()
        self._assert_fence()
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: 6 bounded waits: dmi_busy_retry=%d enforced-by=%s "
            "fail-on-expiry=SmcJtagTapError last=%s; dm_active_poll=%d fail-on-expiry="
            "AssertionError last=dmstatus; halt_wait=%d fail-on-expiry=AssertionError "
            "last=dmstatus; idle_wait=%d fail-on-expiry=AssertionError last=abstractcs; "
            "loop_wait=%d fail-on-expiry=AssertionError last=abstractcs; "
            "busy_observe=%d fail-on-expiry=AssertionError last=abstractcs; "
            "busy_write_wait=%d fail-on-expiry=AssertionError last=abstractcs",
            VIP_DMI_BUSY_RETRIES,
            VIP_FILE,
            self._state(),
            POLL_BOUND,
            POLL_BOUND,
            POLL_BOUND,
            BUSY_BOUND,
            BUSY_BOUND,
            BUSY_BOUND,
        )
        self.dm_ok = True
