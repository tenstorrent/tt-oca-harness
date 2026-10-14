# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CPU Debug Module sbcs capability and haltsum idle readbacks over the DMI.

Spec sources: hw/sys/smc/doc/cpu.adoc (Debug Module capability readbacks and DMI register
inventory tables), hw/ip/jtag/jtag_stap/doc.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time

from .smc_cpu_vip_utils import (
    CPU_CTRL_RESET_CTRL,
    CPU_RESET_CTRL_DEBUG_RELEASE,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_jtag_protocol_vip import SmcJtagTap

DMI_HALTSUM1 = 0x13
DMI_SBCS = 0x38
DMI_HALTSUM0 = 0x40

SBCS_VERSION_SHIFT = 29
SBCS_VERSION_MASK = 0x7
SBCS_ASIZE_SHIFT = 5
SBCS_ASIZE_MASK = 0x7F
SBCS_ACCESS_SHIFT = 0
SBCS_ACCESS_MASK = 0x1F
SBCS_CAP_MASK = (
    (SBCS_VERSION_MASK << SBCS_VERSION_SHIFT)
    | (SBCS_ASIZE_MASK << SBCS_ASIZE_SHIFT)
    | (SBCS_ACCESS_MASK << SBCS_ACCESS_SHIFT)
)

EXPECTED_SBVERSION = 1
EXPECTED_SBASIZE = 56
# sbaccess bits 0..4 = 8, 16, 32, 64, 128.
EXPECTED_SBACCESS = 0b01111

ALL_ONES = 0xFFFF_FFFF

STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")
CHK_BY_STEP = {
    "S2": "CHK-SBCS-VERSION",
    "S3": "CHK-SBCS-ASIZE",
    "S4": "CHK-SBCS-ACCESS-CAPS",
    "S5": "CHK-SBCS-CAPS-WRITE-ALL-ONES",
    "S6": "CHK-HALTSUM0-IDLE",
    "S7": "CHK-HALTSUM1-IDLE",
    "S8": "CHK-HALTSUM-WRITE-IGNORED",
}
FENCE_TERMS = (
    "RELEASED_AND_ACTIVE",
    "SBVERSION",
    "SBASIZE",
    "SBACCESS_CAPS",
    "SBCS_WRITE_IMMUNE",
    "HALTSUM_IDLE",
    "HALTSUM_WRITE_IGNORED",
)
VIP_FILE = "seq_lib/smc_jtag_protocol_vip.py"
VIP_DMI_BUSY_RETRIES = 4


class smc_jtag_dm_sbcs_haltsum_test_seq(SmcCsrSeq):
    """Read sbcs capabilities and haltsum idle values, then write all ones to each."""

    def __init__(self, name: str = "smc_jtag_dm_sbcs_haltsum_test_seq") -> None:
        super().__init__(name)
        self.dm_ok: bool = False
        self._tap: SmcJtagTap | None = None
        self._abits: int = 7
        self._idle: int = 5
        self._events: list[tuple[str, str, int]] = []
        self._last_read: dict[str, int] = {}

    async def _dmi_read(self, addr: int) -> int:
        assert self._tap is not None
        value = await self._tap.dmi_read(addr, abits=self._abits, idle=self._idle)
        self._last_read[f"0x{addr:02X}"] = value
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
        order = {s: i for i, s in enumerate(STEPS)}
        chks = [e for e in self._events if e[0] == "chk"]
        expected = [CHK_BY_STEP[s] for s in STEPS if s in CHK_BY_STEP]
        assert [c[1] for c in chks] == expected, f"checker order {[c[1] for c in chks]}"
        for (_, cid, t), step in zip(chks, [s for s in STEPS if s in CHK_BY_STEP]):
            assert t >= stamps[order[step]], f"{cid} printed at {t} before {step}"
            idx_chk = self._events.index(("chk", cid, t))
            idx_step = self._events.index(("step", step, stamps[order[step]]))
            assert idx_chk > idx_step, f"{cid} printed before {step} completed"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(FENCE_TERMS),
            ", ".join(c[1] for c in chks),
            ",".join(str(s) for s in stamps),
        )

    async def body(self) -> None:
        await self.csr_write(
            "CPU_CTRL_DEBUG_RESET_RELEASE",
            CPU_CTRL_RESET_CTRL,
            CPU_RESET_CTRL_DEBUG_RELEASE,
            length=8,
        )
        await ClockCycles(cocotb.top.clk_smc_i, 64)
        reset_ctrl = await self.csr_read("CPU_CTRL_RESET_CTRL_RB", CPU_CTRL_RESET_CTRL, length=8)
        assert reset_ctrl & (1 << 24), f"debug_reset_n not set in RESET_CTRL (got 0x{reset_ctrl:X})"

        self._tap = SmcJtagTap(name="smc_jtag_dm_sbcs")
        self._tap.init_signals()
        await self._tap.reset_tap()
        await self._tap.read_idcode(check=True)
        await self._tap.read_dmstatus()
        dtmcs = await self._tap.read_dtmcs()
        self._abits = ((dtmcs >> 4) & 0x3F) or 7
        self._idle = max((dtmcs >> 12) & 0x7, 5)
        self._step_done("S1")

        sbcs0 = await self._dmi_read(DMI_SBCS)
        sbversion = (sbcs0 >> SBCS_VERSION_SHIFT) & SBCS_VERSION_MASK
        self._step_done("S2")
        assert sbversion == EXPECTED_SBVERSION, f"sbcs.sbversion={sbversion} sbcs=0x{sbcs0:08X}"
        self._chk("S2", f"sbcs.sbversion={sbversion} (sbcs=0x{sbcs0:08X})")

        sbcs0 = await self._dmi_read(DMI_SBCS)
        sbasize = (sbcs0 >> SBCS_ASIZE_SHIFT) & SBCS_ASIZE_MASK
        self._step_done("S3")
        assert sbasize == EXPECTED_SBASIZE, f"sbcs.sbasize={sbasize} sbcs=0x{sbcs0:08X}"
        self._chk("S3", f"sbcs.sbasize={sbasize} (sbcs=0x{sbcs0:08X})")

        sbcs0 = await self._dmi_read(DMI_SBCS)
        access = (sbcs0 >> SBCS_ACCESS_SHIFT) & SBCS_ACCESS_MASK
        self._step_done("S4")
        assert access == EXPECTED_SBACCESS, (
            f"sbaccess[128,64,32,16,8]={access:05b} expected {EXPECTED_SBACCESS:05b} "
            f"sbcs=0x{sbcs0:08X}"
        )
        self._chk(
            "S4",
            f"sbaccess8={access & 1} sbaccess16={(access >> 1) & 1} sbaccess32={(access >> 2) & 1} "
            f"sbaccess64={(access >> 3) & 1} sbaccess128={(access >> 4) & 1} (sbcs=0x{sbcs0:08X})",
        )

        await self._dmi_write(DMI_SBCS, ALL_ONES)
        sbcs1 = await self._dmi_read(DMI_SBCS)
        await self._dmi_write(DMI_SBCS, 0)
        sbcs2 = await self._dmi_read(DMI_SBCS)
        self._step_done("S5")
        assert (sbcs1 & SBCS_CAP_MASK) == (sbcs0 & SBCS_CAP_MASK), (
            f"capability fields changed: before 0x{sbcs0 & SBCS_CAP_MASK:08X} "
            f"after all-ones 0x{sbcs1 & SBCS_CAP_MASK:08X} (sbcs 0x{sbcs0:08X} -> 0x{sbcs1:08X})"
        )
        self._chk(
            "S5",
            f"sbversion={(sbcs1 >> SBCS_VERSION_SHIFT) & SBCS_VERSION_MASK} "
            f"sbasize={(sbcs1 >> SBCS_ASIZE_SHIFT) & SBCS_ASIZE_MASK} "
            f"sbaccess={sbcs1 & SBCS_ACCESS_MASK:05b} unchanged; sbcs before=0x{sbcs0:08X} "
            f"after_all_ones=0x{sbcs1:08X} after_restore=0x{sbcs2:08X}",
        )

        haltsum0 = await self._dmi_read(DMI_HALTSUM0)
        self._step_done("S6")
        assert haltsum0 == 0, f"haltsum0=0x{haltsum0:08X} with no hart halted"
        self._chk("S6", f"haltsum0=0x{haltsum0:08X} (bits 31:4 and 3:0 both 0)")

        haltsum1 = await self._dmi_read(DMI_HALTSUM1)
        self._step_done("S7")
        assert haltsum1 == 0, f"haltsum1=0x{haltsum1:08X} with no hart halted"
        self._chk("S7", f"haltsum1=0x{haltsum1:08X} (bits 31:1 and 0 both 0)")

        await self._dmi_write(DMI_HALTSUM0, ALL_ONES)
        await self._dmi_write(DMI_HALTSUM1, ALL_ONES)
        haltsum0_w = await self._dmi_read(DMI_HALTSUM0)
        haltsum1_w = await self._dmi_read(DMI_HALTSUM1)
        self._step_done("S8")
        assert haltsum0_w == 0 and haltsum1_w == 0, (
            f"haltsum0=0x{haltsum0_w:08X} haltsum1=0x{haltsum1_w:08X} after all-ones writes"
        )
        self._chk(
            "S8", f"haltsum0=0x{haltsum0_w:08X} haltsum1=0x{haltsum1_w:08X} after all-ones writes"
        )

        self._assert_fence()
        last = ",".join(f"{k}=0x{v:08X}" for k, v in self._last_read.items())
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: 2 bounded waits: dmi_busy_retry=%d enforced-by=%s "
            "fail-on-expiry=SmcJtagTapError last=%s; "
            "dm_active_poll=16 enforced-by=%s fail-on-expiry=AssertionError "
            "last=dmcontrol.dmactive=1",
            VIP_DMI_BUSY_RETRIES,
            VIP_FILE,
            last,
            VIP_FILE,
        )
        self.dm_ok = True
