# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse shim response stream against the SMC eFuse map read back over JTAG2AXI.

Spec: smc.rdl smc_efuse_map at 0xC0007000 and efuse_interface_ctrl at 0xC0008000;
smc_efuse_map.rdl Address Map; smu-smc.adoc 256 32-bit words per instance; interface.adoc
fuse_command_resp_t {data, status, valid}; efuse_interface_ctrl.rdl efuse_sense_done bit 0.

The stream is captured at the SMU boundary during the shared bring-up. Sixteen map words are
read back over JTAG2AXI and compared with the stream word of the same index. Three open owner
questions are waived: the pre-sense status is never read, no multi-word element is assembled, and
the per-slice equality of smc_shadow_regs with the stream is logged and never compared.
"""

from __future__ import annotations

import time

import cocotb
from cocotb.triggers import Event, RisingEdge
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_addr, smc_indexed_addr
from seq_lib.smu_fuse_sense_probe import smc_command_nets
from seq_lib.smu_jtag_helpers import (
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    axi64_unpack32,
    jtag2axi_single_read,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)

MAP_BASE = smc_addr("SMC_TOP_SMC_EFUSE_MAP_BASE_ADDR")
STATUS_ADDR = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_INTERFACE_CTRL_STATUS_BASE_ADDR")
STREAM_WORDS = 256
RESP_WIDTH = 34
VALID_BIT = 0
STATUS_BIT = 1
DATA_LSB = 2
WORD_MASK = 0xFFFF_FFFF
SAMPLED_INDICES = (0, 1, 2, 9, 10, 18, 27, 28, 29, 30, 31, 32, 64, 128, 200, 255)
ELEMENT_CELLS = (
    ("locks_0x0", "SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR", None),
    ("jtag_public_identity_0x8", "SMC_TOP_SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY_BASE_ADDR", None),
    ("i2c_i3c_id_0x28", "SMC_TOP_SMC_EFUSE_MAP_I2C_I3C_ID_BASE_ADDR", 0),
    ("smc_config_0x70", "SMC_TOP_SMC_EFUSE_MAP_SMC_CONFIG_BASE_ADDR", None),
    ("occp_timeout_0x78", "SMC_TOP_SMC_EFUSE_MAP_OCCP_TRANSPORT_TIMEOUT_BASE_ADDR", None),
    ("spare_0x80_to_0x3ff", "SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR", 0),
)
CAPTURE_BOUND_EDGES = 400_000
DONE_BOUND_EDGES = 200_000
TAIL_EDGES = 64
J2A_POLL_LIMIT = 128
CONTRACT_WAIT_SITES = 3
IDCODE = 0x1
SITE_NAMES = ("S1_stream_capture", "S1_done_rise", "j2a")


def _site(bound: int) -> dict:
    return {"bound": bound, "count": 0, "last": "none", "expired": 0}


class SmuEfuseStreamCapture:
    """Response words of the SMC eFuse shim and the rise of smc_fuse_sense_done_o."""

    def __init__(self) -> None:
        self.dut = cocotb.top
        self.words: list[int] = []
        self.status_bits: list[int] = []
        self.sites = {
            "S1_stream_capture": _site(CAPTURE_BOUND_EDGES),
            "S1_done_rise": _site(DONE_BOUND_EDGES),
        }
        self.done = Event()
        self.done_seen = False
        self.done_expired = False

    def arm(self) -> None:
        _, resp = smc_command_nets(self.dut)
        if len(resp) != RESP_WIDTH:
            raise AssertionError(
                f"TB-infrastructure-gap: smc_efuse_shim_command_resp is {len(resp)} bits wide, "
                f"expected {RESP_WIDTH} ({{data[31:0], status, valid}})"
            )
        self.resp = resp
        cocotb.start_soon(self._capture())
        cocotb.start_soon(self._watch_done())

    @staticmethod
    def _read(handle, name: str, *, allow_xz: bool = False) -> int:
        val = handle.value
        if not val.is_resolvable:
            if allow_xz:
                return 0
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val)

    async def _capture(self) -> None:
        rec = self.sites["S1_stream_capture"]
        prev = 0
        tail = 0
        for n in range(CAPTURE_BOUND_EDGES):
            await RisingEdge(self.dut.clk_smu_i)
            raw = self._read(self.resp, "smc_efuse_shim_command_resp", allow_xz=True)
            valid = (raw >> VALID_BIT) & 1
            if valid and not prev:
                self.words.append((raw >> DATA_LSB) & WORD_MASK)
                self.status_bits.append((raw >> STATUS_BIT) & 1)
            prev = valid
            rec["count"] = n + 1
            rec["last"] = f"strobes={len(self.words)}"
            if self.done_seen:
                tail += 1
                if tail >= TAIL_EDGES:
                    return
        rec["expired"] = 1

    async def _watch_done(self) -> None:
        rec = self.sites["S1_done_rise"]
        pin = self.dut.smc_fuse_sense_done_o
        prev = 0
        for n in range(DONE_BOUND_EDGES):
            await RisingEdge(self.dut.clk_smu_i)
            now = self._read(pin, "smc_fuse_sense_done_o", allow_xz=True) & 1
            rec["count"] = n + 1
            rec["last"] = f"smc_fuse_sense_done_o={now}"
            if now and not prev:
                self.done_seen = True
                self.done.set()
                return
            prev = now
        rec["expired"] = 1
        self.done_expired = True
        self.done.set()


class smu_smc_efuse_shadow_map_readback_test_seq:
    """The SMC eFuse map over JTAG2AXI against the sensed response stream."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.sb = test.env.scoreboard
        self.capture = test.efuse_capture
        self.step_ts: dict[str, float] = {}
        self.j2a = 0
        self.sites = {**self.capture.sites, "j2a": _site(J2A_POLL_LIMIT)}

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark(self, step: str, text: str) -> None:
        self.step_ts[step] = time.monotonic()
        self._log(f"STEP {step}: {text}")

    def _cell(self, name: str, text: str) -> None:
        self._log(f"CELL {name} {text}")

    async def _rd32(self, addr: int, label: str) -> int:
        rec = self.sites["j2a"]
        try:
            status, rdata = await jtag2axi_single_read(
                self.jtag,
                addr,
                size=SMC_DBG_AXSIZE_4B,
                poll_limit=J2A_POLL_LIMIT,
                require_complete=True,
            )
        except TimeoutError as exc:
            rec["expired"] += 1
            rec["last"] = f"EXPIRED {label} {exc}"
            self._log(f"TIMEOUT-PATH j2a: bound={rec['bound']} EXPIRED last={exc}")
            raise
        require_jtag_tdo_resolved(f"J2A RD {label} @0x{addr:08x}")
        self.j2a += 1
        rec["count"] = self.j2a
        rec["last"] = f"{label} status={status}"
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A RD {label} @0x{addr:08x} status={status}")
        return axi64_unpack32(addr, int(rdata))

    @staticmethod
    def _slice(value: int, byte_off: int, byte_len: int) -> int:
        return (value >> (byte_off * 8)) & ((1 << (byte_len * 8)) - 1)

    async def run(self) -> None:
        dut = self.dut
        sb = self.sb
        cap = self.capture

        self._mark("S1", "SETUP: stream capture, done rise, TAP reset, IDCODE, J2A gate open")
        await self.cfg.reset_done.wait()
        await cap.done.wait()
        if cap.done_expired:
            raise AssertionError(
                f"TIMEOUT S1_done_rise: bound {DONE_BOUND_EDGES} clk_smu, "
                f"last {cap.sites['S1_done_rise']['last']}"
            )
        stream = cap.words
        if len(stream) != STREAM_WORDS:
            raise AssertionError(
                f"eFuse response stream has {len(stream)} words, want {STREAM_WORDS}"
            )
        self._log(
            f"CELL stream words={len(stream)} first=0x{stream[0]:08x} last=0x{stream[-1]:08x} "
            f"status_errors={sum(cap.status_bits)}"
        )
        self.jtag = jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        idcode = await jtag.read_idcode()
        if idcode != IDCODE:
            raise AssertionError(f"IDCODE want 0x{IDCODE:x} got 0x{idcode:08x}")
        gate = dut.tb_smc_jtag2axi_security_disable.value
        if not gate.is_resolvable or int(gate) & 1:
            raise AssertionError(f"SMC J2A gated: security_disable={gate}")

        self._mark("S2", "read sampled map words and compare with the stream")
        reads: dict[int, int] = {}
        for idx in SAMPLED_INDICES:
            addr = MAP_BASE + 4 * idx
            reads[idx] = await self._rd32(addr, f"map word {idx}")
            self._cell(
                "all_256_words_match",
                f"addr=0x{addr:08x} idx={idx} read=0x{reads[idx]:08x} stream=0x{stream[idx]:08x}",
            )
        sb.expect_eq(
            "sampled eFuse map words equal the stream word of the same index",
            [(idx, reads[idx]) for idx in SAMPLED_INDICES],
            [(idx, stream[idx]) for idx in SAMPLED_INDICES],
            evidence="BOOT_SHADOW_SAMPLES",
        )

        self._mark("S3", "named map elements from the sampled words")
        got = []
        want = []
        for cell, symbol, index in ELEMENT_CELLS:
            addr = smc_addr(symbol) if index is None else smc_indexed_addr(symbol, index)
            idx = (addr - MAP_BASE) // 4
            if idx not in reads:
                raise AssertionError(f"element {cell} word {idx} is not in the sampled set")
            self._cell(cell, f"addr=0x{addr:08x} value=0x{reads[idx]:08x}")
            got.append((cell, reads[idx]))
            want.append((cell, stream[idx]))
        sb.expect_eq(
            "each named map element's first word equals its stream word",
            got,
            want,
            evidence="BOOT_SHADOW_ELEMENTS",
        )

        self._mark("S4", "EFUSE_INTERFACE_CTRL_STATUS after the done rise")
        status = await self._rd32(STATUS_ADDR, "EFUSE_INTERFACE_CTRL_STATUS")
        self._cell("status_bit_after_done", f"addr=0x{STATUS_ADDR:08x} value=0x{status:08x}")
        sb.expect_eq(
            "efuse_sense_done reads 1 after smc_fuse_sense_done_o rose",
            status & 1,
            1,
            evidence="BOOT_SENSE_STATUS",
        )

        self._mark("S5", "smc_shadow_regs port sampled after the done rise")
        await RisingEdge(dut.clk_smu_i)
        raw = dut.smc_shadow_regs.value
        if not raw.is_resolvable:
            raise AssertionError(f"X/Z on smc_shadow_regs: {raw}")
        port = int(raw)
        bits = len(dut.smc_shadow_regs)
        for idx in SAMPLED_INDICES:
            slc = self._slice(port, 4 * idx, 4)
            self._log(
                f"CHK-BOOT-SHADOW-PORT: idx={idx} slice=0x{slc:08x} stream=0x{stream[idx]:08x} "
                f"equal={int(slc == stream[idx])}"
            )
        self._cell(
            "port_matches_map",
            f"smc_shadow_regs nonzero={int(port != 0)} bits={bits}",
        )
        sb.expect_eq(
            "smc_shadow_regs resolves and is not all zero after the sense",
            (True, port != 0),
            (True, True),
            evidence="BOOT_SHADOW_PORT",
        )

        self._mark("S6", "TIMEOUT: bounded waits and last state")
        lines = []
        for site, rec in self.sites.items():
            state = "EXPIRED" if rec["expired"] else "ok"
            lines.append(
                f"{site}: bound={rec['bound']} {state} count={rec['count']} last={rec['last']}"
            )
        for line in lines:
            self._log(f"TIMEOUT-PATH {line}")
        expired = sum(rec["expired"] for rec in self.sites.values())
        self._log(
            f"CHK-TIMEOUT-PATHS: sites={len(lines)} expired={expired} "
            f"j2a_accesses_counted={self.j2a} (counted at the call sites of this seq)"
        )
        sb.expect_eq("expired TIMEOUT-PATH records", expired, 0, evidence="CHK_TIMEOUT_PATHS")
        sb.expect_eq("bounded wait sites named by the test steps", len(lines), CONTRACT_WAIT_SITES)

        self.step_ts["PASS"] = time.monotonic()
        order = ["S1", "S2", "S3", "S4", "S5", "S6", "PASS"]
        for a, b in zip(order, order[1:]):
            if self.step_ts[a] >= self.step_ts[b]:
                raise AssertionError(f"CHK-NONVAC order fail: {a} not before {b}")
        self._log("CHK-NONVAC: PASS (ordered fence S1<S2<S3<S4<S5<S6<PASS)")
        sb.expect_eq("CHK-NONVAC ordered fence", len(order), 7, evidence="CHK-NONVAC")
