# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CPU Debug Module system bus access while the cluster uncore reset is held, and after it.

Spec sources: hw/sys/smc/doc/cpu.adoc (Debug: the system bus access engine of the Debug
Module is reset with the uncore while its DMI registers are not; a system bus access requested
while the uncore reset is applied is not started and is not replayed after the release; `sbcs`
reads `sbbusy` 0 and `sberror` 0, `sbaddress0` does not advance under `sbautoincrement`, and a
write leaves its target unchanged; a debugger checks `RESET_CTRL.uncore_reset_n_n0_scan` 1 and
`RESET_TIMEOUT.reset_applied` 0 before relying on a system bus access),
hw/sys/smc/regs/blocks/cpu_ctrl/cpu_ctrl.rdl (RESET_CTRL uncore reset, RESET_TIMEOUT,
SCRATCH), RISC-V External Debug Support 0.13.2 section 3.12.21 (sbcs).

The `CHK-*` lines grade the write before the hold, the `sbdata0` scan under the hold reaching
the Debug Module, the DMI readbacks of the write requested under the hold (`sbbusy` 0,
`sberror` 0, `sbbusyerror` 0, `sbaddress0` not advanced), the held `CPU_CTRL.SCRATCH` word
unchanged during and after the hold, and the write after the release landing; the `data0`
and `dmstatus` readbacks under the hold are printed.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time

from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_cpu_vip_utils import (
    CPU_CTRL_RESET_CTRL,
    CPU_RESET_CTRL_DEBUG_RELEASE,
    cpu_ctrl_u32,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_jtag_protocol_vip import SmcJtagTap

DEBUG_RESET_N = cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__DEBUG_RESET_N_N0_SCAN_bm")
UNCORE_N = cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__UNCORE_RESET_N_N0_SCAN_bm")
RESET_TIMEOUT = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_TIMEOUT_BASE_ADDR")
TIMEOUT_VALUE_BP = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__TIMEOUT_VALUE_bp")
TIMEOUT_MODE_BM = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__TIMEOUT_MODE_bm")
RESET_APPLIED = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__RESET_APPLIED_bm")
FORCE_AFTER_32 = (32 << TIMEOUT_VALUE_BP) | TIMEOUT_MODE_BM
UNCORE_HELD = CPU_RESET_CTRL_DEBUG_RELEASE & ~UNCORE_N

# CPU_CTRL.SCRATCH words sit outside the cluster: a system bus access reaches them through
# the cluster MMIO port, and the SEP_IN AXI driver reads them while the uncore is held.
SCRATCH_BEFORE = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", 4)
SCRATCH_HELD = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", 5)
SCRATCH_AFTER = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", 6)

DMI_DATA0 = 0x04
DMI_DMSTATUS = 0x11
DMI_SBCS = 0x38
DMI_SBADDRESS0 = 0x39
DMI_SBADDRESS1 = 0x3A
DMI_SBDATA0 = 0x3C

DMSTATUS_VERSION_MASK = 0xF
SBCS_BUSYERROR = 1 << 22
SBCS_BUSY = 1 << 21
SBCS_ACCESS_SHIFT = 17
SBCS_AUTOINCREMENT = 1 << 16
SBCS_ERROR_SHIFT = 12
SBCS_ERROR_MASK = 0x7
SBCS_ERROR_CLEAR = SBCS_ERROR_MASK << SBCS_ERROR_SHIFT
SBACCESS_32 = 2
SBACCESS_32_BYTES = 4

PATTERN_BEFORE = 0x1A2B_3C4D
PATTERN_HELD = 0xB1C2_D3E4
DATA0_HELD = 0x7C8D_9EAF
PATTERN_AFTER = 0x5F6A_7B8C

STEPS = tuple(f"S{i}" for i in range(1, 7))
CHK_AFTER_STEP = (
    ("CHK-DM-SBA-NOT-STARTED-UNDER-HOLD", "S4"),
    ("CHK-DM-SBA-WORD-UNCHANGED-UNDER-HOLD", "S4"),
    ("CHK-DM-SBA-RESUMES-AFTER-RELEASE", "S5"),
)
FENCE_TERMS = {
    "S1": "RELEASED_ACTIVE",
    "S2": "SBA_WRITE_BEFORE_HOLD",
    "S3": "UNCORE_HELD",
    "S4": "DMI_UNDER_HOLD",
    "S5": "SBA_AFTER_RELEASE",
    "S6": "RESTORED",
}
SBBUSY_BOUND = 16
_CSR_POLL_BOUND = 64
IDLE_CYCLES = 8
VIP_FILE = "seq_lib/smc_jtag_protocol_vip.py"
VIP_DMI_BUSY_RETRIES = 4


def _sberror(sbcs: int) -> int:
    return (sbcs >> SBCS_ERROR_SHIFT) & SBCS_ERROR_MASK


def _sbcs_text(sbcs: int) -> str:
    return (
        f"sbcs=0x{sbcs:08X} (sbbusy={int(bool(sbcs & SBCS_BUSY))} sberror={_sberror(sbcs)} "
        f"sbbusyerror={int(bool(sbcs & SBCS_BUSYERROR))})"
    )


class smc_jtag_dm_sba_uncore_hold_test_seq(SmcCsrSeq):
    """Write CPU_CTRL.SCRATCH words over the system bus before, during and after an uncore
    reset hold and grade what the DMI shows for the write requested under the hold."""

    def __init__(self, name: str = "smc_jtag_dm_sba_uncore_hold_test_seq") -> None:
        super().__init__(name)
        self.dm_ok: bool = False
        self.after_word: int = 0
        self._tap: SmcJtagTap | None = None
        self._abits: int = 7
        self._idle: int = 5
        self._events: list[tuple[str, str, int]] = []
        self._last_sbcs = 0
        self._last_dmi = 0
        self._polls: dict[str, int] = {}

    async def _dmi_read(self, addr: int) -> int:
        assert self._tap is not None
        value = await self._tap.dmi_read(addr, abits=self._abits, idle=self._idle)
        self._last_dmi = value
        if addr == DMI_SBCS:
            self._last_sbcs = value
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

    async def _sba_write(self, label: str, addr: int, data: int) -> tuple[int, int, int]:
        """Start a 32-bit system bus write with sbautoincrement set and sberror cleared; read
        sbcs until sbbusy is 0 or SBBUSY_BOUND reads pass; return (sbcs, reads, sbaddress0),
        where sbaddress0 has advanced by 4 once the Debug Module completed the access."""
        await self._dmi_write(
            DMI_SBCS,
            (SBACCESS_32 << SBCS_ACCESS_SHIFT) | SBCS_AUTOINCREMENT | SBCS_ERROR_CLEAR,
        )
        await self._dmi_write(DMI_SBADDRESS1, 0)
        await self._dmi_write(DMI_SBADDRESS0, addr)
        await self._dmi_write(DMI_SBDATA0, data)
        sbcs = 0
        reads = SBBUSY_BOUND
        for n in range(1, SBBUSY_BOUND + 1):
            sbcs = await self._dmi_read(DMI_SBCS)
            if not sbcs & SBCS_BUSY:
                reads = n
                break
        self._polls[label] = reads
        return sbcs, reads, await self._dmi_read(DMI_SBADDRESS0)

    async def _sba_write_clean(self, label: str, addr: int, data: int) -> int:
        sbcs, reads, sbaddress = await self._sba_write(label, addr, data)
        assert not sbcs & SBCS_BUSY and _sberror(sbcs) == 0, (
            f"{label}: {_sbcs_text(sbcs)} after {reads} reads"
        )
        assert sbaddress == addr + SBACCESS_32_BYTES, (
            f"{label}: sbaddress0 reads 0x{sbaddress:08X} after the access, want "
            f"0x{addr + SBACCESS_32_BYTES:08X} (sbautoincrement)"
        )
        return sbcs

    async def _axi_read(self, name: str, addr: int) -> int:
        await ClockCycles(cocotb.top.clk_smc_i, IDLE_CYCLES)
        return await self.csr_read(name, addr, length=8)

    async def _axi_write(self, name: str, addr: int, data: int) -> None:
        await ClockCycles(cocotb.top.clk_smc_i, IDLE_CYCLES)
        await self.csr_write(name, addr, data, length=8)

    async def _await_applied(self, label: str, want: bool) -> int:
        word = 0
        for n in range(1, _CSR_POLL_BOUND + 1):
            word = await self.csr_read(f"{label}_{n}", RESET_TIMEOUT, length=8)
            if bool(word & RESET_APPLIED) == want:
                self._polls[label] = n
                return word
        raise AssertionError(
            f"{label}: RESET_TIMEOUT=0x{word:X} reset_applied never read {int(want)} "
            f"in {_CSR_POLL_BOUND} reads"
        )

    async def body(self) -> None:
        clk = cocotb.top.clk_smc_i
        timeout_idle = await self.csr_read("RESET_TIMEOUT_IDLE", RESET_TIMEOUT, length=8)
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
        self._tap = SmcJtagTap(name="smc_jtag_dm_sba_hold")
        self._tap.init_signals()
        await self._tap.reset_tap()
        await self._tap.read_idcode(check=True)
        await self._tap.read_dmstatus()
        dtmcs = await self._tap.read_dtmcs()
        self._abits = ((dtmcs >> 4) & 0x3F) or 7
        self._idle = max((dtmcs >> 12) & 0x7, 5)
        sbcs0 = await self._dmi_read(DMI_SBCS)
        dmstatus0 = await self._dmi_read(DMI_DMSTATUS)
        self._step_done("S1")
        assert not sbcs0 & SBCS_BUSY and _sberror(sbcs0) == 0, f"idle sbcs=0x{sbcs0:08X}"

        for name, addr in (
            ("BEFORE", SCRATCH_BEFORE),
            ("HELD", SCRATCH_HELD),
            ("AFTER", SCRATCH_AFTER),
        ):
            await self._axi_write(f"AXI_WR_SCRATCH_{name}_ZERO", addr, 0)
        sbcs_before = await self._sba_write_clean("sba_before", SCRATCH_BEFORE, PATTERN_BEFORE)
        before = await self._axi_read("AXI_RD_SCRATCH_BEFORE", SCRATCH_BEFORE)
        held_zero = await self._axi_read("AXI_RD_SCRATCH_HELD_ZERO", SCRATCH_HELD)
        self._step_done("S2")
        assert before == PATTERN_BEFORE, (
            f"system bus write before the hold: SCRATCH[4] reads 0x{before:X} want "
            f"0x{PATTERN_BEFORE:08X} ({_sbcs_text(sbcs_before)})"
        )
        assert held_zero == 0, f"SCRATCH[5]=0x{held_zero:X} before the hold"

        await self.csr_write("RESET_TIMEOUT_FORCE", RESET_TIMEOUT, FORCE_AFTER_32, length=8)
        await self.csr_write("UNCORE_HOLD", CPU_CTRL_RESET_CTRL, UNCORE_HELD, length=8)
        held_ctrl = await self.csr_read("UNCORE_HOLD_RB", CPU_CTRL_RESET_CTRL, length=8)
        applied = await self._await_applied("uncore_applied", True)
        self._step_done("S3")
        assert held_ctrl == UNCORE_HELD, f"RESET_CTRL read 0x{held_ctrl:X} want 0x{UNCORE_HELD:X}"

        sbcs_held, reads_held, sbaddress_held = await self._sba_write(
            "sba_held", SCRATCH_HELD, PATTERN_HELD
        )
        sbdata_held = await self._dmi_read(DMI_SBDATA0)
        await self._dmi_write(DMI_DATA0, DATA0_HELD)
        data0_held = await self._dmi_read(DMI_DATA0)
        dmstatus_held = await self._dmi_read(DMI_DMSTATUS)
        held_during = await self._axi_read("AXI_RD_SCRATCH_HELD_DURING", SCRATCH_HELD)
        applied_still = await self.csr_read("UNCORE_APPLIED_STILL", RESET_TIMEOUT, length=8)
        self._step_done("S4")
        assert applied_still & RESET_APPLIED, (
            f"the uncore hold ended during the scans: RESET_TIMEOUT reads 0x{applied_still:X} "
            f"after them (0x{applied:X} before)"
        )
        assert sbdata_held == PATTERN_HELD, (
            f"the sbdata0 scan under the hold did not reach the Debug Module: sbdata0 reads "
            f"0x{sbdata_held:08X}, want 0x{PATTERN_HELD:08X} ({_sbcs_text(sbcs_held)})"
        )
        assert (
            not sbcs_held & SBCS_BUSY
            and _sberror(sbcs_held) == 0
            and not sbcs_held & SBCS_BUSYERROR
        ), (
            f"the system bus write requested under the uncore hold is reported: "
            f"{_sbcs_text(sbcs_held)} after {reads_held} reads of {SBBUSY_BOUND}, want sbbusy 0, "
            f"sberror 0 and sbbusyerror 0"
        )
        assert sbaddress_held == SCRATCH_HELD, (
            f"sbaddress0 advanced for the system bus write requested under the uncore hold: "
            f"reads 0x{sbaddress_held:08X}, want 0x{SCRATCH_HELD:08X} (sbautoincrement set)"
        )
        self._chk(
            "CHK-DM-SBA-NOT-STARTED-UNDER-HOLD",
            f"RESET_CTRL=0x{held_ctrl:X} RESET_TIMEOUT=0x{applied:X} (reset_applied in "
            f"{self._polls['uncore_applied']} reads, still set after the scans: "
            f"0x{applied_still:X}): 32-bit system bus write of "
            f"0x{PATTERN_HELD:08X} to SCRATCH[5] ended {_sbcs_text(sbcs_held)} after "
            f"{reads_held} reads of {SBBUSY_BOUND}; sbaddress0 written 0x{SCRATCH_HELD:08X} "
            f"reads 0x{sbaddress_held:08X} after the scan (sbautoincrement set, not advanced); "
            f"sbdata0 reads 0x{sbdata_held:08X}; data0 written 0x{DATA0_HELD:08X} reads "
            f"0x{data0_held:08X} and dmstatus reads 0x{dmstatus_held:08X} (version "
            f"{dmstatus_held & DMSTATUS_VERSION_MASK}; 0x{dmstatus0:08X} before the hold), "
            f"printed",
        )
        assert held_during == 0, (
            f"system bus write under the uncore hold landed: SCRATCH[5] reads 0x{held_during:X} "
            f"during the hold ({_sbcs_text(sbcs_held)})"
        )
        self._chk(
            "CHK-DM-SBA-WORD-UNCHANGED-UNDER-HOLD",
            f"SCRATCH[5] reads 0x{held_during:X} over AXI during the hold after the system bus "
            f"write of 0x{PATTERN_HELD:08X}, whose sbdata0 scan reached the Debug Module "
            f"(sbdata0 reads 0x{sbdata_held:08X}; sbaddress0 reads 0x{sbaddress_held:08X}; "
            f"{_sbcs_text(sbcs_held)}); positive control before "
            f"the hold: SCRATCH[4] wrote 0x{PATTERN_BEFORE:08X} read 0x{before:X} "
            f"({_sbcs_text(sbcs_before)})",
        )

        await self.csr_write(
            "UNCORE_RELEASE", CPU_CTRL_RESET_CTRL, CPU_RESET_CTRL_DEBUG_RELEASE, length=8
        )
        released = await self._await_applied("uncore_released", False)
        await ClockCycles(clk, 64)
        sbcs_release = await self._dmi_read(DMI_SBCS)
        dmstatus_release = await self._dmi_read(DMI_DMSTATUS)
        await self._dmi_write(
            DMI_SBCS, (SBACCESS_32 << SBCS_ACCESS_SHIFT) | SBCS_ERROR_CLEAR | SBCS_BUSYERROR
        )
        sbcs_cleared = await self._dmi_read(DMI_SBCS)
        held_after = await self._axi_read("AXI_RD_SCRATCH_HELD_AFTER", SCRATCH_HELD)
        sbcs_after = await self._sba_write_clean("sba_after", SCRATCH_AFTER, PATTERN_AFTER)
        self.after_word = await self._axi_read("AXI_RD_SCRATCH_AFTER", SCRATCH_AFTER)
        held_after_next = await self._axi_read("AXI_RD_SCRATCH_HELD_AFTER_NEXT", SCRATCH_HELD)
        self._step_done("S5")
        assert not sbcs_cleared & SBCS_BUSY and _sberror(sbcs_cleared) == 0, (
            f"after the release and the sberror clear: {_sbcs_text(sbcs_cleared)} "
            f"(before the clear {_sbcs_text(sbcs_release)})"
        )
        assert held_after == 0 and held_after_next == 0, (
            f"the system bus write requested under the uncore hold landed after the release: "
            f"SCRATCH[5] reads 0x{held_after:X} after the release and 0x{held_after_next:X} "
            f"after the next system bus write ({_sbcs_text(sbcs_release)})"
        )
        assert self.after_word == PATTERN_AFTER, (
            f"system bus write after the release: SCRATCH[6] reads 0x{self.after_word:X} want "
            f"0x{PATTERN_AFTER:08X} ({_sbcs_text(sbcs_after)})"
        )
        self._chk(
            "CHK-DM-SBA-RESUMES-AFTER-RELEASE",
            f"after RESET_CTRL=0x{CPU_RESET_CTRL_DEBUG_RELEASE:X} (RESET_TIMEOUT=0x{released:X} in "
            f"{self._polls['uncore_released']} reads): {_sbcs_text(sbcs_release)}, dmstatus "
            f"0x{dmstatus_release:08X}, after the sberror clear {_sbcs_text(sbcs_cleared)}; a new "
            f"write 0x{PATTERN_AFTER:08X} to SCRATCH[6] ended {_sbcs_text(sbcs_after)} in "
            f"{self._polls['sba_after']} reads and SCRATCH[6] reads 0x{self.after_word:X}; "
            f"SCRATCH[5] reads 0x{held_after:X} after the release and 0x{held_after_next:X} "
            f"after that write (the write requested under the hold is not replayed)",
        )

        await self.csr_write("RESET_TIMEOUT_RESTORE", RESET_TIMEOUT, timeout_idle, length=8)
        await self.csr_read(
            "RESET_TIMEOUT_RESTORE_RB", RESET_TIMEOUT, length=8, expected=timeout_idle
        )
        await ClockCycles(clk, 2)
        self._step_done("S6")

        self._assert_fence()
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: 4 bounded waits: dmi_busy_retry=%d enforced-by=%s "
            "fail-on-expiry=SmcJtagTapError last=DMI response 0x%08X; "
            "dm_active_poll=16 enforced-by=%s fail-on-expiry=AssertionError "
            "last=dmcontrol.dmactive; sbbusy_wait=%d fail-on-expiry=AssertionError "
            "last=sbcs 0x%08X; reset_applied_wait=%d "
            "fail-on-expiry=AssertionError last=RESET_TIMEOUT (max reads used %d)",
            VIP_DMI_BUSY_RETRIES,
            VIP_FILE,
            self._last_dmi,
            VIP_FILE,
            SBBUSY_BOUND,
            self._last_sbcs,
            _CSR_POLL_BOUND,
            max(self._polls.values()),
        )
        self.dm_ok = True
