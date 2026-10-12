# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC_POWER_TELEMETRY_017 / smc_telemetry_address_map_test.

Scenarios TLM-ADDRESS-MAP.S1 to S5: receiver offsets, counter window, past-extent, unbacked.
Sources: smc/doc/memmap.adoc, telemetry_receiver/doc/{memmap,interface}.adoc, smc.rdl.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import (
    _REPO,
    TELEMETRY_CG_EN,
    _field_mask,
    _parse_indexed_bases,
    smc_addr,
    smc_indexed_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq

_TELEMETRY_H = (
    _REPO / "hw" / "ip" / "telemetry_receiver" / "regs" / "gen" / "c" / "telemetry_receiver.h"
)
_TELEMETRY_ADDR_H = (
    _REPO / "hw" / "ip" / "telemetry_receiver" / "regs" / "gen" / "c" / "telemetry_receiver_addr.h"
)
_PREFIX = "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER"


def _tel(symbol: str) -> int:
    return _field_mask(_TELEMETRY_H, symbol)


def _reg(register: str, rx: int) -> int:
    return smc_indexed_addr(f"{_PREFIX}_{register}_BASE_ADDR", rx)


_WINDOW_BASE = smc_addr("SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_BASE_ADDR")
_STRIDE = smc_addr(f"{_PREFIX}_STRIDE")
_EXTENT = smc_addr(f"{_PREFIX}_TOTAL_SIZE")
_NUM_RX = smc_addr(f"{_PREFIX}_NUM")
_COUNTER_BASE, _COUNTER_STRIDE = _parse_indexed_bases(_TELEMETRY_ADDR_H)[
    "TELEMETRY_RECEIVER_TELEMETRY_COUNTER_BASE_ADDR"
]
_NUM_COUNTERS = smc_addr(f"{_PREFIX}_TELEMETRY_COUNTER_NUM")
_CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

_BUFFER_POP = _tel("TELEMETRY_RECEIVER__CTRL__BUFFER_POP_bm")
_RX_FLUSH = _tel("TELEMETRY_RECEIVER__CTRL__TELEMETRY_RX_FLUSH_bm")
_THR_BM = _tel("TELEMETRY_RECEIVER__CTRL__BUFFER_THRESHOLD_bm")
_THR_BP = _tel("TELEMETRY_RECEIVER__CTRL__BUFFER_THRESHOLD_bp")
_EMPTY_BM = _tel("TELEMETRY_RECEIVER__STATUS__BUFFER_EMPTY_bm")

# Register types of one aperture with their generated reset values.
_REG_TYPES = (
    ("CTRL", 0x0),
    ("STATUS", _EMPTY_BM),
    ("INTR_STATUS", 0x0),
    ("INTR_ENABLE", 0x0),
    ("INTR_TEST", 0x0),
    ("TELEMETRY_PROBE_ID", 0x0),
    ("TELEMETRY_COUNTER_VLDS", 0x0),
)
_INTR_ENABLE_PATTERNS = (0x01, 0x10, 0x11)
_THRESHOLD_PATTERNS = (0x111, 0x222, 0x333)

# Offsets named by the contract steps S4 to S6.
_PAST_EXTENT_OFFSETS = (_EXTENT, _EXTENT + 0x4, _EXTENT + 0x80, 0xFFC)
_FOURTH_WRITE_OFFSET = _EXTENT + 0xC
_FOURTH_READ_OFFSET = _EXTENT + 0x4
_UNBACKED_PROBES = ((0, 0x1C), (0, 0x20), (0, 0x7C), (2, 0x1C))
_UNBACKED_WRITE = 0x11
_FOURTH_WRITE = 0x11

# ATB framing: 8-bit beats, 64-bit packet, 9-bit blocks (telemetry_receiver/doc/interface.adoc,
# architecture.adoc); header bit positions are DV-owned.
_BEAT_BITS = 8
_BEATS_PER_PACKET = 64 // _BEAT_BITS
_BLOCK_BITS = 9
_PROBE_ID_LSB = 56
_PROBE_ID_BITS = 5
_LAST_PACKET_BIT = 63
_NEXT_BLOCK_LSB = 54
_PROBE_IDS = (0x05, 0x0A, 0x13)
_ATIDS = (0x00, 0x11, 0x22)

_FUSE_SENSE_MAX_CYCLES = 200_000
_ATB_READY_BOUND = 64
_BUFFER_POLL_BOUND = 200
_FLUSH_POLL_BOUND = 64
_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6")
_FENCE = (
    "SETUP_DONE",
    "OFFSETS_AND_PATTERNS",
    "COUNTER_WINDOWS",
    "PAST_EXTENT_MEASURED",
    "UNBACKED_MEASURED",
    "NO_FOURTH_RECEIVER",
)
_CHK_ORDER = (
    ("CHK-TELEMETRY-APERTURE-REGS", "S2"),
    ("CHK-TELEMETRY-COUNTER-WINDOW", "S3"),
    ("CHK-TELEMETRY-PAST-EXTENT", "S4"),
    ("CHK-TELEMETRY-UNBACKED-OFFSETS", "S5"),
    ("CHK-TELEMETRY-NO-FOURTH-RECEIVER", "S6"),
)


def _counter_addr(rx: int, index: int) -> int:
    return _WINDOW_BASE + rx * _STRIDE + _COUNTER_BASE + index * _COUNTER_STRIDE


def _all_valid_packet(probe_id: int) -> int:
    packet = 1 << _LAST_PACKET_BIT
    packet |= (probe_id & ((1 << _PROBE_ID_BITS) - 1)) << _PROBE_ID_LSB
    for block_lsb in range(0, _NEXT_BLOCK_LSB, _BLOCK_BITS):
        packet |= ((1 << _BLOCK_BITS) - 1) << block_lsb
    return packet


class smc_telemetry_address_map_test_seq(SmcCsrSeq):
    def __init__(self, name: str = "smc_telemetry_address_map_test_seq") -> None:
        super().__init__(name)
        self.stamps: dict[str, int] = {}
        self.chk_after: list[tuple[str, str]] = []
        self.waits: list[tuple[str, str, str]] = []
        self.past_extent: dict[int, tuple[int, int, int]] = {}

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

    async def _send_packet(self, rx: int, packet: int) -> None:
        dut = cocotb.top
        atdata = getattr(dut, f"tb_telemetry{rx}_atdata")
        atid = getattr(dut, f"tb_telemetry{rx}_atid")
        atvalid = getattr(dut, f"tb_telemetry{rx}_atvalid")
        atready = getattr(dut, f"tb_telemetry{rx}_atready")
        for beat in range(_BEATS_PER_PACKET):
            atdata.value = (packet >> (beat * _BEAT_BITS)) & 0xFF
            atid.value = _ATIDS[rx]
            atvalid.value = 1
            await RisingEdge(dut.clk_smc_i)
            accepted = False
            for _ in range(_ATB_READY_BOUND):
                raw = atready.value
                assert raw.is_resolvable, f"tb_telemetry{rx}_atready is X/Z: {raw}"
                if int(raw):
                    accepted = True
                    break
                await RisingEdge(dut.clk_smc_i)
            atvalid.value = 0
            assert accepted, (
                f"ATB beat {beat} into receiver {rx} never accepted: "
                f"tb_telemetry{rx}_atready low for {_ATB_READY_BOUND} clk_smc_i cycles"
            )

    async def _wait_empty(self, rx: int, empty: bool, label: str) -> int:
        status = 0
        for polls in range(1, _BUFFER_POLL_BOUND + 1):
            status = await self.csr_read(f"TLM{rx}_STATUS_{label}", _reg("STATUS", rx))
            if bool(status & _EMPTY_BM) == empty:
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
                snap[(rx, reg)] = await self.csr_read(f"{label}_{rx}_{reg}", _reg(reg, rx))
        return snap

    async def body(self) -> None:
        dut = cocotb.top
        assert _NUM_RX == 3, f"generated receiver count {_NUM_RX}, contract covers 0 to 2"
        for rx in range(_NUM_RX):
            assert hasattr(dut, f"tb_telemetry{rx}_atvalid"), f"tb_telemetry{rx}_* ports missing"

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
            await self.csr_write(f"TLM{rx}_RX_FLUSH", _reg("CTRL", rx), _RX_FLUSH)
            polls = await self._wait_empty(rx, True, "FLUSH")
            assert polls <= _FLUSH_POLL_BOUND
        self.waits.append(
            ("rx_flush_empty_poll", f"{_BUFFER_POLL_BOUND} polls", "STATUS.BUFFER_EMPTY=1")
        )
        self._stamp("S1")

        # S2
        for rx in range(_NUM_RX):
            for reg, reset in _REG_TYPES:
                got = await self.csr_read(f"TLM{rx}_{reg}", _reg(reg, rx), expected=reset)
                assert got == reset, f"receiver {rx} {reg} read 0x{got:08x}, reset 0x{reset:08x}"
        for rx in range(_NUM_RX):
            await self.csr_write(
                f"TLM{rx}_IE_WR", _reg("INTR_ENABLE", rx), _INTR_ENABLE_PATTERNS[rx]
            )
            await self.csr_write(
                f"TLM{rx}_THR_WR", _reg("CTRL", rx), _THRESHOLD_PATTERNS[rx] << _THR_BP
            )
        for rx in range(_NUM_RX):
            ie = await self.csr_read(
                f"TLM{rx}_IE_RB", _reg("INTR_ENABLE", rx), expected=_INTR_ENABLE_PATTERNS[rx]
            )
            ctrl = await self.csr_read(f"TLM{rx}_THR_RB", _reg("CTRL", rx))
            thr = (ctrl & _THR_BM) >> _THR_BP
            assert ie == _INTR_ENABLE_PATTERNS[rx], f"receiver {rx} INTR_ENABLE 0x{ie:x}"
            assert thr == _THRESHOLD_PATTERNS[rx], (
                f"receiver {rx} BUFFER_THRESHOLD read 0x{thr:x}, wrote "
                f"0x{_THRESHOLD_PATTERNS[rx]:x} (CTRL=0x{ctrl:08x})"
            )
        for rx in range(_NUM_RX):
            await self.csr_write(f"TLM{rx}_IE_RESTORE", _reg("INTR_ENABLE", rx), 0)
            await self.csr_write(f"TLM{rx}_THR_RESTORE", _reg("CTRL", rx), 0)
        for rx in range(_NUM_RX):
            await self.csr_read(f"TLM{rx}_IE_RESTORE_RB", _reg("INTR_ENABLE", rx), expected=0)
            await self.csr_read(f"TLM{rx}_THR_RESTORE_RB", _reg("CTRL", rx), expected=0)
        self._stamp("S2")
        self._chk(
            "CHK-TELEMETRY-APERTURE-REGS",
            "S2",
            "%d register types x %d apertures read OKAY at window base + 0x%x * i + 0x00 to 0x18 "
            "with reset values; INTR_ENABLE %s and BUFFER_THRESHOLD %s written to receivers 0 to 2 "
            "read back as their own and restored to 0",
            len(_REG_TYPES),
            _NUM_RX,
            _STRIDE,
            ",".join(f"0x{p:02x}" for p in _INTR_ENABLE_PATTERNS),
            ",".join(f"0x{p:03x}" for p in _THRESHOLD_PATTERNS),
        )

        # S3
        windows = []
        for rx in range(_NUM_RX):
            await self._send_packet(rx, _all_valid_packet(_PROBE_IDS[rx]))
            await self._wait_empty(rx, False, "MSG")
            vals = []
            for other in range(_NUM_RX):
                c0 = await self.csr_read(f"TLM{other}_C0_MSG{rx}", _counter_addr(other, 0))
                c1 = await self.csr_read(f"TLM{other}_C1_MSG{rx}", _counter_addr(other, 1))
                want = (0xFFFFFFFF, 0x0) if other == rx else (0x0, 0x0)
                assert (c0, c1) == want, (
                    f"message in receiver {rx}: receiver {other} COUNTER[0]=0x{c0:08x} "
                    f"COUNTER[1]=0x{c1:08x}, expected 0x{want[0]:08x} 0x{want[1]:08x}"
                )
                vals.append((c0, c1))
            if rx == 1:
                for idx in range(_NUM_COUNTERS):
                    await self.csr_read(f"TLM1_COUNTER_{idx}", _counter_addr(1, idx))
            await self.csr_write(f"TLM{rx}_POP", _reg("CTRL", rx), _BUFFER_POP)
            await self._wait_empty(rx, True, "POP")
            windows.append(vals)
        self.waits.append(
            ("buffer_status_poll", f"{_BUFFER_POLL_BOUND} polls", "STATUS.BUFFER_EMPTY")
        )
        self.waits.append(("atb_beat_accept", f"{_ATB_READY_BOUND} cycles", "atready=1"))
        self._stamp("S3")
        for rx in range(_NUM_RX):
            self._chk(
                "CHK-TELEMETRY-COUNTER-WINDOW",
                "S3",
                "message in receiver %d: COUNTER[0]/[1] at offsets 0x%x/0x%x of receivers 0..2 "
                "read %s; all %d counters of receiver 1 answered OKAY in 4-byte steps",
                rx,
                _COUNTER_BASE,
                _COUNTER_BASE + _COUNTER_STRIDE,
                " ".join(f"(0x{a:08x},0x{b:08x})" for a, b in windows[rx]),
                _NUM_COUNTERS,
            )

        # S4
        before = await self._snapshot("PE_PRE")
        receiver_status = before[(0, "STATUS")]
        measured = []
        for off in _PAST_EXTENT_OFFSETS:
            addr = _WINDOW_BASE + off
            rresp, rdata = await self._measure(f"PE_RD_{off:x}", addr)
            wresp = (await self._measure(f"PE_WR_{off:x}", addr, _FOURTH_WRITE))[0]
            assert not (rresp <= 1 and rdata == receiver_status), (
                f"past-extent read at +0x{off:x} answered OKAY with receiver STATUS-like data "
                f"0x{rdata:08x}"
            )
            self.past_extent[off] = (rresp, rdata, wresp)
            measured.append(f"+0x{off:x}:rresp={rresp},rdata=0x{rdata:08x},wresp={wresp}")
        self._stamp("S4")
        self._chk(
            "CHK-TELEMETRY-PAST-EXTENT",
            "S4",
            "measured, not compared (SF-009): %s",
            " ".join(measured),
        )

        # S5
        measured = []
        for rx, off in _UNBACKED_PROBES:
            addr = _WINDOW_BASE + rx * _STRIDE + off
            rresp, rdata = await self._measure(f"UB_RD_{rx}_{off:x}", addr)
            wresp = (await self._measure(f"UB_WR_{rx}_{off:x}", addr, _UNBACKED_WRITE))[0]
            measured.append(f"rx{rx}+0x{off:x}:rresp={rresp},rdata=0x{rdata:08x},wresp={wresp}")
        after = await self._snapshot("UB_POST")
        assert after == before, f"unbacked accesses changed receiver registers: {before} -> {after}"
        self._stamp("S5")
        self._chk(
            "CHK-TELEMETRY-UNBACKED-OFFSETS",
            "S5",
            "measured, not compared (SF-008); receiver STATUS/INTR_ENABLE/INTR_STATUS/CTRL "
            "unchanged: %s",
            " ".join(measured),
        )

        # S6
        wresp = (await self._measure("NF_WR", _WINDOW_BASE + _FOURTH_WRITE_OFFSET, _FOURTH_WRITE))[
            0
        ]
        rresp, rdata = await self._measure("NF_RD", _WINDOW_BASE + _FOURTH_READ_OFFSET)
        pe_rresp, pe_rdata, pe_wresp = self.past_extent[_FOURTH_READ_OFFSET]
        assert rresp == pe_rresp, (
            f"fourth-aperture read resp {rresp} differs from past-extent read resp {pe_rresp}"
        )
        assert wresp == pe_wresp, (
            f"fourth-aperture write resp {wresp} differs from past-extent write resp {pe_wresp}"
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
            "equal to the past-extent responses (wresp=%d rresp=%d); INTR_ENABLE and STATUS of "
            "receivers 0 to 2 unchanged (%s)",
            _FOURTH_WRITE,
            _FOURTH_WRITE_OFFSET,
            wresp,
            _FOURTH_READ_OFFSET,
            rresp,
            rdata,
            pe_wresp,
            pe_rresp,
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
        assert dedup == expect, f"checker lines {dedup} not in contract order {expect}"
        for chk, step in self.chk_after:
            assert dict(_CHK_ORDER)[chk] == step, f"{chk} printed after wrong step {step}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(_FENCE),
            ",".join(dedup),
            ",".join(f"{s}={self.stamps[s]}ps" for s in _STEPS),
        )
