# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""START_ADDR / END_ADDR granule write-back and read-only data_bus_width over SEP_IN.

Spec sources: filter_ctrl.rdl FILTER_CONFIG / START_ADDR, axi_filter index.adoc granule examples.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import _REPO, _field_mask, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

_FILTER_H = _REPO / "hw" / "ip" / "axi_filter" / "regs" / "gen" / "c" / "filter_ctrl.h"
DBW_BM = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__DATA_BUS_WIDTH_bm")
DBW_BP = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__DATA_BUS_WIDTH_bp")
ALLOW_BURST = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__ALLOW_BURST_bm")
DBW_RESET = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__DATA_BUS_WIDTH_reset")
FC_RESET = DBW_RESET << DBW_BP
START_RESET = 0
END_RESET = 7
FUSE_WAIT_BOUND_SMC_CYCLES = 200_000
AXI_TIMEOUT_NS = 50_000
ACCESS_COUNT = 94
_RESP_NAMES = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}

_BANKS = ("INBOUND", "OUTBOUND")
_FENCE = (
    "SETUP",
    "DBW_READS",
    "BURST0_PAIR",
    "BURST1_PAIR",
    "ALIGNED_PAIR",
    "OBSERVE_LEG",
    "RESTORED",
)
# (checker id, fence term it follows), in print order.
_CHECKERS = (
    ("CHK-DBW-READ-ONLY", "DBW_READS"),
    ("CHK-GRANULE-BURST0", "BURST0_PAIR"),
    ("CHK-GRANULE-ALIGNED", "ALIGNED_PAIR"),
    ("CHK-GRANULE-BANK-PARITY", "ALIGNED_PAIR"),
    ("CHK-GRANULE-WRITEBACK-OBSERVE", "OBSERVE_LEG"),
    ("CHK-TIMEOUT-PATHS", "RESTORED"),
)


def _reg(bank: str, reg: str, idx: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_{bank}_FILTER_CTRL_{reg}_BASE_ADDR", idx)


class smc_filter_range_granule_test_seq(SmcCsrSeq):
    """Program disabled entries 2 and 3 of both filter banks and read the ranges back."""

    def __init__(self, name: str = "smc_filter_range_granule_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self.last_access = "none"
        self.fuse_state = "not waited"

    def _mark(self, term: str) -> None:
        self._stamps.append((term, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, len(self._stamps)))

    async def _rd(self, label: str, addr: int, expected: int | None = None) -> int:
        item = SmcSysAxiItem(f"rd_{label}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 8
        item.expected = expected
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.rdata is not None, f"{label} @ 0x{addr:08x}: no rdata recorded"
        self.last_access = f"rd {label} resp={item.resp_code} data=0x{item.rdata:x}"
        return item.rdata

    async def _wr(self, label: str, addr: int, data: int, print_resp: bool = False) -> int | None:
        item = SmcSysAxiItem(f"wr_{label}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 8
        item.wdata = data
        if print_resp:
            item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self.last_access = f"wr {label} resp={item.resp_code}"
        return item.resp_code

    async def _program(
        self, bank: str, idx: int, fc: int, start: int | None, end: int | None, tag: str
    ) -> None:
        await self._wr(f"{bank}{idx}_FC_{tag}", _reg(bank, "FILTER_CONFIG", idx), fc)
        if start is not None:
            await self._wr(f"{bank}{idx}_START_{tag}", _reg(bank, "START_ADDR", idx), start)
        if end is not None:
            await self._wr(f"{bank}{idx}_END_{tag}", _reg(bank, "END_ADDR", idx), end)

    async def _read_pair(
        self, bank: str, idx: int, tag: str, want: tuple[int, int] | None = None
    ) -> tuple[int, int]:
        s = await self._rd(
            f"{bank}{idx}_START_{tag}",
            _reg(bank, "START_ADDR", idx),
            None if want is None else want[0],
        )
        e = await self._rd(
            f"{bank}{idx}_END_{tag}", _reg(bank, "END_ADDR", idx), None if want is None else want[1]
        )
        if want is not None:
            assert (s, e) == want, (
                f"{bank} entry {idx} {tag}: read (0x{s:x}, 0x{e:x}), want "
                f"(0x{want[0]:x}, 0x{want[1]:x})"
            )
        return s, e

    async def body(self) -> None:
        await self.wait_fuse_sense_done(FUSE_WAIT_BOUND_SMC_CYCLES)
        states = []
        for name in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            sig = getattr(cocotb.top, name)
            assert sig.value.is_resolvable, f"{name} is X/Z after the wait"
            states.append(f"{name}={int(sig.value)}")
        self.fuse_state = ",".join(states)
        self._mark("SETUP")

        # S2: data_bus_width is read-only.
        dbw_text = []
        for bank in _BANKS:
            fc = _reg(bank, "FILTER_CONFIG", 2)
            reads = [await self._rd(f"{bank}2_FC_RESET", fc, FC_RESET)]
            bresps = []
            for val in (0x0, DBW_BM):
                bresps.append(await self._wr(f"{bank}2_FC_W{val:X}", fc, val, print_resp=True))
                reads.append(await self._rd(f"{bank}2_FC_R{val:X}", fc))
            fields = [(r & DBW_BM) >> DBW_BP for r in reads]
            assert fields == [DBW_RESET] * 3, (
                f"{bank} FILTER_CONFIG data_bus_width reads {fields} (words "
                f"{[hex(r) for r in reads]}), want {DBW_RESET} each time"
            )
            dbw_text.append(
                f"{bank} reads {[f'0x{r:04X}' for r in reads]} bresp "
                f"{[_RESP_NAMES.get(b, b) for b in bresps]}"
            )
        self._mark("DBW_READS")
        self._log_chk(
            "CHK-DBW-READ-ONLY",
            f"data_bus_width reads {DBW_RESET} at reset and after writes of 0 and 0x{DBW_BM:X}: "
            + "; ".join(dbw_text)
            + " (BRESP printed, owner value pending)",
        )

        # S3: granule rounding with allow_burst 0 and 1.
        pairs: dict[str, dict[str, tuple[int, int]]] = {b: {} for b in _BANKS}
        for bank in _BANKS:
            await self._program(bank, 2, 0, 0x1001, 0x1002, "B0")
            pairs[bank]["b0"] = await self._read_pair(bank, 2, "B0", (0x1000, 0x1007))
        self._mark("BURST0_PAIR")
        self._log_chk(
            "CHK-GRANULE-BURST0",
            "allow_burst 0 range 0x1001..0x1002 reads back "
            + "; ".join(f"{b} (0x{pairs[b]['b0'][0]:X}, 0x{pairs[b]['b0'][1]:X})" for b in _BANKS),
        )
        for bank in _BANKS:
            await self._program(bank, 2, ALLOW_BURST, 0x1001, 0x1002, "B1")
            pairs[bank]["b1"] = await self._read_pair(bank, 2, "B1", (0x1000, 0x1FFF))
        self._mark("BURST1_PAIR")

        # S4: aligned range stays unchanged.
        for bank in _BANKS:
            await self._program(bank, 2, ALLOW_BURST, 0x2000, 0x2FFF, "AL")
            pairs[bank]["al"] = await self._read_pair(bank, 2, "AL", (0x2000, 0x2FFF))
        self._mark("ALIGNED_PAIR")
        self._log_chk(
            "CHK-GRANULE-ALIGNED",
            "allow_burst 1 range 0x2000..0x2FFF reads back "
            + "; ".join(f"{b} (0x{pairs[b]['al'][0]:X}, 0x{pairs[b]['al'][1]:X})" for b in _BANKS),
        )
        for key in ("b0", "b1", "al"):
            assert pairs["INBOUND"][key] == pairs["OUTBOUND"][key], (
                f"bank parity broken for {key}: inbound {pairs['INBOUND'][key]} "
                f"outbound {pairs['OUTBOUND'][key]}"
            )
        self._log_chk(
            "CHK-GRANULE-BANK-PARITY",
            "inbound and outbound read-back pairs identical: "
            + ", ".join(
                f"({pairs['INBOUND'][k][0]:#x}, {pairs['INBOUND'][k][1]:#x})"
                for k in ("b0", "b1", "al")
            ),
        )

        # S5: START_ADDR write-back trigger, observe-only.
        obs = []
        for bank in _BANKS:
            await self._rd(f"{bank}3_FC_RESET", _reg(bank, "FILTER_CONFIG", 3), FC_RESET)
            await self._read_pair(bank, 3, "RESET", (START_RESET, END_RESET))
            await self._program(bank, 3, 0, 0x1001, None, "START_ONLY")
            s0, e0 = await self._read_pair(bank, 3, "START_ONLY")
            await self._program(bank, 3, ALLOW_BURST, 0x1001, 0x1002, "B1")
            await self._read_pair(bank, 3, "B1", (0x1000, 0x1FFF))
            await self._wr(f"{bank}3_FC_CLR", _reg(bank, "FILTER_CONFIG", 3), 0)
            s1, e1 = await self._read_pair(bank, 3, "CLR")
            obs.append(
                f"{bank} after START-only start=0x{s0:X} end=0x{e0:X} (reset end "
                f"0x{END_RESET:X}); allow_burst pair (0x1000, 0x1FFF); after allow_burst clear "
                f"start=0x{s1:X} end=0x{e1:X}"
            )
        self._mark("OBSERVE_LEG")
        self._log_chk("CHK-GRANULE-WRITEBACK-OBSERVE", "; ".join(obs) + " (owner value pending)")

        # S6: restore.
        for bank in _BANKS:
            for idx in (2, 3):
                await self._program(bank, idx, FC_RESET, START_RESET, END_RESET, "RESTORE")
                await self._rd(
                    f"{bank}{idx}_FC_RESTORE", _reg(bank, "FILTER_CONFIG", idx), FC_RESET
                )
                await self._read_pair(bank, idx, "RESTORE", (START_RESET, END_RESET))
        self._mark("RESTORED")

        assert self.accesses == ACCESS_COUNT, (
            f"{self.accesses} accesses, required cost {ACCESS_COUNT}"
        )
        self._log_chk(
            "CHK-TIMEOUT-PATHS",
            f"3 fuse sub-waits each {FUSE_WAIT_BOUND_SMC_CYCLES} clk_smc_i rises "
            f"(state {self.fuse_state}); SEP_IN_access {AXI_TIMEOUT_NS}ns x {self.accesses} "
            f"accesses, last {self.last_access}; no other wait; expiry raises AssertionError",
        )
        self._nonvac_fence()

    def _nonvac_fence(self) -> None:
        terms = tuple(t for t, _ in self._stamps)
        assert terms == _FENCE, f"fence terms {terms}, want {_FENCE}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        ids = tuple(c for c, _ in self._chk_marks)
        assert ids == tuple(c for c, _ in _CHECKERS), f"checker lines {ids}"
        for (chk_id, seen), (_, term) in zip(self._chk_marks, _CHECKERS):
            assert seen >= _FENCE.index(term) + 1, f"{chk_id} printed before {term}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            "<".join(_FENCE[1:]),
            ",".join(ids),
            ",".join(f"{t}={p}" for t, p in self._stamps),
        )
