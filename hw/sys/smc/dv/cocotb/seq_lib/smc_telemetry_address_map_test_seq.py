# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC telemetry receiver wrapper address map: offsets, data windows, past-extent, unbacked.

Sources: smc/doc/memmap.adoc, telemetry_receiver/doc/{memmap,interface}.adoc, smc.rdl and the
generated memory map, which gives a hole inside a receiver slot and an access past the third
slot the same response: DECERR, read data 0xBADCAB1E.
"""

from __future__ import annotations

import os
import random

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import (
    TELEMETRY_CG_EN,
    generated_hole_rresp,
    generated_past_extent_resp,
    smc_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_telemetry_atb_capture_test_seq import (
    BUFFER_DEPTH,
    BUFFER_EMPTY_BM,
    ENABLE_THRESHOLD_BM,
    RX_FLUSH_BM,
    THRESHOLD_BP,
    _HeldSource,
    _rx_addr,
    _tel,
    _word,
    pop_expect,
)

_PREFIX = "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER"
_WINDOW_BASE = smc_addr("SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_BASE_ADDR")
_STRIDE = smc_addr(f"{_PREFIX}_STRIDE")
_EXTENT = smc_addr(f"{_PREFIX}_TOTAL_SIZE")
_NUM_RX = smc_addr(f"{_PREFIX}_NUM")
_RX_SIZE = smc_addr(f"{_PREFIX}_SIZE")
_CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
_THR_BM = _tel("TELEMETRY_RECEIVER__CTRL__BUFFER_THRESHOLD_bm")

# Register types of one aperture with their generated reset values.
_REG_TYPES = (
    ("CTRL", 0x0),
    ("STATUS", BUFFER_EMPTY_BM),
    ("INTR_STATUS", 0x0),
    ("INTR_ENABLE", 0x0),
    ("INTR_TEST", 0x0),
    ("TELEMETRY_DATA", 0x0),
)
# INTR_ENABLE has one writable bit; receiver 1 takes the other value, so a receiver 1 window
# aliased onto 0 or 2 fails its readback. The drawn thresholds tell all three apart.
_INTR_ENABLE_PATTERNS = (ENABLE_THRESHOLD_BM, 0x0, ENABLE_THRESHOLD_BM)

# Offsets named by steps S4 to S6.
_PAST_EXTENT_OFFSETS = (_EXTENT, _EXTENT + 0x4, _EXTENT + 0x80, 0xFFC)
_FOURTH_WRITE_OFFSET = _EXTENT + 0xC
_FOURTH_READ_OFFSET = _EXTENT + 0x4
_UNBACKED_PROBES = tuple(
    (rx, off) for rx in range(_NUM_RX) for off in (_RX_SIZE, 0x1C, 0x20, 0x7C, 0xFC)
)
_UNBACKED_WRITE = 0x11
_FOURTH_WRITE = 0x11
_UNIT = "smc_telemetry_receiver_wrap"
assert generated_hole_rresp(_UNIT) == {"DECERR"}, "the generated map changed the hole response"
assert generated_past_extent_resp(_UNIT) == ("DECERR", "DECERR"), "past-extent response changed"
_DECERR = 3
_ERR_DATA = SmcCsrSeq.ERR_SLAVE_SIGNATURE

_FUSE_SENSE_MAX_CYCLES = 200_000
_BUFFER_POLL_BOUND = 200
_FLUSH_POLL_BOUND = 64
_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6")
_FENCE = (
    "SETUP_DONE",
    "OFFSETS_AND_PATTERNS",
    "DATA_WINDOWS",
    "PAST_EXTENT_DECERR",
    "UNBACKED_DECERR",
    "NO_FOURTH_RECEIVER",
)
_CHK_ORDER = (
    ("CHK-TELEMETRY-APERTURE-REGS", "S2"),
    ("CHK-TELEMETRY-DATA-WINDOW", "S3"),
    ("CHK-TELEMETRY-PAST-EXTENT", "S4"),
    ("CHK-TELEMETRY-UNBACKED-OFFSETS", "S5"),
    ("CHK-TELEMETRY-NO-FOURTH-RECEIVER", "S6"),
)


class smc_telemetry_address_map_test_seq(SmcCsrSeq):
    def __init__(self, name: str = "smc_telemetry_address_map_test_seq") -> None:
        super().__init__(name)
        self.seed = int(os.environ.get("RANDOM_SEED", "1"), 0)
        self.stamps: dict[str, int] = {}
        self.chk_after: list[tuple[str, str]] = []
        self.waits: list[tuple[str, str, str]] = []

    def _stamp(self, step: str) -> None:
        self.stamps[step] = int(get_sim_time("ps"))

    def _chk(self, chk_id: str, step: str, text: str, *args) -> None:
        assert step in self.stamps, f"{chk_id} printed before {step} completed"
        self.chk_after.append((chk_id, step))
        cocotb.log.info(f"{chk_id}: {text}", *args)

    async def _measure(self, name: str, addr: int, write: int | None = None) -> tuple[int, int]:
        """One tolerated-response access: returns (resp_code, rdata)."""
        item = SmcSysAxiItem(f"{'wr' if write is not None else 'rd'}_{name}")
        item.op = SmcSysAxiOp.READ if write is None else SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 4
        item.wdata = 0 if write is None else write
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None and not item.timed_out, f"{name}: no response"
        return item.resp_code, item.rdata

    async def _expect_decerr(self, name: str, addr: int, write: int) -> tuple[int, int, int]:
        """Read and write `addr`; both must answer DECERR and the read 0xBADCAB1E."""
        rresp, rdata = await self._measure(f"{name}_RD", addr)
        wresp = (await self._measure(f"{name}_WR", addr, write))[0]
        assert (rresp, rdata, wresp) == (_DECERR, _ERR_DATA, _DECERR), (
            f"{name} @ 0x{addr:08x}: read resp {rresp} data 0x{rdata:08x}, write resp {wresp}; "
            f"the generated map gives DECERR, 0x{_ERR_DATA:08x} / DECERR"
        )
        return rresp, rdata, wresp

    async def _wait_empty(self, rx: int, empty: bool, label: str) -> int:
        status = 0
        for polls in range(1, _BUFFER_POLL_BOUND + 1):
            status = await self.csr_read(f"TLM{rx}_STATUS_{label}", _rx_addr("STATUS", rx))
            if bool(status & BUFFER_EMPTY_BM) == empty:
                return polls
            await ClockCycles(cocotb.top.clk_smc_i, 1)
        raise AssertionError(
            f"receiver {rx} STATUS.BUFFER_EMPTY never reached {int(empty)} over "
            f"{_BUFFER_POLL_BOUND} polls ({label}); last STATUS=0x{status:08x}"
        )

    async def _snapshot(self, label: str) -> dict[tuple[int, str], int]:
        snap = {}
        for rx in range(_NUM_RX):
            for reg in ("STATUS", "INTR_ENABLE", "INTR_STATUS", "CTRL"):
                snap[(rx, reg)] = await self.csr_read(f"{label}_{rx}_{reg}", _rx_addr(reg, rx))
        return snap

    async def body(self) -> None:
        dut = cocotb.top
        assert _NUM_RX == 3, f"generated receiver count {_NUM_RX}, the test covers 0 to 2"
        for rx in range(_NUM_RX):
            assert hasattr(dut, f"tb_telemetry{rx}_atvalid"), f"tb_telemetry{rx}_* ports missing"

        rng = random.Random(self.seed)
        counts = [rng.randint(1, BUFFER_DEPTH) for _ in range(_NUM_RX)]
        order = list(range(_NUM_RX))
        rng.shuffle(order)
        thresholds = rng.sample(range(1, (_THR_BM >> THRESHOLD_BP) + 1), _NUM_RX)
        # One beat per (ATID, data) pair drawn without repeats across all receivers, so a beat
        # read back in any aperture names the receiver and the position it was sent to.
        pairs = rng.sample(range(1 << 15), sum(counts))
        beats = []
        for rx in range(_NUM_RX):
            taken, pairs = pairs[: counts[rx]], pairs[counts[rx] :]
            beats.append([(p >> 8, p & 0xFF) for p in taken])
        drawn = f"seed {self.seed} counts {counts} order {order} thresholds " + ",".join(
            f"0x{t:03x}" for t in thresholds
        )
        cocotb.log.info("RAND-SEED: %d; RAND-DRAW: %s", self.seed, drawn)

        # S1
        await self.wait_fuse_sense_done(_FUSE_SENSE_MAX_CYCLES)
        self.waits.append(
            ("fuse_sense_done", f"{_FUSE_SENSE_MAX_CYCLES} smc cycles", "tb_fuse_sense_done=1")
        )
        cg = await self.csr_read("CLOCK_GATE_CONTROL_SAVE", _CLOCK_GATE_CONTROL)
        ungated = cg & ~TELEMETRY_CG_EN
        await self.csr_write("CLOCK_GATE_CONTROL_TEL_ON", _CLOCK_GATE_CONTROL, ungated)
        await self.csr_read("CLOCK_GATE_CONTROL_TEL_ON_RB", _CLOCK_GATE_CONTROL, expected=ungated)
        for rx in range(_NUM_RX):
            await self.csr_write(f"TLM{rx}_RX_FLUSH", _rx_addr("CTRL", rx), RX_FLUSH_BM)
            polls = await self._wait_empty(rx, True, "FLUSH")
            assert polls <= _FLUSH_POLL_BOUND
        self.waits.append(
            ("rx_flush_empty_poll", f"{_BUFFER_POLL_BOUND} polls", "STATUS.BUFFER_EMPTY=1")
        )
        self._stamp("S1")

        # S2
        for rx in range(_NUM_RX):
            for reg, reset in _REG_TYPES:
                got = await self.csr_read(f"TLM{rx}_{reg}", _rx_addr(reg, rx), expected=reset)
                assert got == reset, f"receiver {rx} {reg} read 0x{got:08x}, reset 0x{reset:08x}"
        for rx in range(_NUM_RX):
            await self.csr_write(
                f"TLM{rx}_IE_WR", _rx_addr("INTR_ENABLE", rx), _INTR_ENABLE_PATTERNS[rx]
            )
            await self.csr_write(
                f"TLM{rx}_THR_WR", _rx_addr("CTRL", rx), thresholds[rx] << THRESHOLD_BP
            )
        for rx in range(_NUM_RX):
            ie = await self.csr_read(
                f"TLM{rx}_IE_RB", _rx_addr("INTR_ENABLE", rx), expected=_INTR_ENABLE_PATTERNS[rx]
            )
            ctrl = await self.csr_read(f"TLM{rx}_THR_RB", _rx_addr("CTRL", rx))
            thr = (ctrl & _THR_BM) >> THRESHOLD_BP
            assert ie == _INTR_ENABLE_PATTERNS[rx], f"receiver {rx} INTR_ENABLE 0x{ie:x}"
            assert thr == thresholds[rx], (
                f"receiver {rx} BUFFER_THRESHOLD read 0x{thr:x}, wrote "
                f"0x{thresholds[rx]:x} (CTRL=0x{ctrl:08x})"
            )
        for rx in range(_NUM_RX):
            await self.csr_write(f"TLM{rx}_IE_RESTORE", _rx_addr("INTR_ENABLE", rx), 0)
            await self.csr_write(f"TLM{rx}_THR_RESTORE", _rx_addr("CTRL", rx), 0)
        for rx in range(_NUM_RX):
            await self.csr_read(f"TLM{rx}_IE_RESTORE_RB", _rx_addr("INTR_ENABLE", rx), expected=0)
            await self.csr_read(f"TLM{rx}_THR_RESTORE_RB", _rx_addr("CTRL", rx), expected=0)
        self._stamp("S2")
        self._chk(
            "CHK-TELEMETRY-APERTURE-REGS",
            "S2",
            "%d register types x %d apertures read OKAY at window base + 0x%x * i + 0x00 to 0x%x "
            "with reset values; INTR_ENABLE %s and the drawn BUFFER_THRESHOLD %s written to "
            "receivers 0 to 2 read back as their own and restored to 0; zero reset values are "
            "bench-limited (2-state zero init); drawn=%s",
            len(_REG_TYPES),
            _NUM_RX,
            _STRIDE,
            _RX_SIZE - 4,
            ",".join(f"0x{p:02x}" for p in _INTR_ENABLE_PATTERNS),
            ",".join(f"0x{p:03x}" for p in thresholds),
            drawn,
        )

        # S3: each receiver in the drawn order takes its drawn number of beats, and every beat
        # is read back in that receiver's aperture while the other two read empty.
        windows: dict[int, str] = {}
        for rx in order:
            await _HeldSource(dut, beats[rx], rx=rx).task
            for index, beat in enumerate(beats[rx]):
                await pop_expect(self, f"TLM{rx}_BEAT{index}", beat, rx)
            for other in range(_NUM_RX):
                await self.csr_read(
                    f"TLM{other}_DATA_AFTER_RX{rx}", _rx_addr("TELEMETRY_DATA", other), expected=0
                )
            await self._wait_empty(rx, True, "DRAINED")
            windows[rx] = f"rx{rx}: {counts[rx]} beats, last 0x{_word(beats[rx][-1]):08x}"
        self.waits.append(
            ("buffer_status_poll", f"{_BUFFER_POLL_BOUND} polls", "STATUS.BUFFER_EMPTY")
        )
        self.waits.append(("data_read", "200 reads", "TELEMETRY_DATA valid"))
        self._stamp("S3")
        for rx in order:
            self._chk(
                "CHK-TELEMETRY-DATA-WINDOW",
                "S3",
                "%s: each read back in order through TELEMETRY_DATA at offset 0x%x of receiver "
                "%d, after which TELEMETRY_DATA of receivers 0..%d read 0 and BUFFER_EMPTY 1; "
                "drawn=%s",
                windows[rx],
                _rx_addr("TELEMETRY_DATA", 0) - _WINDOW_BASE,
                rx,
                _NUM_RX - 1,
                drawn,
            )

        # S4
        self.env.axi_monitor.expected_decerr_addrs.update(
            [_WINDOW_BASE + off for off in (*_PAST_EXTENT_OFFSETS, _FOURTH_WRITE_OFFSET)]
            + [_WINDOW_BASE + rx * _STRIDE + off for rx, off in _UNBACKED_PROBES]
        )
        before = await self._snapshot("PE_PRE")
        for off in _PAST_EXTENT_OFFSETS:
            await self._expect_decerr(f"PE_{off:x}", _WINDOW_BASE + off, _FOURTH_WRITE)
        after = await self._snapshot("PE_POST")
        assert after == before, f"past-extent accesses changed receiver registers: {after}"
        self._stamp("S4")
        self._chk(
            "CHK-TELEMETRY-PAST-EXTENT",
            "S4",
            "reads and writes at window offsets %s answered DECERR, the reads with 0x%08x, and "
            "STATUS/INTR_ENABLE/INTR_STATUS/CTRL of receivers 0..%d read unchanged",
            ", ".join(f"0x{o:x}" for o in _PAST_EXTENT_OFFSETS),
            _ERR_DATA,
            _NUM_RX - 1,
        )

        # S5
        for rx, off in _UNBACKED_PROBES:
            await self._expect_decerr(
                f"UB_{rx}_{off:x}", _WINDOW_BASE + rx * _STRIDE + off, _UNBACKED_WRITE
            )
        after = await self._snapshot("UB_POST")
        assert after == before, f"unbacked accesses changed receiver registers: {before} -> {after}"
        self._stamp("S5")
        self._chk(
            "CHK-TELEMETRY-UNBACKED-OFFSETS",
            "S5",
            "reads and writes of 0x%x at slot offsets %s of receivers 0..%d answered DECERR, the "
            "reads with 0x%08x, and STATUS/INTR_ENABLE/INTR_STATUS/CTRL of every receiver read "
            "unchanged",
            _UNBACKED_WRITE,
            ", ".join(f"0x{o:x}" for o in sorted({o for _, o in _UNBACKED_PROBES})),
            _NUM_RX - 1,
            _ERR_DATA,
        )

        # S6
        wresp = (await self._measure("NF_WR", _WINDOW_BASE + _FOURTH_WRITE_OFFSET, _FOURTH_WRITE))[
            0
        ]
        rresp, rdata = await self._measure("NF_RD", _WINDOW_BASE + _FOURTH_READ_OFFSET)
        assert (rresp, rdata, wresp) == (_DECERR, _ERR_DATA, _DECERR), (
            f"fourth-aperture read resp {rresp} data 0x{rdata:08x}, write resp {wresp}; expected "
            f"the past-extent DECERR, 0x{_ERR_DATA:08x} / DECERR"
        )
        final = await self._snapshot("NF_POST")
        assert final == before, f"fourth-aperture access changed receiver registers: {final}"
        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", _CLOCK_GATE_CONTROL, cg)
        await self.csr_read("CLOCK_GATE_CONTROL_RESTORE_RB", _CLOCK_GATE_CONTROL, expected=cg)
        self._stamp("S6")
        self._chk(
            "CHK-TELEMETRY-NO-FOURTH-RECEIVER",
            "S6",
            "write 0x%x at +0x%x answered resp=%d and read at +0x%x answered resp=%d rdata=0x%08x, "
            "the past-extent DECERR responses; INTR_ENABLE and STATUS of receivers 0 to 2 "
            "unchanged (%s)",
            _FOURTH_WRITE,
            _FOURTH_WRITE_OFFSET,
            wresp,
            _FOURTH_READ_OFFSET,
            rresp,
            rdata,
            ",".join(
                f"rx{r}:IE=0x{final[(r, 'INTR_ENABLE')]:x}/STATUS=0x{final[(r, 'STATUS')]:08x}"
                for r in range(_NUM_RX)
            ),
        )

        axi_bound = self.cfg.axi_timeout_ns
        bounds = [f"sep_in_axi_access={axi_bound}ns last=response received"]
        bounds += [f"{n}={b} last={s}" for n, b, s in self.waits]
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s; expiry raises AssertionError with the "
            "last observed state",
            len(bounds),
            "; ".join(bounds),
        )
        self._fence()

    def _fence(self) -> None:
        assert tuple(self.stamps) == _STEPS, f"step stamps {list(self.stamps)} not in order"
        times = [self.stamps[s] for s in _STEPS]
        assert all(a < b for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        order = [chk for chk, _ in self.chk_after]
        expect = [chk for chk, _ in _CHK_ORDER]
        dedup = [c for i, c in enumerate(order) if i == 0 or order[i - 1] != c]
        assert dedup == expect, f"checker lines {dedup} not in expected order {expect}"
        for chk, step in self.chk_after:
            assert dict(_CHK_ORDER)[chk] == step, f"{chk} printed after wrong step {step}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(_FENCE),
            ",".join(dedup),
            ",".join(f"{s}={self.stamps[s]}ps" for s in _STEPS),
        )
