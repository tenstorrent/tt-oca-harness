# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CPU Debug Module system bus access into the scratchpad memory over the DMI.

Spec sources: hw/sys/smc/doc/cpu.adoc (Debug Module capability readbacks, DMI register
inventory and system bus access), hw/sys/smc/doc/memmap.adoc (local alias),
RISC-V External Debug Support 0.13.2 sections 3.12.21 to 3.12.26,
hw/sys/smc/regs/gen/c/smc_addr.h (scratchpad region).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time

from .smc_addr_map import SPM_MEMORY_BASE, SPM_MEMORY_SIZE
from .smc_cpu_vip_utils import (
    CPU_CTRL_RESET_CTRL,
    CPU_RESET_CTRL_DEBUG_RELEASE,
    cpu_ctrl_u32,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_jtag_protocol_vip import SmcJtagTap

DEBUG_RESET_N = cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__DEBUG_RESET_N_N0_SCAN_bm")

DMI_DATA0 = 0x04
DMI_SBCS = 0x38
DMI_SBADDRESS0 = 0x39
DMI_SBADDRESS1 = 0x3A
DMI_SBDATA0 = 0x3C
DMI_SBDATA1 = 0x3D

SBCS_VERSION_SHIFT = 29
SBCS_VERSION_MASK = 0x7
SBCS_BUSY = 1 << 21
SBCS_READONADDR = 1 << 20
SBCS_ACCESS_SHIFT = 17
SBCS_ERROR_SHIFT = 12
SBCS_ERROR_MASK = 0x7
SBCS_ERROR_CLEAR = SBCS_ERROR_MASK << SBCS_ERROR_SHIFT
SBCS_ASIZE_SHIFT = 5
SBCS_ASIZE_MASK = 0x7F
SBCS_CAPS_MASK = 0x1F

EXPECTED_SBVERSION = 1
EXPECTED_SBASIZE = 56
# sbaccess8, 16, 32, 64, 128 in bits 0..4.
EXPECTED_SBACCESS_CAPS = 0b01111

SBACCESS_8 = 0
SBACCESS_16 = 1
SBACCESS_32 = 2
SBACCESS_64 = 3

ALL_ONES = 0xFFFF_FFFF
DATA0_PATTERN = 0xA55A_C33C
NOT_IMPLEMENTED_DMI = (
    ("data4", 0x08),
    ("hartinfo", 0x12),
    ("confstrptr0", 0x19),
    ("nextdm", 0x1D),
    ("authdata", 0x30),
    ("haltsum2", 0x34),
    ("sbaddress2", 0x3B),
    ("sbdata2", 0x3E),
)

WORD_A = SPM_MEMORY_BASE + 0x0000_0200
WORD_B = SPM_MEMORY_BASE + 0x000A_3F04
PATTERN_A = 0x1357_9BDF
PATTERN_B = 0x2468_ACE0
# Per width: (sbaccess, byte width, dword-aligned address, byte lane, background, pattern).
WIDTH_CASES = (
    (SBACCESS_8, 1, SPM_MEMORY_BASE + 0x0000_0518, 3, 0x1122_3344_5566_7788, 0xA7),
    (SBACCESS_16, 2, SPM_MEMORY_BASE + 0x0002_1A40, 6, 0x99AA_BBCC_DDEE_FF00, 0x3C5A),
    (SBACCESS_32, 4, SPM_MEMORY_BASE + 0x0004_0C80, 4, 0x0F1E_2D3C_4B5A_6978, 0xC0DE_F00D),
    (
        SBACCESS_64,
        8,
        SPM_MEMORY_BASE + 0x0007_7D00,
        0,
        0xFEDC_BA98_7654_3210,
        0x0BAD_CAFE_8BAD_F00D,
    ),
)
WORD_64 = SPM_MEMORY_BASE + 0x000C_0A30
PATTERN_64_LO = 0xD00D_1234
PATTERN_64_HI = 0xBEEF_5678
WORD_AXI = SPM_MEMORY_BASE + 0x000E_0F58
PATTERN_AXI = 0x7E57_B00C

STEPS = tuple(f"S{i}" for i in range(1, 8))
CHK_BY_STEP = {
    "S1": "CHK-DM-SBCS-CAPS",
    "S2": "CHK-DM-NOT-IMPL-DMI",
    "S3": "CHK-DM-SBA-WRITE",
    "S4": "CHK-DM-SBA-READ",
    "S5": "CHK-DM-SBA-WIDTHS",
    "S6": "CHK-DM-SBA-64BIT",
    "S7": "CHK-DM-SBA-VISIBLE",
}
FENCE_TERMS = {
    "S1": "SBCS_CAPS",
    "S2": "NOT_IMPLEMENTED_DMI",
    "S3": "SBA_WRITE_32",
    "S4": "SBA_READ_32",
    "S5": "SBA_WIDTHS",
    "S6": "SBA_64BIT",
    "S7": "AXI_VISIBLE",
}
SBBUSY_BOUND = 16
VIP_FILE = "seq_lib/smc_jtag_protocol_vip.py"
VIP_DMI_BUSY_RETRIES = 4
IDLE_CYCLES = 8


def _mask(width: int) -> int:
    return (1 << (8 * width)) - 1


class smc_jtag_dm_sba_scratchpad_test_seq(SmcCsrSeq):
    """Write and read the scratchpad through the Debug Module system bus and the AXI driver."""

    def __init__(self, name: str = "smc_jtag_dm_sba_scratchpad_test_seq") -> None:
        super().__init__(name)
        self.dm_ok: bool = False
        self.expected_word: int = (PATTERN_64_HI << 32) | PATTERN_64_LO
        self.observed_word: int = 0
        self._tap: SmcJtagTap | None = None
        self._abits: int = 7
        self._idle: int = 5
        self._events: list[tuple[str, str, int]] = []
        self._last_sbcs = 0
        self._last_dmi = 0
        self._polls: list[int] = []

    async def _dmi_read(self, addr: int) -> int:
        assert self._tap is not None
        value = await self._tap.dmi_read(addr, abits=self._abits, idle=self._idle)
        self._last_dmi = value
        return value

    async def _dmi_write(self, addr: int, data: int) -> None:
        assert self._tap is not None
        await self._tap.dmi_write(addr, data, abits=self._abits, idle=self._idle)

    def _step_done(self, step: str) -> None:
        self._events.append(("step", step, int(get_sim_time("ps"))))

    def _chk(self, step: str, text: str) -> None:
        cid = CHK_BY_STEP[step]
        cocotb.log.info("%s: %s", cid, text)
        self._events.append(("chk", cid, int(get_sim_time("ps"))))

    def _assert_fence(self) -> None:
        steps = [e for e in self._events if e[0] == "step"]
        assert [e[1] for e in steps] == list(STEPS), f"step order {[e[1] for e in steps]}"
        stamps = [e[2] for e in steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        chks = [e for e in self._events if e[0] == "chk"]
        expected = [CHK_BY_STEP[s] for s in STEPS]
        assert [c[1] for c in chks] == expected, f"checker order {[c[1] for c in chks]}"
        for chk, step_event, step in zip(chks, steps, STEPS):
            assert self._events.index(chk) > self._events.index(step_event), (
                f"{chk[1]} printed before {step} completed"
            )
            assert chk[2] >= step_event[2], f"{chk[1]} printed before the {step} stamp"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(FENCE_TERMS[e[1]] for e in steps),
            ", ".join(c[1] for c in chks),
            ",".join(str(s) for s in stamps),
        )

    async def _wait_sba_idle(self, label: str) -> int:
        """Read sbcs until sbbusy is 0; require sberror 0; raise after SBBUSY_BOUND reads."""
        for n in range(1, SBBUSY_BOUND + 1):
            sbcs = await self._dmi_read(DMI_SBCS)
            self._last_sbcs = sbcs
            if not sbcs & SBCS_BUSY:
                error = (sbcs >> SBCS_ERROR_SHIFT) & SBCS_ERROR_MASK
                assert error == 0, f"{label}: sberror={error} sbcs=0x{sbcs:08X}"
                self._polls.append(n)
                return sbcs
        raise AssertionError(
            f"{label}: sbbusy still set after {SBBUSY_BOUND} sbcs reads; "
            f"last sbcs=0x{self._last_sbcs:08X} last DMI response=0x{self._last_dmi:08X}"
        )

    async def _sba_write(self, label: str, access: int, addr: int, lo: int, hi: int | None = None):
        await self._dmi_write(DMI_SBCS, (access << SBCS_ACCESS_SHIFT) | SBCS_ERROR_CLEAR)
        await self._dmi_write(DMI_SBADDRESS1, 0)
        await self._dmi_write(DMI_SBADDRESS0, addr)
        if hi is not None:
            await self._dmi_write(DMI_SBDATA1, hi)
        await self._dmi_write(DMI_SBDATA0, lo)
        return await self._wait_sba_idle(label)

    async def _sba_read(self, label: str, access: int, addr: int, *, wide: bool = False):
        await self._dmi_write(
            DMI_SBCS, SBCS_READONADDR | (access << SBCS_ACCESS_SHIFT) | SBCS_ERROR_CLEAR
        )
        await self._dmi_write(DMI_SBADDRESS1, 0)
        await self._dmi_write(DMI_SBADDRESS0, addr)
        await self._wait_sba_idle(label)
        lo = await self._dmi_read(DMI_SBDATA0)
        hi = await self._dmi_read(DMI_SBDATA1) if wide else 0
        return (hi << 32) | lo

    async def _axi_read(self, name: str, addr: int, length: int) -> int:
        await ClockCycles(cocotb.top.clk_smc_i, IDLE_CYCLES)
        return await self.csr_read(name, addr, length=length)

    async def body(self) -> None:
        clk = cocotb.top.clk_smc_i
        assert SPM_MEMORY_BASE + SPM_MEMORY_SIZE > WORD_AXI + 4
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
        self._tap = SmcJtagTap(name="smc_jtag_dm_sba")
        self._tap.init_signals()
        await self._tap.reset_tap()
        await self._tap.read_idcode(check=True)
        await self._tap.read_dmstatus()
        dtmcs = await self._tap.read_dtmcs()
        self._abits = ((dtmcs >> 4) & 0x3F) or 7
        self._idle = max((dtmcs >> 12) & 0x7, 5)

        sbcs = await self._dmi_read(DMI_SBCS)
        self._step_done("S1")
        sbversion = (sbcs >> SBCS_VERSION_SHIFT) & SBCS_VERSION_MASK
        sbasize = (sbcs >> SBCS_ASIZE_SHIFT) & SBCS_ASIZE_MASK
        caps = sbcs & SBCS_CAPS_MASK
        assert sbversion == EXPECTED_SBVERSION, f"sbversion={sbversion} sbcs=0x{sbcs:08X}"
        assert sbasize == EXPECTED_SBASIZE, f"sbasize={sbasize} sbcs=0x{sbcs:08X}"
        assert caps == EXPECTED_SBACCESS_CAPS, (
            f"sbaccess[128,64,32,16,8]={caps:05b} sbcs=0x{sbcs:08X}"
        )
        self._chk(
            "S1",
            f"sbcs=0x{sbcs:08X} sbversion={sbversion} sbasize={sbasize} sbaccess8={caps & 1} "
            f"sbaccess16={(caps >> 1) & 1} sbaccess32={(caps >> 2) & 1} "
            f"sbaccess64={(caps >> 3) & 1} sbaccess128={(caps >> 4) & 1}",
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
        await self._dmi_write(DMI_DATA0, DATA0_PATTERN)
        data0 = await self._dmi_read(DMI_DATA0)
        self._step_done("S2")
        assert data0 == DATA0_PATTERN, f"data0 wrote 0x{DATA0_PATTERN:08X} read 0x{data0:08X}"
        self._chk(
            "S2",
            f"before/after a write of 0x{ALL_ONES:08X}: {', '.join(rows)}; positive control "
            f"data0 wrote 0x{DATA0_PATTERN:08X} read 0x{data0:08X}",
        )

        await self._sba_write("sba_write_a", SBACCESS_32, WORD_A, PATTERN_A)
        addr0_a = await self._dmi_read(DMI_SBADDRESS0)
        await self._sba_write("sba_write_b", SBACCESS_32, WORD_B, PATTERN_B)
        addr0_b = await self._dmi_read(DMI_SBADDRESS0)
        addr1 = await self._dmi_read(DMI_SBADDRESS1)
        sbcs_w = self._last_sbcs
        self._step_done("S3")
        assert PATTERN_A != PATTERN_B and WORD_A != WORD_B
        assert addr0_a == WORD_A, f"sbaddress0 wrote 0x{WORD_A:08X} read 0x{addr0_a:08X}"
        assert addr0_b == WORD_B, f"sbaddress0 wrote 0x{WORD_B:08X} read 0x{addr0_b:08X}"
        self._chk(
            "S3",
            f"32-bit writes 0x{PATTERN_A:08X}@0x{WORD_A:08X} and 0x{PATTERN_B:08X}@0x{WORD_B:08X} "
            f"each ended sbbusy=0 sberror=0 (last sbcs=0x{sbcs_w:08X}); sbaddress0 read back "
            f"0x{addr0_a:08X} and 0x{addr0_b:08X}; sbaddress1 (written 0 by the sequence) is "
            f"printed and not compared: sbaddress1=0x{addr1:08X} observed",
        )

        read_a = await self._sba_read("sba_read_a", SBACCESS_32, WORD_A)
        sbcs_a = self._last_sbcs
        read_b = await self._sba_read("sba_read_b", SBACCESS_32, WORD_B)
        sbcs_b = self._last_sbcs
        self._step_done("S4")
        assert read_a == PATTERN_A, (
            f"read @0x{WORD_A:08X} got 0x{read_a:08X} want 0x{PATTERN_A:08X}"
        )
        assert read_b == PATTERN_B, (
            f"read @0x{WORD_B:08X} got 0x{read_b:08X} want 0x{PATTERN_B:08X}"
        )
        self._chk(
            "S4",
            f"read @0x{WORD_A:08X}=0x{read_a:08X} (sbcs=0x{sbcs_a:08X}) and "
            f"@0x{WORD_B:08X}=0x{read_b:08X} (sbcs=0x{sbcs_b:08X}), sbbusy=0 sberror=0",
        )

        width_text = []
        for access, width, base, lane, background, pattern in WIDTH_CASES:
            addr = base + lane
            await self._sba_write(
                f"bg_{width}", SBACCESS_64, base, background & ALL_ONES, background >> 32
            )
            await self._sba_write(f"w{8 * width}", access, addr, pattern & ALL_ONES, pattern >> 32)
            narrow = await self._sba_read(f"r{8 * width}", access, addr, wide=width == 8)
            whole = await self._sba_read(f"rd_{width}", SBACCESS_64, base, wide=True)
            field = _mask(width) << (8 * lane)
            want = (background & ~field) | ((pattern & _mask(width)) << (8 * lane))
            assert narrow & _mask(width) == pattern, (
                f"{8 * width}-bit read @0x{addr:08X} got 0x{narrow:X} want 0x{pattern:X}"
            )
            assert whole == want, (
                f"{8 * width}-bit write @0x{addr:08X}: dword 0x{whole:016X} want 0x{want:016X} "
                f"(background 0x{background:016X})"
            )
            width_text.append(
                f"{8 * width}-bit 0x{pattern:X}@0x{addr:08X} read 0x{narrow & _mask(width):X}, "
                f"dword 0x{background:016X} -> 0x{whole:016X}"
            )
        self._step_done("S5")
        self._chk("S5", "; ".join(width_text) + "; sberror 0 after each")

        await self._sba_write("w64_pair", SBACCESS_64, WORD_64, PATTERN_64_LO, PATTERN_64_HI)
        pair = await self._sba_read("r64_pair", SBACCESS_64, WORD_64, wide=True)
        self.observed_word = pair
        self._step_done("S6")
        assert PATTERN_64_LO != PATTERN_64_HI
        assert pair & ALL_ONES == PATTERN_64_LO, (
            f"sbdata0 read 0x{pair & ALL_ONES:08X} want 0x{PATTERN_64_LO:08X}"
        )
        assert pair >> 32 == PATTERN_64_HI, (
            f"sbdata1 read 0x{pair >> 32:08X} want 0x{PATTERN_64_HI:08X}"
        )
        self._chk(
            "S6",
            f"64-bit write sbdata1=0x{PATTERN_64_HI:08X} sbdata0=0x{PATTERN_64_LO:08X}@"
            f"0x{WORD_64:08X} read back sbdata0=0x{pair & ALL_ONES:08X} "
            f"sbdata1=0x{pair >> 32:08X}",
        )

        axi_a = await self._axi_read("AXI_RD_A", WORD_A, 4)
        axi_b = await self._axi_read("AXI_RD_B", WORD_B, 4)
        axi_32 = await self._axi_read("AXI_RD_W32", WIDTH_CASES[2][2] + WIDTH_CASES[2][3], 4)
        axi_64 = await self._axi_read("AXI_RD_64", WORD_64, 8)
        await ClockCycles(clk, IDLE_CYCLES)
        await self.csr_write("AXI_WR_NEW", WORD_AXI, PATTERN_AXI, length=4)
        await ClockCycles(clk, IDLE_CYCLES)
        sba_new = await self._sba_read("sba_read_axi", SBACCESS_32, WORD_AXI)
        await ClockCycles(clk, 2)
        self._step_done("S7")
        want_32 = WIDTH_CASES[2][5]
        assert axi_a == PATTERN_A, f"AXI read @0x{WORD_A:08X} got 0x{axi_a:08X}"
        assert axi_b == PATTERN_B, f"AXI read @0x{WORD_B:08X} got 0x{axi_b:08X}"
        assert axi_32 == want_32, f"AXI read of the 32-bit width word got 0x{axi_32:08X}"
        assert axi_64 == self.expected_word, f"AXI 64-bit read got 0x{axi_64:016X}"
        assert sba_new == PATTERN_AXI, (
            f"system bus read @0x{WORD_AXI:08X} got 0x{sba_new:08X} want 0x{PATTERN_AXI:08X}"
        )
        self._chk(
            "S7",
            f"AXI reads 0x{axi_a:08X}@0x{WORD_A:08X}, 0x{axi_b:08X}@0x{WORD_B:08X}, "
            f"0x{axi_32:08X}@0x{WIDTH_CASES[2][2] + WIDTH_CASES[2][3]:08X}, "
            f"0x{axi_64:016X}@0x{WORD_64:08X} equal the system bus writes; AXI write "
            f"0x{PATTERN_AXI:08X}@0x{WORD_AXI:08X} read by system bus 0x{sba_new:08X}",
        )

        self._assert_fence()
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: 3 bounded waits: dmi_busy_retry=%d enforced-by=%s "
            "fail-on-expiry=SmcJtagTapError last=DMI response 0x%08X; "
            "dm_active_poll=16 enforced-by=%s fail-on-expiry=AssertionError "
            "last=dmcontrol.dmactive=1; sbbusy_wait=%d fail-on-expiry=AssertionError "
            "last=sbcs 0x%08X (max sbcs reads used %d)",
            VIP_DMI_BUSY_RETRIES,
            VIP_FILE,
            self._last_dmi,
            VIP_FILE,
            SBBUSY_BOUND,
            self._last_sbcs,
            max(self._polls),
        )
        self.dm_ok = True
