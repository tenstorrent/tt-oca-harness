# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CLOCK_GATE_CONTROL register access over SEP_IN.

Sources: hw/sys/smc/regs/blocks/smc_base_config/smc_base_config.rdl, hw/sys/smc/doc/clk_rst.adoc.

The register returns to its reset value at the end of every step, so no peripheral window is
accessed while an enable is set.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from . import smc_addr_map as _addr
from .smc_cg_obs_utils import (
    CG_HYST_MASK,
    CG_HYST_SHIFT,
    CLOCK_GATE_CONTROL,
    DMA_CG_EN,
)
from .smc_csr_seq_utils import SmcCsrSeq

_CGC = "SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__"
ENABLES_BM = 0
for _symbol, _mask in _addr._parse_simple_defines(_addr._SMC_BASE_CFG_H).items():
    if _symbol.startswith(_CGC) and _symbol.endswith("_CG_EN_bm"):
        ENABLES_BM |= _mask
ENABLE_COUNT = ENABLES_BM.bit_length()
assert ENABLES_BM == (1 << ENABLE_COUNT) - 1, f"enable masks 0x{ENABLES_BM:x} are not contiguous"
HYST_RESET = (_addr.CLOCK_GATE_CONTROL_RESET & CG_HYST_MASK) >> CG_HYST_SHIFT
BASE = HYST_RESET << CG_HYST_SHIFT
DEFINED_BM = ENABLES_BM | CG_HYST_MASK
_RESERVED_BM = ((1 << 64) - 1) & ~DEFINED_BM
RESERVED_LO_BM = _RESERVED_BM & ((1 << CG_HYST_SHIFT) - 1)
RESERVED_HI_BM = _RESERVED_BM & ~((1 << CG_HYST_SHIFT) - 1)
HYST_VALUES = (0x00, 0x01, 0x1F, 0x20, 0x3F)
OKAY = 0
ACCESS_TIMEOUT_NS = 50_000

STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")
FENCE_TERMS = (
    "SETUP",
    "RESET_READ",
    "WALKING_ONE",
    "WALKING_ZERO",
    "HYST_RANGE",
    "RESERVED_WRITTEN",
    "NARROW_WRITTEN",
    "REWRITE",
)
CHECKER_STEPS = (
    ("CHK-CGC-RESET-VALUE", "S2"),
    ("CHK-CGC-WALKING-ONE", "S3"),
    ("CHK-CGC-WALKING-ZERO", "S4"),
    ("CHK-CGC-HYST-RANGE", "S5"),
    ("CHK-CGC-RESERVED-BITS", "S6"),
    ("CHK-CGC-NARROW-ACCESS", "S7"),
    ("CHK-CGC-REWRITE", "S8"),
)


class smc_cg_ctrl_reg_access_test_seq(SmcCsrSeq):
    """CLOCK_GATE_CONTROL reset, walking patterns, hysteresis, reserved, narrow, rewrite."""

    def __init__(self, name: str = "smc_cg_ctrl_reg_access_test_seq") -> None:
        super().__init__(name)
        self.stamps: dict[str, int] = {}
        self.chk_stamps: dict[str, int] = {}
        self.chk_order: list[str] = []
        self.chk_seen: dict[str, str] = {}

    async def _access(
        self,
        label: str,
        op: SmcSysAxiOp,
        addr: int,
        data: int = 0,
        length: int = 8,
        wstrb: int | None = None,
        tolerate_error: bool = False,
    ) -> tuple[int, int]:
        item = SmcSysAxiItem(f"{'rd' if op == SmcSysAxiOp.READ else 'wr'}_{label}")
        item.op = op
        item.addr = addr
        item.length = length
        item.timeout_ns = ACCESS_TIMEOUT_NS
        item.allow_error = tolerate_error
        if op == SmcSysAxiOp.WRITE:
            item.wdata = data
            item.wstrb = wstrb
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None, f"{label}: no response code"
        if not tolerate_error:
            assert item.resp_code == OKAY, (
                f"{label} @ 0x{addr:08x}: response code {item.resp_code}, expected OKAY"
            )
        return item.rdata, item.resp_code

    async def _rd(self, label: str) -> int:
        got, _ = await self._access(label, SmcSysAxiOp.READ, CLOCK_GATE_CONTROL)
        return got

    async def _wr(self, label: str, data: int, tolerate_error: bool = False) -> int:
        _, resp = await self._access(
            label, SmcSysAxiOp.WRITE, CLOCK_GATE_CONTROL, data, tolerate_error=tolerate_error
        )
        return resp

    async def _wr_rd(self, label: str, data: int, expect: int | None = None) -> int:
        await self._wr(label, data)
        got = await self._rd(f"{label}_RB")
        want = data if expect is None else expect
        assert got & DEFINED_BM == want & DEFINED_BM, (
            f"{label}: wrote 0x{data:016x}, read 0x{got:016x}, defined fields expected "
            f"0x{want & DEFINED_BM:016x}"
        )
        return got

    async def _restore(self, label: str) -> None:
        await self._wr_rd(f"{label}_RESTORE", BASE)

    def _stamp(self, step: str) -> None:
        now = int(get_sim_time("ps"))
        self.stamps[step] = now
        cocotb.log.info("STEP %s: complete at %d ps", step, now)

    def _chk(self, chk_id: str, text: str) -> None:
        self.chk_order.append(chk_id)
        self.chk_stamps[chk_id] = int(get_sim_time("ps"))
        self.chk_seen[chk_id] = text
        cocotb.log.info("%s: %s", chk_id, text)

    def _assert_fence(self) -> tuple[list[int], str]:
        assert list(self.stamps) == list(STEPS), f"step order {list(self.stamps)} != {STEPS}"
        times = [self.stamps[s] for s in STEPS]
        for prev, cur, step in zip(times, times[1:], STEPS[1:]):
            assert cur > prev, f"step {step} stamp {cur} ps is not after {prev} ps"
        expected = [c for c, _ in CHECKER_STEPS]
        assert self.chk_order == expected, f"checker lines {self.chk_order} != {expected}"
        for chk_id, step in CHECKER_STEPS:
            assert self.chk_stamps[chk_id] >= self.stamps[step], (
                f"{chk_id} printed at {self.chk_stamps[chk_id]} ps before {step} "
                f"completed at {self.stamps[step]} ps"
            )
        return times, ", ".join(f"{s}@{t}" for s, t in zip(STEPS, times))

    async def body(self) -> None:
        assert DMA_CG_EN == 1, f"DMA_CG_EN mask 0x{DMA_CG_EN:x} is not bit 0"
        assert _addr.TELEMETRY_CG_EN == 1 << (ENABLE_COUNT - 1), "fourteenth enable is not bit 13"
        assert CG_HYST_MASK == 0x3F << CG_HYST_SHIFT, "cg_hysteresis is not a six-bit field"

        # S1: bring-up is complete; no CLOCK_GATE_CONTROL write has been issued.
        self._stamp("S1")

        # S2: reset value.
        raw = await self._rd("RESET")
        assert raw & ENABLES_BM == 0, f"reset enables read 0x{raw & ENABLES_BM:04x}, expected 0"
        hyst = (raw & CG_HYST_MASK) >> CG_HYST_SHIFT
        assert hyst == HYST_RESET, (
            f"reset cg_hysteresis read 0x{hyst:02x}, expected 0x{HYST_RESET:02x}"
        )
        self._stamp("S2")
        self._chk(
            "CHK-CGC-RESET-VALUE",
            f"CLOCK_GATE_CONTROL=0x{raw:016x}: enables 13:0 = 0x{raw & ENABLES_BM:04x}, "
            f"cg_hysteresis 29:24 = 0x{hyst:02x}, response OKAY",
        )

        # S3: walking one.
        reads: list[str] = []
        for i in range(ENABLE_COUNT):
            got = await self._wr_rd(f"WALK1_{i}", BASE | (1 << i))
            assert got & ENABLES_BM == 1 << i, (
                f"walking-one {i}: enables read 0x{got & ENABLES_BM:04x}, expected 0x{1 << i:04x}"
            )
            assert (got & CG_HYST_MASK) >> CG_HYST_SHIFT == HYST_RESET, f"walking-one {i}: hyst"
            reads.append(f"{i}:0x{got & DEFINED_BM:08x}")
            await self._wr_rd(f"WALK1_{i}_CLEAR", BASE)
        self._stamp("S3")
        self._chk(
            "CHK-CGC-WALKING-ONE",
            f"{ENABLE_COUNT} of {ENABLE_COUNT} cells, every response OKAY, enable i alone set, "
            f"cg_hysteresis 0x{HYST_RESET:02x} on every cell; readbacks {' '.join(reads)}",
        )

        # S4: walking zero.
        ones = BASE | ENABLES_BM
        reads = []
        await self._wr_rd("WALK0_ALL", ones)
        for i in range(ENABLE_COUNT):
            got = await self._wr_rd(f"WALK0_{i}", ones & ~(1 << i))
            assert got & ENABLES_BM == ENABLES_BM & ~(1 << i), (
                f"walking-zero {i}: enables read 0x{got & ENABLES_BM:04x}"
            )
            assert (got & CG_HYST_MASK) >> CG_HYST_SHIFT == HYST_RESET, f"walking-zero {i}: hyst"
            reads.append(f"{i}:0x{got & DEFINED_BM:08x}")
            await self._wr_rd(f"WALK0_{i}_RESTORE", ones)
        await self._restore("WALK0")
        self._stamp("S4")
        self._chk(
            "CHK-CGC-WALKING-ZERO",
            f"{ENABLE_COUNT} of {ENABLE_COUNT} cells, every response OKAY, enable i alone clear "
            f"from all-ones, cg_hysteresis 0x{HYST_RESET:02x} on every cell; "
            f"readbacks {' '.join(reads)}",
        )

        # S5: hysteresis range with the enables held all clear, then all set.
        reads = []
        for pattern_name, pattern in (("CLEAR", 0), ("SET", ENABLES_BM)):
            for value in HYST_VALUES:
                word = pattern | (value << CG_HYST_SHIFT)
                got = await self._wr_rd(f"HYST_{pattern_name}_{value:02x}", word)
                assert (got & CG_HYST_MASK) >> CG_HYST_SHIFT == value, (
                    f"hysteresis 0x{value:02x} ({pattern_name}): read "
                    f"0x{(got & CG_HYST_MASK) >> CG_HYST_SHIFT:02x}"
                )
                assert got & ENABLES_BM == pattern, (
                    f"hysteresis 0x{value:02x} ({pattern_name}): enables read "
                    f"0x{got & ENABLES_BM:04x}, expected 0x{pattern:04x}"
                )
                reads.append(f"{pattern_name.lower()}/0x{value:02x}:0x{got & DEFINED_BM:08x}")
            await self._restore(f"HYST_{pattern_name}")
        self._stamp("S5")
        self._chk(
            "CHK-CGC-HYST-RANGE",
            f"hysteresis {' '.join(f'0x{v:02x}' for v in HYST_VALUES)} read back as written in "
            f"both patterns, enables held, every response OKAY; readbacks {' '.join(reads)}",
        )

        # S6: reserved bits, printed and not compared.
        notes: list[str] = []
        for name, mask in (("23_14", RESERVED_LO_BM), ("63_30", RESERVED_HI_BM)):
            resp = await self._wr(f"RSVD_{name}", BASE | mask, tolerate_error=True)
            got = await self._rd(f"RSVD_{name}_RB")
            assert got & DEFINED_BM == BASE, (
                f"reserved write {name}: defined fields read 0x{got & DEFINED_BM:016x}, "
                f"held 0x{BASE:016x}"
            )
            notes.append(
                f"ones to bits {name.replace('_', ':')} response {resp} "
                f"readback 0x{got:016x} reserved bits 0x{got & ~DEFINED_BM & (2**64 - 1):016x}"
            )
            await self._restore(f"RSVD_{name}")
        self._stamp("S6")
        self._chk(
            "CHK-CGC-RESERVED-BITS",
            f"defined fields held 0x{BASE:016x} across both writes; {'; '.join(notes)}; "
            f"reserved value not asserted (not specified, measured)",
        )

        # S7: narrow accesses, printed and not compared.
        hi_addr = CLOCK_GATE_CONTROL + 4
        low_val = 0x0000_0555
        high_val = 0x2A00_0000
        partial_val = 0x1500_0000_0000_0A0A
        partial_strb = 0x05
        notes = []
        _, resp = await self._access(
            "NARROW_LOW", SmcSysAxiOp.WRITE, CLOCK_GATE_CONTROL, low_val, 4, None, True
        )
        got = await self._rd("NARROW_LOW_RB")
        notes.append(f"32-bit low 0x{low_val:08x} response {resp} readback 0x{got:016x}")
        await self._restore("NARROW_LOW")
        _, resp = await self._access(
            "NARROW_HIGH", SmcSysAxiOp.WRITE, hi_addr, high_val, 4, None, True
        )
        got = await self._rd("NARROW_HIGH_RB")
        notes.append(f"32-bit high 0x{high_val:08x} response {resp} readback 0x{got:016x}")
        await self._restore("NARROW_HIGH")
        item = SmcSysAxiItem("wr_NARROW_STROBED")
        item.op = SmcSysAxiOp.WRITE
        item.addr = CLOCK_GATE_CONTROL
        item.length = 8
        item.wdata = partial_val
        item.wstrb = partial_strb
        item.allow_error = True
        item.timeout_ns = ACCESS_TIMEOUT_NS
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None, "strobed write: no response code"
        got = await self._rd("NARROW_STROBED_RB")
        notes.append(
            f"64-bit data 0x{partial_val:016x} wstrb 0x{partial_strb:02x} response "
            f"{item.resp_code} readback 0x{got:016x}"
        )
        await self._restore("NARROW_STROBED")
        self._stamp("S7")
        self._chk(
            "CHK-CGC-NARROW-ACCESS",
            f"{'; '.join(notes)}; every access completed, responses and values "
            f"not asserted (not specified, measured)",
        )

        # S8: rewrites.
        notes = []
        same = BASE | (1 << 5)
        await self._wr("SAME_1", same)
        first = await self._rd("SAME_1_RB")
        await self._wr("SAME_2", same)
        got = await self._rd("SAME_2_RB")
        assert got & DEFINED_BM == same == first & DEFINED_BM, f"same-value write read 0x{got:x}"
        notes.append(f"same value twice 0x{same:08x} read 0x{got & DEFINED_BM:08x}")
        await self._restore("SAME")
        for level in (1, 0, 1):
            await self._wr(f"TOGGLE_{level}", BASE | (level << 3))
        got = await self._rd("TOGGLE_RB")
        assert got & DEFINED_BM == BASE | (1 << 3), f"1-0-1 sequence read 0x{got:x}"
        notes.append(f"1-0-1 on enable 3 read 0x{got & DEFINED_BM:08x}")
        await self._restore("TOGGLE")
        await self._wr("PAIR_A", BASE | (1 << 2))
        await self._wr("PAIR_B", BASE | (1 << 9))
        got = await self._rd("PAIR_RB")
        assert got & DEFINED_BM == BASE | (1 << 9), f"successive pair read 0x{got:x}"
        notes.append(f"successive pair read 0x{got & DEFINED_BM:08x}")
        await self._restore("PAIR")
        self._stamp("S8")
        self._chk(
            "CHK-CGC-REWRITE",
            f"{'; '.join(notes)}; other fields equal 0x{BASE:08x}, every response OKAY",
        )

        times, stamp_text = self._assert_fence()
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(FENCE_TERMS),
            ", ".join(c for c, _ in CHECKER_STEPS),
            stamp_text,
        )
        self.chk_seen["CHK-NONVAC"] = "printed"
        assert times == sorted(set(times))
