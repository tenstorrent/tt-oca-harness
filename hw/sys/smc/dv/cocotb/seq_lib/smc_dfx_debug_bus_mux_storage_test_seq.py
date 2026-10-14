# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DEBUG_BUS_MUX write and readback.

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
DEBUG_BUS_MUX = smc_addr("SMC_TOP_DFX_CTRL_DEBUG_BUS_MUX_BASE_ADDR")
WIDTH = 64
FULL_MASK = (1 << WIDTH) - 1


def _field(name: str) -> tuple[int, int, int]:
    prefix = f"DFX_CTRL_STATUS__DEBUG_BUS_MUX__{name}"
    mask = dfx_status_u32(f"{prefix}_bm")
    lsb = dfx_status_u32(f"{prefix}_bp")
    return mask, lsb, mask >> lsb


MODE = _field("DBMMODE")
ID = _field("DBMID")
RSVD = _field("RSVD158")
SEGS = [_field(f"MUXSELSEG{i}") for i in range(8)]
ASSIGNED_IDS = (3, 6, 7, 14)
UNASSIGNED_IDS = (0, 63)
SEL_PATTERNS = (0, 1, 2, 3, 4, 5, 42, 63)
STEP_ORDER = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")
FENCE_TERMS = {
    "S1": "BRINGUP_SENSE_DONE",
    "S2": "MODE_EXACT",
    "S3": "ID_EXACT",
    "S4": "SEL03_EXACT",
    "S5": "SEL47_EXACT",
    "S6": "WALK1_EXACT",
    "S7": "ONEATATIME_EXACT",
    "S8": "B2B_EXACT_RESTORED",
}
CHK_ORDER = (
    ("CHK-DFX-MUX-MODE", "S2"),
    ("CHK-DFX-MUX-ID", "S3"),
    ("CHK-DFX-MUX-SEL03", "S4"),
    ("CHK-DFX-MUX-SEL47", "S5"),
    ("CHK-DFX-MUX-WALK1", "S6"),
    ("CHK-DFX-MUX-ONEATATIME", "S7"),
    ("CHK-DFX-MUX-B2B", "S8"),
    ("CHK-TIMEOUT-PATHS", "S8"),
)


def _put(field: tuple[int, int, int], value: int) -> int:
    return value << field[1]


class smc_dfx_debug_bus_mux_storage_test_seq(SmcCsrSeq):
    """Write DEBUG_BUS_MUX over SEP_IN as 8-byte accesses and compare every readback."""

    def __init__(self, name: str = "smc_dfx_debug_bus_mux_storage_test_seq") -> None:
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

    async def _read(self, name: str) -> int:
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = DEBUG_BUS_MUX
        item.length = 8
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self._last_access = f"{name}@0x{DEBUG_BUS_MUX:08x} resp={item.resp_code} rdata={item.rdata}"
        assert item.resp_code == OKAY, f"read not OKAY: {self._last_access}"
        assert isinstance(item.rdata, int), f"read data not resolvable: {self._last_access}"
        return item.rdata & FULL_MASK

    async def _write(self, name: str, data: int) -> None:
        await self.csr_write(name, DEBUG_BUS_MUX, data, length=8)
        self._last_access = f"{name}@0x{DEBUG_BUS_MUX:08x} wdata=0x{data:016x} written"

    async def _write_expect(self, name: str, data: int) -> int:
        """Write `data`, read back and compare all 64 bits; return the readback."""
        await self._write(name, data)
        got = await self._read(f"{name}_RB")
        assert got == data, f"{name}: wrote 0x{data:016x}, read 0x{got:016x} ({self._last_access})"
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
        modes = []
        for mode in range(4):
            await self._write_expect(f"MODE_{mode}", _put(MODE, mode))
            modes.append(mode)
        self._stamp("S2")
        self._chk(
            "CHK-DFX-MUX-MODE",
            f"Dbmmode {modes} each read back the full 64-bit register exactly with every other "
            "field 0",
        )

        # S3
        assigned = []
        for ident in ASSIGNED_IDS:
            await self._write_expect(f"ID_{ident}", _put(ID, ident))
            assigned.append(ident)
        for ident in UNASSIGNED_IDS:
            await self._write_expect(f"ID_{ident}", _put(ID, ident))
        self._stamp("S3")
        self._chk(
            "CHK-DFX-MUX-ID",
            f"Dbmid {assigned} and unassigned values {list(UNASSIGNED_IDS)} read back exactly",
        )

        # S4
        cells = 0
        for idx in range(4):
            for pattern in SEL_PATTERNS:
                await self._write_expect(f"SEG{idx}_{pattern}", _put(SEGS[idx], pattern))
                cells += 1
        self._stamp("S4")
        self._chk(
            "CHK-DFX-MUX-SEL03",
            f"Muxselseg0..3 each read back the patterns {list(SEL_PATTERNS)} exactly with every "
            f"other field 0 ({cells} cells)",
        )

        # S5
        seg47 = []
        for idx in range(4, 8):
            await self._write_expect(f"SEG{idx}_63", _put(SEGS[idx], 63))
            seg47.append(idx)
        await self._write_expect("RSVD158_63", _put(RSVD, 63))
        self._stamp("S5")
        self._chk(
            "CHK-DFX-MUX-SEL47",
            f"Muxselseg{seg47} each read back 63 with no other field changing; Rsvd158 wrote "
            "0x3f and read back exactly",
        )

        # S6
        for bit in range(WIDTH):
            await self._write_expect(f"WALK1_BIT{bit}", 1 << bit)
        self._stamp("S6")
        self._chk(
            "CHK-DFX-MUX-WALK1",
            f"a one at each of the {WIDTH} bit positions, Rsvd158 included, read back as exactly "
            "that bit",
        )

        # S7
        walked = []
        for ident in range(3, 15):
            value = _put(MODE, 1) | _put(ID, ident)
            for idx in range(4):
                value |= _put(SEGS[idx], (ident * 5 + idx * 11 + 1) & 63)
            await self._write_expect(f"MUX_{ident}", value)
            walked.append(f"{ident}=0x{value:016x}")
        self._stamp("S7")
        self._chk(
            "CHK-DFX-MUX-ONEATATIME",
            f"Dbmid 3..14 each read back exactly with its own Muxselseg0..3 patterns: "
            f"{','.join(walked)}",
        )

        # S8
        pat_a = _put(MODE, 1) | _put(ID, 5) | _put(SEGS[0], 42) | _put(SEGS[3], 21)
        pat_b = _put(MODE, 2) | _put(ID, 9) | _put(SEGS[1], 21) | _put(SEGS[2], 42)
        await self._write("B2B_A_FIRST", pat_a)
        await self._write("B2B_B_SECOND", pat_b)
        second = await self._read("B2B_B_RB")
        assert second == pat_b, f"A then B read 0x{second:016x}, expected 0x{pat_b:016x}"
        await self._write("B2B_B_FIRST", pat_b)
        await self._write("B2B_A_SECOND", pat_a)
        first = await self._read("B2B_A_RB")
        assert first == pat_a, f"B then A read 0x{first:016x}, expected 0x{pat_a:016x}"
        await self._write_expect("RESTORE_ZERO", 0)
        self._waits.append(("sep_in_access", f"{axi_bound}ns", self._last_access))
        self._stamp("S8")
        self._chk(
            "CHK-DFX-MUX-B2B",
            f"A=0x{pat_a:016x} then B=0x{pat_b:016x} read 0x{second:016x}; B then A read "
            f"0x{first:016x}; restored to 0x0 and read back 0x0",
        )

        self.assert_all_reachable(self.accesses, "DEBUG_BUS_MUX")
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
