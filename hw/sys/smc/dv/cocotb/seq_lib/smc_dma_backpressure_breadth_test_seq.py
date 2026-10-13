# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DMA copies through a SYS_OUT responder that stalls, delays and holds its channels.

Contract SMC_POWER_DMA_ZEROER_020, anchor smc_dma_backpressure_breadth_test.
Scenarios DMA-AXI-BACKPRESSURE.S1 to S4 (random stalls, in-flight plateau, long hold, realign).
Specs hw/sys/smc/doc/dma.adoc, hw/sys/smc/doc/fabric.adoc, vendor idma overlay dma_ctrl.rdl.

Sources and destinations sit in the output-fabric window and are preloaded and read back
through the responder's backdoor, so no bus traffic other than the DMA's own is added.
The outstanding AR and AW counts come from the SYS_OUT handshakes: AR minus RLAST
handshakes, and AW minus B handshakes.

Every S2 copy holds SYS_OUT AR READY low from before its launch until the egress tally has
seen an ARVALID without ARREADY and the drawn number of further rises has passed. READY then
follows the free-running stall pattern for the rest of the copy.
"""

from __future__ import annotations

import os
import random

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time

from .smc_csr_seq_utils import SmcCsrSeq
from .smc_dma_sanity_test_seq import (
    DMA_CONFIG_ENABLED_ND,
    DMA_CTRL_CONFIG,
    DMA_CTRL_DONE_0,
    DMA_CTRL_DST_ADDRESS_HI,
    DMA_CTRL_DST_ADDRESS_LO,
    DMA_CTRL_DST_STRIDE_HI,
    DMA_CTRL_DST_STRIDE_LO,
    DMA_CTRL_LENGTH_HI,
    DMA_CTRL_LENGTH_LO,
    DMA_CTRL_NEXT_ID_0,
    DMA_CTRL_NUM_REPETITIONS_HI,
    DMA_CTRL_NUM_REPETITIONS_LO,
    DMA_CTRL_SRC_ADDRESS_HI,
    DMA_CTRL_SRC_ADDRESS_LO,
    DMA_CTRL_SRC_STRIDE_HI,
    DMA_CTRL_SRC_STRIDE_LO,
    DMA_CTRL_STATUS_0,
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    OUTBOUND0_END,
    OUTBOUND0_FILTER_CONFIG,
    OUTBOUND0_START,
    PASS_ALL_CONFIG,
)

WINDOW = 0x0200_0000
GUARD = 8
GUARD_BYTE = 0xEE
POISON = 0xA5
POLL_LIMIT = 1000
POLL_CYCLES = 20
WAIT_LIMIT = 40000
PLATEAU_RISES = 256
OUTSTANDING_AR_CAP = 32
LONG_HOLD_RISES = 4096
ROWS = 128
ROW_BYTES = 8
B_DELAY_CYCLES = 24

#: Lengths of the six S2 copies.
RANDOM_LENGTHS = (8, 40, 96, 200, 512, 1000)
RANDOM_STRIDE = 0x1000
S3_SRC = WINDOW + 0x8000
S3_DST = WINDOW + 0x8800
S3B_SRC = WINDOW + 0xA000
S3B_DST = WINDOW + 0xA800
S4_SRC = WINDOW + 0xC000
S4_DST = WINDOW + 0xC800
S4_LEN = 64
S5_SRC = WINDOW + 0xD000 + 3
S5_DST = WINDOW + 0xD800 + 5
S5_LEN = 200

_TB_SIGNALS = (
    "tb_output_axi_arvalid",
    "tb_output_axi_arready",
    "tb_output_axi_awvalid",
    "tb_output_axi_awready",
    "tb_output_axi_wvalid",
    "tb_output_axi_wready",
    "tb_output_axi_bvalid",
    "tb_output_axi_bready",
    "tb_output_axi_resp_hold",
)
_IF_SIGNALS = ("rvalid", "rready", "rlast")


def _pattern(seed: int, addr: int) -> int:
    return ((addr * 13) ^ (addr >> 7) ^ seed ^ 0x3C) & 0xFF


class _Desc:
    def __init__(self, name: str, src: int, dst: int, length: int, reps: int = 1) -> None:
        self.name = name
        self.src = src
        self.dst = dst
        self.length = length
        self.reps = reps
        self.id = -1

    @property
    def total(self) -> int:
        return self.length * self.reps


class _EgressTally:
    """Per-rise sampler of the SYS_OUT handshakes."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.ar_issued = 0
        self.ar_out = 0
        self.ar_out_max = 0
        self.ar_offset = 0
        self.aw_out = 0
        self.aw_out_max = 0
        self.aw_offset = 0
        self.r_beats = 0
        self.stalls = {"ar": 0, "aw": 0, "w": 0}
        self._ar_hs = 0
        self._r_last = 0
        self._aw_hs = 0
        self._b_hs = 0
        self.armed = False
        self.armed_issued = 0
        self.last = -1
        self.unchanged = 0
        self.plateau_done = False
        self.plateau_value = -1
        self.plateau_issued = -1
        self.plateau_at_ps = 0

    def _bit(self, sig, name: str) -> int:
        value = sig.value
        assert value.is_resolvable, f"{name} is X/Z ({value})"
        return int(value)

    def arm_plateau(self) -> None:
        self.armed = True
        self.armed_issued = self.ar_issued
        self.last = -1
        self.unchanged = 0
        self.plateau_done = False

    def reset_maxima(self) -> None:
        self.ar_out_max = self.ar_out
        self.aw_out_max = self.aw_out

    async def run(self) -> None:
        dut = self.dut
        ifc = dut.u_output_axi_if
        while True:
            await RisingEdge(dut.clk_smc_i)
            await ReadOnly()
            tb = {n[len("tb_output_axi_") :]: self._bit(getattr(dut, n), n) for n in _TB_SIGNALS}
            rv = {n: self._bit(getattr(ifc, n), f"u_output_axi_if.{n}") for n in _IF_SIGNALS}
            if tb["arvalid"] and tb["arready"]:
                self._ar_hs += 1
                self.ar_issued += 1
            if rv["rvalid"] and rv["rready"]:
                self.r_beats += 1
                if rv["rlast"]:
                    self._r_last += 1
            if tb["awvalid"] and tb["awready"]:
                self._aw_hs += 1
            if tb["bvalid"] and tb["bready"]:
                self._b_hs += 1
            for chan in ("ar", "aw", "w"):
                if tb[f"{chan}valid"] and not tb[f"{chan}ready"]:
                    self.stalls[chan] += 1
            self.ar_offset = max(self.ar_offset, self._r_last - self._ar_hs)
            self.aw_offset = max(self.aw_offset, self._b_hs - self._aw_hs)
            self.ar_out = self._ar_hs - self._r_last + self.ar_offset
            self.aw_out = self._aw_hs - self._b_hs + self.aw_offset
            self.ar_out_max = max(self.ar_out_max, self.ar_out)
            self.aw_out_max = max(self.aw_out_max, self.aw_out)
            if self.armed and not self.plateau_done and self.ar_issued > self.armed_issued:
                if self.ar_out == self.last:
                    self.unchanged += 1
                else:
                    self.last = self.ar_out
                    self.unchanged = 0
                if self.unchanged >= PLATEAU_RISES:
                    self.plateau_done = True
                    self.plateau_value = self.ar_out
                    self.plateau_issued = self.ar_issued
                    self.plateau_at_ps = int(get_sim_time("ps"))


class _RBeatDelayer:
    """Holds the responder's R and B for a random number of rises before every R beat."""

    def __init__(self, dut, rng: random.Random) -> None:
        self.dut = dut
        self.rng = rng
        self.stop = False
        self.episodes = 0

    async def run(self) -> None:
        dut = self.dut
        ifc = dut.u_output_axi_if
        while not self.stop:
            await RisingEdge(dut.clk_smc_i)
            await FallingEdge(dut.clk_smc_i)
            value = ifc.rvalid.value
            assert value.is_resolvable, f"u_output_axi_if.rvalid is X/Z ({value})"
            if int(value) and not self.stop:
                dut.tb_output_axi_resp_hold.value = 1
                self.episodes += 1
                await ClockCycles(dut.clk_smc_i, self.rng.randint(1, 3))
                await FallingEdge(dut.clk_smc_i)
                dut.tb_output_axi_resp_hold.value = 0


class smc_dma_backpressure_breadth_test_seq(SmcCsrSeq):
    """Copies under random stalls, an R and B hold, a long hold and delayed R beats."""

    def __init__(self, name: str = "smc_dma_backpressure_breadth_test_seq") -> None:
        super().__init__(name)
        self.steps: list[tuple[str, int]] = []
        self.chk_steps: list[tuple[str, str]] = []
        self.chk_ids: list[str] = []
        self.tally: _EgressTally | None = None
        self.seed = 0
        self.rng = random.Random(0)
        self.next_expected_id = 0

    # -- plumbing ---------------------------------------------------------

    def _mark(self, step: str) -> None:
        self.steps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str) -> None:
        assert self.steps and self.steps[-1][0] == step, f"{chk_id} printed before {step} ended"
        self.chk_steps.append((step, chk_id))
        self.chk_ids.append(chk_id)
        cocotb.log.info("%s: %s", chk_id, text)

    @property
    def _responder(self):
        responder = self.cfg.sys_out_mem
        assert responder is not None, "SYS_OUT responder not bound"
        return responder

    async def _pass_all(self) -> None:
        for name, addr, value in (
            ("IN_START", INBOUND0_START, 0),
            ("IN_END", INBOUND0_END, 0x00FF_FFFF_FFFF_FFFF),
            ("IN_CFG", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG),
            ("OUT_START", OUTBOUND0_START, 0),
            ("OUT_END", OUTBOUND0_END, 0x00FF_FFFF_FFFF_FFFF),
            ("OUT_CFG", OUTBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG),
        ):
            await self.csr_write(f"PASS_{name}", addr, value, length=8)

    def _seed_copy(self, d: _Desc) -> bytes:
        payload = bytes(_pattern(self.seed, d.src + i) for i in range(d.total))
        self._responder.write(d.src, payload)
        self._responder.write(d.dst - GUARD, bytes([GUARD_BYTE]) * GUARD)
        self._responder.write(d.dst, bytes([POISON]) * d.total)
        self._responder.write(d.dst + d.total, bytes([GUARD_BYTE]) * GUARD)
        return payload

    def _compare(self, d: _Desc, payload: bytes) -> None:
        got = bytes(self._responder.read(d.dst, d.total))
        assert got == payload, (
            f"{d.name}: destination 0x{d.dst:08x} holds {got[:32].hex()}..., "
            f"expected {payload[:32].hex()}... ({d.total} bytes)"
        )
        before = bytes(self._responder.read(d.dst - GUARD, GUARD))
        after = bytes(self._responder.read(d.dst + d.total, GUARD))
        want = bytes([GUARD_BYTE]) * GUARD
        assert before == want and after == want, (
            f"{d.name}: bytes either side of the destination changed: "
            f"before={before.hex()} after={after.hex()}"
        )
        src = bytes(self._responder.read(d.src, d.total))
        assert src == payload, f"{d.name}: the source bytes changed"

    async def _program(self, d: _Desc) -> None:
        stride = d.length if d.reps > 1 else 0
        for reg, value in (
            (DMA_CTRL_CONFIG, DMA_CONFIG_ENABLED_ND),
            (DMA_CTRL_DST_ADDRESS_LO, d.dst & 0xFFFF_FFFF),
            (DMA_CTRL_DST_ADDRESS_HI, d.dst >> 32),
            (DMA_CTRL_SRC_ADDRESS_LO, d.src & 0xFFFF_FFFF),
            (DMA_CTRL_SRC_ADDRESS_HI, d.src >> 32),
            (DMA_CTRL_LENGTH_LO, d.length),
            (DMA_CTRL_LENGTH_HI, 0),
            (DMA_CTRL_DST_STRIDE_LO, stride),
            (DMA_CTRL_DST_STRIDE_HI, 0),
            (DMA_CTRL_SRC_STRIDE_LO, stride),
            (DMA_CTRL_SRC_STRIDE_HI, 0),
            (DMA_CTRL_NUM_REPETITIONS_LO, d.reps),
            (DMA_CTRL_NUM_REPETITIONS_HI, 0),
        ):
            await self.csr_write(f"{d.name}_0x{reg & 0xFFF:03x}", reg, value)

    async def _launch(self, d: _Desc) -> None:
        # Reading NEXT_ID launches the programmed descriptor.
        d.id = await self.csr_read(f"{d.name}_NEXT_ID", DMA_CTRL_NEXT_ID_0)
        assert d.id == self.next_expected_id + 1, (
            f"{d.name}: NEXT_ID returned {d.id} after DONE {self.next_expected_id}"
        )

    async def _await_done(self, d: _Desc) -> None:
        done = -1
        for _ in range(POLL_LIMIT):
            done = await self.csr_read(f"{d.name}_DONE", DMA_CTRL_DONE_0)
            if done == d.id:
                self.next_expected_id = d.id
                return
            assert done < d.id, f"{d.name}: DONE_0 reads {done}, past its id {d.id}"
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        raise AssertionError(
            f"{d.name}: DONE_0 reached {done}, not id {d.id} within {POLL_LIMIT} polls"
        )

    async def _hold_ar(self, d: _Desc, ar: int, before: int) -> tuple[int, int]:
        t = self.tally
        clk = cocotb.top.clk_smc_i
        rises = 0
        while t.stalls["ar"] <= before:
            assert rises < WAIT_LIMIT, (
                f"{d.name}: no ARVALID without ARREADY within {WAIT_LIMIT} clk_smc_i rises "
                f"of the AR hold: ar_issued={t.ar_issued} ar_out={t.ar_out}"
            )
            await ClockCycles(clk, 1)
            rises += 1
        await ClockCycles(clk, ar)
        await FallingEdge(clk)
        self._responder.driver.read_if.ar_channel.pause = False
        self._responder.enable_backpressure(channels=["ar"], stall_cycles=ar)
        delta = t.stalls["ar"] - before
        assert delta >= 1, f"{d.name}: no bus-observed AR stall ({delta})"
        return delta, rises

    async def _wait_flag(self, what: str, cond, limit: int = WAIT_LIMIT) -> None:
        for _ in range(limit):
            if cond():
                return
            await ClockCycles(cocotb.top.clk_smc_i, 1)
        t = self.tally
        raise AssertionError(
            f"{what} not reached within {limit} clk_smc_i rises: ar_out={t.ar_out} "
            f"ar_issued={t.ar_issued} aw_out={t.aw_out} unchanged={t.unchanged}"
        )

    # -- steps ------------------------------------------------------------

    async def _s1(self) -> None:
        dut = cocotb.top
        for name in _TB_SIGNALS:
            assert hasattr(dut, name), f"tb_top has no {name}"
        for name in _IF_SIGNALS:
            assert hasattr(dut.u_output_axi_if, name), f"u_output_axi_if has no {name}"
        await self._pass_all()
        self.seed = int(os.environ.get("RANDOM_SEED", "1"), 0)
        self.rng = random.Random(self.seed)
        cocotb.log.info("DMA-BP-BREADTH seed=%d", self.seed)
        self.tally = _EgressTally(dut)
        cocotb.start_soon(self.tally.run())
        self.next_expected_id = await self.csr_read("DONE_BASE", DMA_CTRL_DONE_0)
        await ClockCycles(dut.clk_smc_i, 2)
        self._mark("S1")

    async def _s2(self) -> str:
        resp = self._responder
        applied = {"r_delay": 0, "b_delay": 0}

        def draws(kind: str, count: int):
            for _ in range(count):
                applied[kind] += 1
                yield self.rng.randint(1, 8)

        stall_log = []
        ar_counts = []
        ar_waits = []
        for i, length in enumerate(RANDOM_LENGTHS):
            base = WINDOW + i * RANDOM_STRIDE
            d = _Desc(f"RND{i}", base + 0x10, base + 0x810, length)
            ar, aw, w = (self.rng.randint(1, 5) for _ in range(3))
            resp.disable_backpressure()
            resp.enable_backpressure(channels=["aw"], stall_cycles=aw)
            resp.enable_backpressure(channels=["w"], stall_cycles=w)
            resp.set_response_delay(draws("r_delay", 4096), read=True, write=False)
            resp.set_response_delay(draws("b_delay", 4096), read=False, write=True)
            stall_log.append(f"{length}B(ar={ar},aw={aw},w={w})")
            payload = self._seed_copy(d)
            await self._program(d)
            await FallingEdge(cocotb.top.clk_smc_i)
            resp.driver.read_if.ar_channel.pause = True
            before = self.tally.stalls["ar"]
            await self._launch(d)
            delta, rises = await self._hold_ar(d, ar, before)
            ar_counts.append(delta)
            ar_waits.append(rises)
            await self._await_done(d)
            self._compare(d, payload)
        resp.disable_backpressure()
        resp.clear_response_delay()
        t = self.tally
        kinds = {**t.stalls, **applied}
        missing = [k for k, v in kinds.items() if v <= 0]
        assert not missing, f"stall or delay kinds never applied: {missing} ({kinds})"
        self._mark("S2")
        return (
            f"seed {self.seed}; six copies of {', '.join(stall_log)} delivered their exact "
            f"payload with DONE_0 equal to each id; per-copy bus-observed AR stalls {ar_counts}, "
            f"rises of AR hold before the first AR {ar_waits}; stall and delay counts {kinds}"
        )

    async def _plateau_copy(self, d: _Desc, hold: bool) -> bytes:
        dut = cocotb.top
        t = self.tally
        payload = self._seed_copy(d)
        await self._program(d)
        if hold:
            dut.tb_output_axi_resp_hold.value = 1
        t.reset_maxima()
        t.arm_plateau()
        try:
            await self._launch(d)
            await self._wait_flag("the outstanding AR plateau", lambda: t.plateau_done)
            assert t.plateau_value <= OUTSTANDING_AR_CAP, (
                f"outstanding AR count {t.plateau_value} exceeds {OUTSTANDING_AR_CAP}"
            )
        finally:
            await FallingEdge(dut.clk_smc_i)
            dut.tb_output_axi_resp_hold.value = 0
        return payload

    async def _s3(self) -> str:
        t = self.tally
        d = _Desc("PLATEAU", S3_SRC, S3_DST, ROW_BYTES, ROWS)
        payload = await self._plateau_copy(d, hold=True)
        plateau, issued_at, ar_max = t.plateau_value, t.plateau_issued, t.ar_out_max
        aw_hold_max = t.aw_out_max
        assert ar_max <= OUTSTANDING_AR_CAP, (
            f"outstanding AR count reached {ar_max}, above {OUTSTANDING_AR_CAP}"
        )
        await self._wait_flag(
            "AR issue resuming after the release", lambda: t.ar_issued > issued_at
        )
        await self._await_done(d)
        self._compare(d, payload)
        resumed = t.ar_issued - issued_at

        resp = self._responder
        d2 = _Desc("BDELAY", S3B_SRC, S3B_DST, ROW_BYTES, ROWS)
        payload2 = self._seed_copy(d2)
        resp.set_response_delay(B_DELAY_CYCLES, read=False, write=True)
        t.reset_maxima()
        try:
            await self._program(d2)
            await self._launch(d2)
            await self._await_done(d2)
        finally:
            resp.clear_response_delay()
        aw_max = t.aw_out_max
        self._compare(d2, payload2)
        self._mark("S3")
        return (
            f"with R and B held the outstanding AR count plateaued at {plateau} (stable "
            f"{PLATEAU_RISES} rises, maximum {ar_max}, cap {OUTSTANDING_AR_CAP}; "
            f"AW maximum under the hold {aw_hold_max}); {resumed} further ARs issued after the "
            f"release and the {ROWS}-row copy completed; with B delayed {B_DELAY_CYCLES} "
            f"cycles alone the outstanding AW maximum is {aw_max} (SF-017 SF-028 open)"
        )

    async def _s4(self) -> str:
        dut = cocotb.top
        d = _Desc("LONGHOLD", S4_SRC, S4_DST, S4_LEN)
        baseline = self.next_expected_id
        payload = self._seed_copy(d)
        await self._program(d)
        statuses: list[int] = []
        dones: list[int] = []
        dut.tb_output_axi_resp_hold.value = 1
        try:
            await self._launch(d)
            rises = 0
            while rises < LONG_HOLD_RISES:
                t0 = int(get_sim_time("ps"))
                done = await self.csr_read("HOLD_DONE", DMA_CTRL_DONE_0)
                status = await self.csr_read("HOLD_STATUS", DMA_CTRL_STATUS_0)
                dones.append(done)
                statuses.append(status)
                assert done == baseline, (
                    f"DONE_0 read {done} during the hold, baseline {baseline}, new id {d.id}"
                )
                assert (status >> 9) & 1 == 0, f"STATUS_0 bit 9 set during the hold: 0x{status:x}"
                period_ps = int(round(self.cfg.smc_clk_period_ns * 1000))
                rises += max(1, (int(get_sim_time("ps")) - t0) // period_ps)
        finally:
            await FallingEdge(dut.clk_smc_i)
            dut.tb_output_axi_resp_hold.value = 0
        await self._await_done(d)
        self._compare(d, payload)
        self._mark("S4")
        return (
            f"throughout the {LONG_HOLD_RISES}-rise hold {len(dones)} DONE_0 reads equalled "
            f"the baseline {baseline} and the new id {d.id} stayed unretired; STATUS_0 reads "
            f"{sorted(set(f'0x{s:x}' for s in statuses))}; after the release DONE_0 reached {d.id}"
        )

    async def _s5(self) -> str:
        dut = cocotb.top
        t = self.tally
        d = _Desc("REALIGN", S5_SRC, S5_DST, S5_LEN)
        payload = self._seed_copy(d)
        delayer = _RBeatDelayer(dut, self.rng)
        task = cocotb.start_soon(delayer.run())
        beats0 = t.r_beats
        try:
            await self._program(d)
            await self._launch(d)
            await self._await_done(d)
        finally:
            delayer.stop = True
            await FallingEdge(dut.clk_smc_i)
            task.cancel()
            dut.tb_output_axi_resp_hold.value = 0
        beats = t.r_beats - beats0
        assert delayer.episodes >= S5_LEN // 8, (
            f"only {delayer.episodes} R-beat delays for a {S5_LEN}-byte copy"
        )
        self._compare(d, payload)
        self._mark("S5")
        return (
            f"a copy of {S5_LEN} bytes from word offset {S5_SRC & 7} to word offset "
            f"{S5_DST & 7} with {delayer.episodes} R-beat delays over {beats} R beats delivered "
            f"its exact payload with the {GUARD} bytes either side unchanged"
        )

    async def body(self) -> None:
        dut = cocotb.top
        dut.tb_output_axi_resp_hold.value = 0
        await self._s1()
        text = await self._s2()
        self._chk("S2", "CHK-DMA-BP-RANDOM", text)
        text = await self._s3()
        self._chk("S3", "CHK-DMA-BP-OUTSTANDING-CAP", text)
        text = await self._s4()
        self._chk("S4", "CHK-DMA-BP-LONG-STALL", text)
        text = await self._s5()
        self._chk("S5", "CHK-DMA-BP-REALIGN", text)
        self._nonvac()

    def _nonvac(self) -> None:
        order = ["S1", "S2", "S3", "S4", "S5"]
        assert [s for s, _ in self.steps] == order, f"step order {self.steps}"
        stamps = [ps for _, ps in self.steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        want = [
            ("S2", "CHK-DMA-BP-RANDOM"),
            ("S3", "CHK-DMA-BP-OUTSTANDING-CAP"),
            ("S4", "CHK-DMA-BP-LONG-STALL"),
            ("S5", "CHK-DMA-BP-REALIGN"),
        ]
        assert self.chk_steps == want, f"checker lines {self.chk_steps}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence checker lines in step order, step stamps strictly "
            "increasing, each line after its own compare; checker lines %s; stamps %s",
            ",".join(self.chk_ids),
            ",".join(f"{s}={ps}" for s, ps in self.steps),
        )
