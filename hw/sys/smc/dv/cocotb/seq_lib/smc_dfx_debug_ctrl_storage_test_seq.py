# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DEBUG_CTRL field write and readback.

Sources: hw/sys/smc/regs/blocks/dfx_ctrl_status/dfx_ctrl_status.rdl, hw/sys/smc/doc/memmap.adoc.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import dfx_status_u32, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

OKAY = 0
FUSE_SENSE_MAX_CYCLES = 200_000
DEBUG_CTRL = smc_addr("SMC_TOP_DFX_CTRL_DEBUG_CTRL_BASE_ADDR")
WORD_MASK = 0xFFFF_FFFF
LOW_BITS = 31
LOW_MASK = (1 << LOW_BITS) - 1
BIT31 = 1 << 31
UPPER_HALF = 0xFFFF_FFFF_0000_0000


def _field(name: str) -> tuple[int, int, int]:
    prefix = f"DFX_CTRL_STATUS__DEBUG_CTRL__{name}"
    mask = dfx_status_u32(f"{prefix}_bm")
    lsb = dfx_status_u32(f"{prefix}_bp")
    return mask, lsb, mask >> lsb


FIELDS = {
    name: _field(name)
    for name in (
        "CHIPLET_ENABLE",
        "GPIO_EN",
        "CG_EN",
        "FORCE_CLK_EN",
        "DTB_NS_EN",
        "DTB_EW_EN",
        "XTRIG_CLK_HALT_MASK",
        "DEBUG_MARKER",
    )
}
STORAGE_FIELDS = ("CHIPLET_ENABLE", "GPIO_EN", "DTB_NS_EN", "DTB_EW_EN", "DEBUG_MARKER")
STEP_ORDER = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")
FENCE_TERMS = {
    "S1": "BRINGUP_SENSE_DONE",
    "S2": "FIELDS_EXACT",
    "S3": "CLK_BITS_EXACT",
    "S4": "XTRIG_EXACT",
    "S5": "WALK1_EXACT",
    "S6": "BIT31_PRINTED",
    "S7": "B2B_EXACT",
    "S8": "RESTORED_0",
}
CHK_ORDER = (
    ("CHK-DFX-CTRL-FIELDS", "S2"),
    ("CHK-DFX-CTRL-CLK-BITS", "S3"),
    ("CHK-DFX-CTRL-XTRIG", "S4"),
    ("CHK-DFX-CTRL-WALK1", "S5"),
    ("CHK-DFX-CTRL-BIT31", "S6"),
    ("CHK-DFX-CTRL-B2B", "S7"),
    ("CHK-TIMEOUT-PATHS", "S8"),
)


def _patterns(width: int) -> tuple[int, ...]:
    """All-ones then an alternating pattern (and its complement when the field has 2+ bits)."""
    ones = (1 << width) - 1
    if width == 1:
        return (ones, 0)
    alt = int("10" * ((width + 1) // 2), 2) & ones
    return (ones, alt, ones ^ alt)


class smc_dfx_debug_ctrl_storage_test_seq(SmcCsrSeq):
    """Write DEBUG_CTRL over SEP_IN and compare every readback exactly."""

    def __init__(self, name: str = "smc_dfx_debug_ctrl_storage_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: set[str] = set()
        self._stamps: list[tuple[str, int]] = []
        self._chk_order: list[tuple[str, int]] = []
        self._waits: list[tuple[str, str, str]] = []
        self._last_access = "none"

    def _stamp(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_order.append((chk_id, len(self._stamps)))
        self.chk_seen.add(chk_id)

    async def _read(self, name: str, length: int = 4) -> int:
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = DEBUG_CTRL
        item.length = length
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self._last_access = f"{name}@0x{DEBUG_CTRL:08x} resp={item.resp_code} rdata={item.rdata}"
        assert item.resp_code == OKAY, f"read not OKAY: {self._last_access}"
        assert isinstance(item.rdata, int), f"read data not resolvable: {self._last_access}"
        return item.rdata & ((1 << (8 * length)) - 1)

    async def _write(self, name: str, data: int, length: int = 4) -> None:
        await self.csr_write(name, DEBUG_CTRL, data, length=length)
        self._last_access = f"{name}@0x{DEBUG_CTRL:08x} wdata=0x{data:x} written"

    async def _write_expect(self, name: str, data: int) -> int:
        await self._write(name, data)
        got = await self._read(f"{name}_RB")
        assert got == data, f"{name}: wrote 0x{data:08x}, read 0x{got:08x} ({self._last_access})"
        return got

    async def body(self) -> None:
        dut = cocotb.top
        axi_bound = self.cfg.axi_timeout_ns

        # S1
        await self.wait_fuse_sense_done(FUSE_SENSE_MAX_CYCLES)
        sense = int(dut.tb_fuse_sense_done.value)
        assert sense == 1, "tb_fuse_sense_done low after the wait returned"
        self._waits.append(
            (
                "fuse_sense_done",
                f"{FUSE_SENSE_MAX_CYCLES}cyc(enforced-by=seq_lib/smc_base_test_seq.py)",
                f"tb_fuse_sense_done={sense}",
            )
        )
        self._stamp("S1")

        # S2
        cells = []
        for fname in STORAGE_FIELDS:
            _mask, lsb, fmax = FIELDS[fname]
            for pattern in _patterns(fmax.bit_length()):
                value = pattern << lsb
                await self._write_expect(f"{fname}_0x{pattern:x}", value)
                cells.append(f"{fname}=0x{pattern:x}")
        self._stamp("S2")
        self._chk(
            "CHK-DFX-CTRL-FIELDS",
            f"{len(cells)} cells read back the full register exactly with every other field 0: "
            f"{','.join(cells)}",
        )

        # S3
        clk = []
        cg_mask = FIELDS["CG_EN"][0]
        force_mask = FIELDS["FORCE_CLK_EN"][0]
        for label, value in (
            ("CG_EN", cg_mask),
            ("FORCE_CLK_EN", force_mask),
            ("BOTH", cg_mask | force_mask),
        ):
            await self._write_expect(f"CLK_{label}", value)
            await self._write_expect(f"CLK_{label}_RESTORE", 0)
            clk.append(f"{label}=0x{value:x}")
        self._stamp("S3")
        self._chk(
            "CHK-DFX-CTRL-CLK-BITS",
            f"cg_en, force_clk_en and both read back exactly ({','.join(clk)}) and each was "
            "restored to 0x0 and read back as 0x0 at once; the DFD clock effect is not checked",
        )

        # S4
        xmask, xlsb, xmax = FIELDS["XTRIG_CLK_HALT_MASK"]
        xwidth = xmax.bit_length()
        await self._write_expect("XTRIG_ONES", xmask)
        for bit in range(xwidth):
            await self._write_expect(f"XTRIG_BIT{bit}", (1 << bit) << xlsb)
        self._stamp("S4")
        self._chk(
            "CHK-DFX-CTRL-XTRIG",
            f"xtrig_clk_halt_mask[{xlsb + xwidth - 1}:{xlsb}] read back all-ones 0x{xmask:x} and "
            f"each of the {xwidth} walking-one positions {xlsb}..{xlsb + xwidth - 1} exactly",
        )

        # S5
        for bit in range(LOW_BITS):
            await self._write_expect(f"WALK1_BIT{bit}", 1 << bit)
        self._stamp("S5")
        self._chk(
            "CHK-DFX-CTRL-WALK1",
            f"a walking one at each of bits 0..{LOW_BITS - 1} read back as exactly that single bit "
            f"({LOW_BITS} cells)",
        )

        # S6
        await self._write("BIT31_4B", BIT31)
        word_4b = await self._read("BIT31_4B_RB")
        await self._write("BIT31_8B", UPPER_HALF, length=8)
        slot_8b = await self._read("BIT31_8B_RB", length=8)
        self._stamp("S6")
        self._chk(
            "CHK-DFX-CTRL-BIT31",
            f"4-byte write 0x{BIT31:08x} read back 0x{word_4b:08x}; "
            f"8-byte write 0x{UPPER_HALF:016x} read back slot 0x{slot_8b:016x}; "
            "both resolvable, expected values are not stated in the document and are not asserted",
        )

        # S7
        await self._write("B2B_ONES_ZERO_ONES", LOW_MASK)
        await self._write("B2B_ONES_ZERO_ZERO", 0)
        first = await self._read("B2B_ONES_THEN_ZERO_RB")
        assert first == 0, f"ones then 0 read 0x{first:08x}, expected 0 ({self._last_access})"
        await self._write("B2B_ZERO_THEN_ONES_0", 0)
        await self._write("B2B_ZERO_THEN_ONES_1", LOW_MASK)
        second = await self._read("B2B_ZERO_THEN_ONES_RB")
        assert second == LOW_MASK, (
            f"0 then ones read 0x{second:08x}, expected 0x{LOW_MASK:08x} ({self._last_access})"
        )
        self._stamp("S7")
        self._chk(
            "CHK-DFX-CTRL-B2B",
            f"all-ones(0x{LOW_MASK:08x}) then 0 with no read between read 0x{first:08x}; "
            f"0 then all-ones read 0x{second:08x}",
        )

        # S8
        await self._write_expect("RESTORE_ZERO", 0)
        self._waits.append(("sep_in_access", f"{axi_bound}ns", self._last_access))
        self._stamp("S8")

        self.assert_all_reachable(self.accesses, "DEBUG_CTRL")
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s",
            len(self._waits),
            " ".join(f"{n}={b} last={s}" for n, b, s in self._waits),
        )
        self._chk_order.append(("CHK-TIMEOUT-PATHS", len(self._stamps)))
        self.chk_seen.add("CHK-TIMEOUT-PATHS")
        self._fence()

    def _fence(self) -> None:
        steps = [s for s, _ in self._stamps]
        assert tuple(steps) == STEP_ORDER, f"step order {steps}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        order = [c for c, _ in self._chk_order]
        assert order == [c for c, _ in CHK_ORDER], f"checker order {order}"
        for chk_id, n_stamps in self._chk_order:
            step = dict(CHK_ORDER)[chk_id]
            assert n_stamps == STEP_ORDER.index(step) + 1, f"{chk_id} printed before {step}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(FENCE_TERMS[s] for s in steps),
            ",".join(order),
            ",".join(f"{s}={t}ps" for s, t in self._stamps),
        )
        self.chk_seen.add("CHK-NONVAC")
