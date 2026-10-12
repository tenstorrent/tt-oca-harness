# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Reset behaviour of shadow words and locks of SMC_EFUSE_MAP.

Contract SMC_EFUSE_MAP_019, anchor smc_efuse_map_reset_persistence_test.
Scenarios EMAP-RESET-WARM.S1-S4, EMAP-RESET-COLD.S2/S6; the warm reset is driven through
the JTAG reset-control override (gate map019-warm-reset-source; contract revision 2).
Sources: smu-smc.adoc (eFuse Interface), clk_rst.adoc (rst_warm_n), smc-programming.adoc (LOCKS).

SPARE[3] (map words 56-63) holds P1 under a write lock, SPARE[4] word 0 (map word 64) holds P2
under a read lock. A warm reset keeps both and does not re-sense; a cold reset clears the locks
and re-senses the all-zero image.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time
from env.smc_reset_item import SmcResetOp
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import jtag_smc_reset_ctrl_bit, jtag_smc_reset_ctrl_width
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_image_pattern_test_seq import (
    LOCKS_WORDS,
    REGIONS,
    EfuseImage,
    word_addr,
)
from .smc_reset_seq_base import SmcResetSeqBase

_WORD_MASK = 0xFFFF_FFFF
_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")
_SENSE_BOUND_CYCLES = 200_000
_MID_BOUND_EDGES = 200_000
_PIN_BOUND = 64
_RECOVERY_BOUND = 50_000
_PRE_EDGES = 100
_POST_EDGES = 2000
_MID_GAP_EDGES = 2
_DRIVER_BOUND_NS = 50_000
_P1, _P2, _P3, _P4 = 0xA5C3_1E71, 0x3C69_D2B4, 0x5AE1_7C93, 0xC7D2_0B58
_LOCKS_SET = 0x0002_4000
_CHK_STEP = {
    "CHK-EMAP-RST-WARM-VALUES": "S3",
    "CHK-EMAP-RST-WARM-LOCKS": "S4",
    "CHK-EMAP-RST-WARM-NORESENSE": "S5",
    "CHK-EMAP-RST-WARM-MID": "S6",
    "CHK-EMAP-RST-COLD-LOCKS": "S7",
    "CHK-EMAP-RST-COLD-MID": "S8",
}


def _warm_pack(*, ovrd: int, val: int) -> int:
    """Packed jtag_reset_ctrl_i with only the SMC warm_reset_n override bits set."""
    v = 0
    if ovrd:
        v |= 1 << jtag_smc_reset_ctrl_bit("warm_reset_n_ovrd")
    if val:
        v |= 1 << jtag_smc_reset_ctrl_bit("warm_reset_n_val")
    return v


class smc_efuse_map_reset_persistence_test_seq(SmcResetSeqBase, SmcCsrSeq):
    """Warm and cold reset effects on SPARE words and LOCKS, idle and mid-access."""

    def __init__(self, name: str = "smc_efuse_map_reset_persistence_test_seq") -> None:
        super().__init__(name)
        self.image: EfuseImage | None = None
        self.dispatch_reset = None
        self.dispatch_sep_in = None
        self.seed = 1
        self.access_floor = 0
        self.locks_model = 0
        self._calls = 0
        self._events: list[tuple[str, str]] = []
        self._stamps: list[tuple[str, int]] = []
        self._waits: list[tuple[str, int, str]] = []
        self._samples = 0
        self._drops = 0
        self._low_samples = 0
        self._first_stamp = 0
        self._last_stamp = 0
        self._release_sample = None
        self._sampler_done = False
        self._mid_warm = (0, 0)
        self._orphan: dict = {}

    async def _dispatch_reset_item(self, item) -> None:
        await self.dispatch_reset(item)

    # --- fence ----------------------------------------------------------
    def _done(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))
        self._events.append(("step", step))

    def _chk(self, chk_id: str, fmt: str, *args) -> None:
        self._events.append(("chk", chk_id))
        cocotb.log.info("%s: " + fmt, chk_id, *args)

    # --- probes ---------------------------------------------------------
    @staticmethod
    def _sig(name: str) -> int:
        dut = cocotb.top
        assert hasattr(dut, name), f"{name} is not a signal of the testbench top"
        value = getattr(dut, name).value
        assert value.is_resolvable, f"{name} is X/Z: {value}"
        return int(value)

    def _sense_state(self) -> str:
        return (
            f"tb_fuse_sense_done={self._sig('tb_fuse_sense_done')},"
            f"tb_fuse_reset_n={self._sig('tb_fuse_reset_n')},"
            f"tb_rst_warm_smc_clk_n={self._sig('tb_rst_warm_smc_clk_n')}"
        )

    async def _sense_wait(self, label: str) -> None:
        try:
            await self.wait_fuse_sense_done(_SENSE_BOUND_CYCLES)
        except AssertionError as exc:
            raise AssertionError(f"{label}: {exc}; {self._sense_state()}") from exc
        self._waits.append((label, _SENSE_BOUND_CYCLES, self._sense_state()))

    # --- access ---------------------------------------------------------
    async def _rd(self, label: str, addr: int, expected: int) -> int:
        self._calls += 1
        return await self.csr_read(label, addr, expected=expected)

    async def _read_locks(self, label: str) -> tuple[int, int]:
        addr = word_addr(LOCKS_WORDS[0])
        lo = await self._rd(f"{label}_LO", addr, self.locks_model & _WORD_MASK)
        hi = await self._rd(f"{label}_HI", addr + 4, self.locks_model >> 32)
        return lo & _WORD_MASK, hi & _WORD_MASK

    async def _write_word(self, label: str, word: int, data: int) -> int:
        item = SmcSysAxiItem(f"wr_{label}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = word_addr(word)
        item.length = 4
        item.wdata = data
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self._calls += 1
        assert item.resp_code is not None, f"{label}: the write got no response"
        return item.resp_code

    async def _read_any(self, label: str, word: int) -> int:
        item = SmcSysAxiItem(f"rd_{label}")
        item.op = SmcSysAxiOp.READ
        item.addr = word_addr(word)
        item.length = 4
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self._calls += 1
        assert item.resp_code is not None, f"{label}: the read got no response"
        return item.rdata & _WORD_MASK

    async def _expect_words(self, label: str, words: range, expected: int) -> None:
        for word in words:
            await self._rd(f"{label}_{word}", word_addr(word), expected)

    async def _expect_hidden(self, label: str, word: int, held: int) -> int:
        got = await self._read_any(label, word)
        assert got not in (held, ~held & _WORD_MASK), (
            f"{label}: word {word} reads 0x{got:08x} with its read lock set; "
            f"the field holds 0x{held:08x}"
        )
        return got

    # --- resets ---------------------------------------------------------
    async def _warm_reset(self, label: str, on_fall=None) -> tuple[int, int]:
        """Assert and release the warm reset through the JTAG override; returns edge counts."""
        dut = cocotb.top
        clk = dut.clk_smc_i
        assert self._sig("tb_rst_warm_smc_clk_n") == 1, f"{label}: the warm domain is not released"
        assert int(dut.tb_jtag_reset_ctrl.value) == 0, f"{label}: the override is not idle"
        dut.tb_jtag_reset_ctrl.value = _warm_pack(ovrd=1, val=0)
        low = 0
        for low in range(1, _PIN_BOUND + 1):
            await RisingEdge(clk)
            if self._sig("tb_rst_warm_smc_clk_n") == 0:
                if on_fall is not None:
                    on_fall()
                break
        else:
            raise AssertionError(
                f"{label}: tb_rst_warm_smc_clk_n still 1 {_PIN_BOUND} edges after the override"
            )
        self._waits.append((f"{label}_drop", _PIN_BOUND, f"tb_rst_warm_smc_clk_n=0 after {low}"))
        dut.tb_jtag_reset_ctrl.value = 0
        rise = 0
        for rise in range(1, _RECOVERY_BOUND + 1):
            await RisingEdge(clk)
            if self._sig("tb_rst_warm_smc_clk_n") == 1:
                break
        else:
            raise AssertionError(
                f"{label}: tb_rst_warm_smc_clk_n still 0 {_RECOVERY_BOUND} edges after release; "
                f"{self._sense_state()}"
            )
        self._waits.append(
            (f"{label}_rise", _RECOVERY_BOUND, f"tb_rst_warm_smc_clk_n=1 after {rise}")
        )
        return low, rise

    async def _cold_assert(self, label: str) -> None:
        await self._send(SmcResetOp.COLD_RST_LO)
        await self._cold_assert_wait(label)

    async def _cold_assert_wait(self, label: str) -> None:
        await self._wait_state(
            f"{label} cold assert",
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=0,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        assert self._sig("tb_fuse_sense_done") == 0, (
            f"{label}: tb_fuse_sense_done is still 1 with the cold reset asserted"
        )

    async def _cold_fall_watch(self, label: str, on_fall) -> None:
        """Calls on_fall on the first clk_smc_i edge that samples rst_primary_smc_clk_no low."""
        clk = cocotb.top.clk_smc_i
        for _ in range(_MID_BOUND_EDGES):
            await RisingEdge(clk)
            if self._sig("rst_primary_smc_clk_no") == 0:
                on_fall()
                return
        raise AssertionError(
            f"{label}: rst_primary_smc_clk_no still 1 {_MID_BOUND_EDGES} edges after "
            f"COLD_RST_LO; {self._sense_state()}"
        )

    async def _cold_release(self, label: str) -> None:
        await self._send(SmcResetOp.COLD_RST_HI)
        await self._wait_released(f"{label} cold release")
        await self._sense_wait(f"{label}_sense")

    # --- sampler --------------------------------------------------------
    async def _sampler(self) -> None:
        clk = cocotb.top.clk_smc_i
        prev = None
        while not self._sampler_done:
            await RisingEdge(clk)
            now = self._sig("tb_fuse_sense_done")
            self._samples += 1
            self._last_stamp = int(get_sim_time("ps"))
            if self._samples == 1:
                self._first_stamp = self._last_stamp
            if now == 0:
                self._low_samples += 1
            if prev == 1 and now == 0:
                self._drops += 1
            prev = now
            if (
                self._release_sample is not None
                and self._samples - self._release_sample >= _POST_EDGES
            ):
                self._sampler_done = True

    # --- mid-reset read -------------------------------------------------
    async def _orphan_watch(self, fall_n: int) -> None:
        """Samples s_axi_rvalid on every clk_smc_i edge from the primary-reset fall until the
        AR handshake of the first read issued after the release."""
        clk = cocotb.top.clk_smc_i
        orphan = self._orphan
        released = False
        while not orphan["done"]:
            if self._sig("s_axi_rvalid") == 1:
                orphan["hits"] += 1
                orphan["first_hit"] = orphan["first_hit"] or fall_n + orphan["samples"]
            if self._sig("rst_primary_smc_clk_no") == 1:
                released = True
            hs = self._sig("s_axi_arvalid") == 1 and self._sig("s_axi_arready") == 1
            if released and hs:
                orphan["done"] = True
                orphan["live_n"] = fall_n + orphan["samples"]
            orphan["samples"] += 1
            if not orphan["done"]:
                await RisingEdge(clk)

    async def _mid_read(
        self, label: str, reset_action, *, gap_edges: int, repeat: bool, watch_orphan: bool
    ) -> dict:
        """Run SEP_IN LOCKS reads while reset_action drives a domain reset.

        reset_action(on_fall) calls on_fall on the edge the domain reset reaches the DUT.
        With repeat, reads are re-issued back-to-back until one is aborted or the reset fell.
        A read resolves as completed (resp_code 0) or aborted-by-reset-flush (no response, no
        driver timeout); a driver timeout raises.
        """
        clk = cocotb.top.clk_smc_i
        st = {
            "n": 0,
            "pending": False,
            "issue_n": 0,
            "fall_n": None,
            "fall_pending": None,
            "stop": False,
            "outcome": [],
            "done_n": 0,
            "reads": 0,
        }
        last: dict = {}

        async def ticker() -> None:
            while True:
                await RisingEdge(clk)
                st["n"] += 1

        def on_fall() -> None:
            st["fall_n"] = st["n"]
            st["fall_pending"] = st["pending"]
            st["stop"] = True
            if watch_orphan:
                self._orphan = {
                    "samples": 0,
                    "hits": 0,
                    "first_hit": 0,
                    "done": False,
                    "live_n": 0,
                }
                cocotb.start_soon(self._orphan_watch(st["n"]))

        async def runner() -> None:
            while True:
                item = SmcSysAxiItem(f"rd_{label}_{st['reads']}")
                item.op = SmcSysAxiOp.READ
                item.addr = word_addr(LOCKS_WORDS[0])
                item.length = 4
                item.allow_error = True
                item.allow_timeout = True
                item.timeout_ns = _DRIVER_BOUND_NS
                last["item"] = item
                st["reads"] += 1
                st["pending"] = True
                st["issue_n"] = st["n"]
                try:
                    await self.dispatch_sep_in(item, f"{label}_os_{st['reads']}")
                    if item.timed_out:
                        last["res"] = "timed-out"
                    elif item.resp_code is None:
                        last["res"] = "aborted-by-reset-flush"
                    else:
                        last["res"] = "completed"
                except Exception as exc:
                    last["res"] = f"exception:{type(exc).__name__}:{exc}"
                st["done_n"] = st["n"]
                if last["res"] != "aborted-by-reset-flush":
                    st["pending"] = False
                if last["res"] == "completed":
                    self.accesses += 1
                    self._calls += 1
                if not repeat or st["stop"] or last["res"] != "completed":
                    break
            st["outcome"].append(last["res"])

        tick = cocotb.start_soon(ticker())
        task = cocotb.start_soon(runner())
        for _ in range(gap_edges):
            await RisingEdge(clk)
        action = cocotb.start_soon(reset_action(on_fall))
        waited = 0
        while not st["outcome"] and waited < _MID_BOUND_EDGES:
            await RisingEdge(clk)
            waited += 1
        tick.cancel()
        item = last["item"]
        item_state = (
            f"timed_out={item.timed_out} resp_code={item.resp_code} "
            f"done@{st['done_n']} issue@{st['issue_n']} bound_ns={_DRIVER_BOUND_NS}"
        )
        if not st["outcome"]:
            task.cancel()
            raise AssertionError(
                f"{label}: the SEP_IN read neither completed nor aborted within "
                f"{_MID_BOUND_EDGES} edges; {item_state}; {self._sense_state()}"
            )
        assert not item.timed_out, (
            f"{label}: the SEP_IN read hit the {_DRIVER_BOUND_NS} ns driver bound; {item_state}; "
            f"{self._sense_state()}"
        )
        res = last["res"]
        assert res in ("completed", "aborted-by-reset-flush"), (
            f"{label}: the SEP_IN read resolved as {res}; {item_state}"
        )
        await action
        assert st["fall_n"] is not None, f"{label}: the domain reset never fell"
        assert st["done_n"] - st["issue_n"] <= _MID_BOUND_EDGES, (
            f"{label}: the SEP_IN read resolved {st['done_n'] - st['issue_n']} edges after its "
            f"AR issue, bound {_MID_BOUND_EDGES}; {item_state}"
        )
        if res == "completed":
            assert item.resp_code == 0, f"{label}: the read completed with rresp {item.resp_code}"
        if res == "aborted-by-reset-flush" or not watch_orphan:
            assert st["fall_pending"], (
                f"{label}: no SEP_IN read was outstanding when the domain reset fell "
                f"(fall edge {st['fall_n']}, {st['reads']} reads issued); {item_state}"
            )
        else:
            assert st["done_n"] <= st["fall_n"], (
                f"{label}: the read completed {st['done_n'] - st['fall_n']} edges after the "
                f"primary-reset fall; {item_state}"
            )
        self._waits.append((f"{label}_item_driver", _DRIVER_BOUND_NS, f"ns {item_state}"))
        self._waits.append(
            (
                f"{label}_item_edges",
                _MID_BOUND_EDGES,
                f"{res} {st['done_n'] - st['issue_n']} edges after AR issue {item_state}",
            )
        )
        return {
            "res": res,
            "ar": st["issue_n"],
            "fall": st["fall_n"],
            "done": st["done_n"],
            "reads": st["reads"],
            "after_fall": st["done_n"] - st["fall_n"],
            "rresp": item.resp_code,
            "rdata": 0 if item.rdata is None else item.rdata & _WORD_MASK,
            "gap": gap_edges,
            "outstanding": bool(st["fall_pending"]),
        }

    # --- body -----------------------------------------------------------
    async def body(self) -> None:
        dut = cocotb.top
        image = self.image
        assert image is not None, "the testcase module sets the image before starting"
        for name in (
            "tb_jtag_reset_ctrl",
            "tb_rst_warm_smc_clk_n",
            "tb_fuse_sense_done",
            "rst_primary_smc_clk_no",
            "s_axi_rvalid",
            "s_axi_arvalid",
            "s_axi_arready",
        ):
            assert hasattr(dut, name), f"{name} is not a signal of the testbench top"
        assert len(dut.tb_jtag_reset_ctrl.value) == jtag_smc_reset_ctrl_width(), (
            f"jtag_reset_ctrl width {len(dut.tb_jtag_reset_ctrl.value)} is not "
            f"{jtag_smc_reset_ctrl_width()}"
        )
        reg = {r.name: r for r in REGIONS}
        spare3 = range(reg["SPARE3"].first_word, reg["SPARE3"].end_word)
        spare4_w0 = reg["SPARE4"].first_word
        assert (spare3.start, len(spare3), spare4_w0) == (56, 8, 64), (
            f"SPARE[3] words {spare3}, SPARE[4] first word {spare4_w0}"
        )
        wl3, rl4 = reg["SPARE3"].write_lock, reg["SPARE4"].read_lock
        assert (wl3, rl4) == (1 << 14, 1 << 17), (
            f"lock masks 0x{wl3:x}/0x{rl4:x} are not LOCKS bits 14/17"
        )
        assert wl3 | rl4 == _LOCKS_SET
        pats = (_P1, _P2, _P3, _P4)
        assert all(p not in (0, _WORD_MASK) for p in pats)
        assert len({p for p in pats} | {~p & _WORD_MASK for p in pats}) == 8, "patterns collide"
        assert all(w == 0 for w in image.words), "the image has a non-zero word"
        self.locks_model = image.locks
        assert self.locks_model == 0, f"image LOCKS 0x{self.locks_model:x} is not 0"

        # S1: sense
        await self._sense_wait("sense1")
        await self._read_locks("BASE_LOCKS")
        self._done("S1")

        # S2: setup
        for word in spare3:
            await self._write_word(f"S2_P1_{word}", word, _P1)
        await self._write_word("S2_P2", spare4_w0, _P2)
        await self._expect_words("S2_RB3", spare3, _P1)
        await self._expect_words("S2_RB4", range(spare4_w0, spare4_w0 + 1), _P2)
        self._calls += 1
        await self.csr_write("S2_LOCKS", word_addr(LOCKS_WORDS[0]), wl3 | rl4, length=8)
        self.locks_model |= wl3 | rl4
        assert self.locks_model == _LOCKS_SET
        lo, hi = await self._read_locks("S2_LOCKS_RB")
        assert (lo, hi) == (_LOCKS_SET, 0)
        self._done("S2")

        # S3: warm reset through the JTAG override, sampler window opened first
        sampler = cocotb.start_soon(self._sampler())
        for _ in range(_PRE_EDGES + 2):
            if self._samples >= _PRE_EDGES:
                break
            await RisingEdge(dut.clk_smc_i)
        pre_samples = self._samples
        assert pre_samples >= _PRE_EDGES, f"{pre_samples} samples before the warm reset"
        low, rise = await self._warm_reset("warm1")
        self._release_sample = self._samples
        await self._expect_words("S3_WARM_RB3", spare3, _P1)
        self._done("S3")
        self._chk(
            "CHK-EMAP-RST-WARM-VALUES",
            "warm reset through the JTAG reset-control override: tb_rst_warm_smc_clk_n fell "
            "%d edges after the override and rose %d edges after release; all %d SPARE[3] "
            "words read P1=0x%08x",
            low,
            rise,
            len(spare3),
            _P1,
        )

        # S4: locks and denies after the warm reset
        resp = await self._write_word("S4_P3", spare3[0], _P3)
        await self._rd("S4_P3_RB", word_addr(spare3[0]), _P1)
        hidden = await self._expect_hidden("S4_HIDDEN4", spare4_w0, _P2)
        lo, hi = await self._read_locks("S4_LOCKS")
        assert (lo, hi) == (_LOCKS_SET, 0)
        self._done("S4")
        self._chk(
            "CHK-EMAP-RST-WARM-LOCKS",
            "after the warm reset LOCKS lo=0x%08x hi=0x%08x; the write of P3=0x%08x to SPARE[3] "
            "word 0 (bresp %s) left P1=0x%08x; SPARE[4] word 0 read 0x%08x, neither P2=0x%08x "
            "nor its complement",
            lo,
            hi,
            _P3,
            resp,
            _P1,
            hidden,
            _P2,
        )

        # S5: no re-sense, sampled window
        waited = 0
        while not self._sampler_done and waited < _POST_EDGES + 100:
            await RisingEdge(dut.clk_smc_i)
            waited += 1
        assert self._sampler_done, (
            f"S5: the sampler did not finish {_POST_EDGES} edges after the release; "
            f"{self._samples} samples; {self._sense_state()}"
        )
        self._waits.append(("sampler_post_window", _POST_EDGES + 100, f"{self._samples} samples"))
        await sampler
        assert self._drops == 0 and self._low_samples == 0, (
            f"tb_fuse_sense_done dropped {self._drops} time(s) and read 0 on "
            f"{self._low_samples} of {self._samples} samples across the warm reset"
        )
        await self._expect_words("S5_NORELOAD3", spare3[:1], _P1)
        self._done("S5")
        self._chk(
            "CHK-EMAP-RST-WARM-NORESENSE",
            "tb_fuse_sense_done read 1 on all %d clk_smc_i samples (%d before the warm reset "
            "assertion, %d after the release), %d 1-to-0 transitions, first %d ps, last %d ps; "
            "SPARE[3] word 0 still reads P1=0x%08x",
            self._samples,
            pre_samples,
            _POST_EDGES,
            self._drops,
            self._first_stamp,
            self._last_stamp,
            _P1,
        )

        # S6: warm reset two edges after a SEP_IN read starts
        async def warm_action(on_fall) -> None:
            self._mid_warm = await self._warm_reset("warm2", on_fall)

        mid = await self._mid_read(
            "S6_MID", warm_action, gap_edges=_MID_GAP_EDGES, repeat=False, watch_orphan=False
        )
        lo, hi = await self._read_locks("S6_LOCKS")
        assert (lo, hi) == (_LOCKS_SET, 0)
        self._done("S6")
        self._chk(
            "CHK-EMAP-RST-WARM-MID",
            "warm reset %d edges after the LOCKS read started (fell %d, rose %d edges after the "
            "override): ar@%d fall@%d outstanding=%s resolution=%s done@%d (%d edges after the "
            "fall, bound %d) rresp=%s rdata=0x%08x no_timeout=True orphan_r=n/a (the R beat "
            "was delivered with the response); LOCKS after release lo=0x%08x hi=0x%08x",
            mid["gap"],
            self._mid_warm[0],
            self._mid_warm[1],
            mid["ar"],
            mid["fall"],
            mid["outstanding"],
            mid["res"],
            mid["done"],
            mid["after_fall"],
            _MID_BOUND_EDGES,
            mid["rresp"],
            mid["rdata"],
            lo,
            hi,
        )

        # S7: cold reset
        await self._cold_assert("S7")
        await self._cold_release("S7")
        self.locks_model = image.locks
        lo, hi = await self._read_locks("S7_LOCKS")
        assert (lo, hi) == (0, 0)
        await self._expect_words("S7_ZERO3", spare3, 0)
        await self._write_word("S7_P3", spare3[0], _P3)
        await self._rd("S7_P3_RB", word_addr(spare3[0]), _P3)
        await self._write_word("S7_P4", spare4_w0, _P4)
        await self._rd("S7_P4_RB", word_addr(spare4_w0), _P4)
        self._done("S7")
        self._chk(
            "CHK-EMAP-RST-COLD-LOCKS",
            "after the cold reset and sense done LOCKS lo=0x%08x hi=0x%08x, all %d SPARE[3] "
            "words read 0; P3=0x%08x landed in SPARE[3] word 0 and P4=0x%08x in SPARE[4] word 0",
            lo,
            hi,
            len(spare3),
            _P3,
            _P4,
        )

        # S8: LOCKS reads outstanding while the cold reset reaches the primary domain
        self._calls += 1
        await self.csr_write("S8_LOCKS", word_addr(LOCKS_WORDS[0]), wl3, length=8)
        self.locks_model |= wl3
        lo, hi = await self._read_locks("S8_LOCKS_SET")
        assert (lo, hi) == (wl3, 0)
        await self._send(SmcResetOp.COLD_RST_LO)

        async def cold_action(on_fall) -> None:
            await self._cold_fall_watch("S8", on_fall)

        mid = await self._mid_read(
            "S8_MID", cold_action, gap_edges=0, repeat=True, watch_orphan=True
        )
        await self._cold_assert_wait("S8")
        await self._cold_release("S8")
        self.locks_model = image.locks
        lo, hi = await self._read_locks("S8_LOCKS")
        orphan = self._orphan
        assert orphan["done"], (
            f"S8: no AR handshake of the post-release read was sampled; {orphan['samples']} "
            f"edges sampled, rvalid hits {orphan['hits']}"
        )
        assert orphan["hits"] == 0, (
            f"S8: s_axi_rvalid read 1 on {orphan['hits']} edge(s) between the primary-reset "
            f"fall and the next AR handshake, first at edge {orphan['first_hit']}"
        )
        self._waits.append(
            (
                "S8_orphan_watch",
                orphan["samples"],
                f"s_axi_rvalid never 1 over {orphan['samples']} edges, AR handshake at "
                f"edge {orphan['live_n']}",
            )
        )
        assert (lo, hi) == (0, 0)
        self._done("S8")
        self._chk(
            "CHK-EMAP-RST-COLD-MID",
            "SPARE[3] write lock set before the reset (LOCKS 0x%08x); COLD_RST_LO then LOCKS "
            "reads re-issued (%d issued): ar@%d fall@%d outstanding=%s resolution=%s flush@%d "
            "(%d edges after the fall) orphan_r=%d live_read@%d locks=0x%x/0x%x; no driver "
            "timeout",
            wl3,
            mid["reads"],
            mid["ar"],
            mid["fall"],
            mid["outstanding"],
            mid["res"],
            mid["done"],
            mid["after_fall"],
            orphan["hits"],
            orphan["live_n"],
            lo,
            hi,
        )
        self.access_floor = self._calls

        # fence
        assert [s for s, _t in self._stamps] == list(_STEPS), (
            f"steps completed {[s for s, _t in self._stamps]}, expected {list(_STEPS)}"
        )
        times = [t for _s, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        printed = [ident for kind, ident in self._events if kind == "chk"]
        assert printed == list(_CHK_STEP), f"checker lines printed {printed}"
        for index, (kind, ident) in enumerate(self._events):
            if kind == "chk":
                assert ("step", _CHK_STEP[ident]) in self._events[:index], (
                    f"{ident} printed before step {_CHK_STEP[ident]} completed"
                )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence SETUP < WARM-VALUES < WARM-LOCKS < WARM-NORESENSE < "
            "WARM-MID < COLD-LOCKS < COLD-MID; checker lines %s; stamps %s ps",
            ", ".join(printed),
            ", ".join(f"{s}={t}" for s, t in self._stamps),
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s",
            len(self._waits),
            " ".join(
                f"{name}={bound}(fails with AssertionError on expiry) last={state}"
                for name, bound, state in self._waits
            ),
        )
