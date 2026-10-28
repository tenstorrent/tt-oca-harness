# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_R4_001 ANCHOR: smc_log_engine_transfer_test
# DV-TESTCASE-CONTRACT-REVISION: 2 RECORD-SHA256: 047d42022e2d641a47ec590f36f30504d88952df77710af282fbfb6d5b7d11fd
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_R4_VPLAN_DETAIL.md @ artifact_revision 2 ENV: cocotb
"""Log-engine register surface and all-16-slot transfers on every uart_log_engine_wrap.

Spec sources: hw/ip/uart/log_engine/doc/architecture.adoc, interface.adoc and memmap.adoc,
hw/ip/uart/log_engine/regs/gen/adoc/log_engine.adoc,
hw/ip/uart/uart_log_engine_wrap/regs/gen/adoc/uart_log_engine_ctrl.adoc,
hw/ip/uart/uart_16550/regs/gen/adoc/uart_16550_main.adoc, hw/sys/smc/doc/fabric.adoc and
periphs.adoc.

The steps run in the contract's order, each across all four wrappers before the next:

* S2 reads the 23 log-engine words and the wrapper control register of every wrapper before
  anything writes to it, and reads INTR_TEST and every other register the generated
  wrapper map lists outside the log-engine bank once, logging the values.
* S3 writes 0xA5A5A5A5, its complement and 0 to the five writable log-engine registers
  other than LOG_CTRL with CTRL.EN = 0 and compares the documented RW bits; CTRL.UART_EN
  takes 1 then 0. A non-zero LOG_LEN starts a transfer that may not be withdrawn, so no
  LOG_CTRL element is written there; S5 and S7 read their stored lengths back.
* S4 puts each UART in MCR.LOOP with the bench's arm sequence and sends 0x55 and 0xAA
  through it.
* S5 gives all 16 LOG_CTRL elements of one wrapper at a time a non-zero length of at most
  one 8-byte fetch word over a 0x80-byte SPM region (8-byte slots). Byte 0 of slot i of wrapper N is the header
  N * 16 + i; byte j >= 1 is 0x40 + ((7 i + 13 j + 29 N) mod 0xC0), so a header never occurs
  in a body and the received stream partitions into its messages. While the receiver is
  empty the drain reads the other wrappers' LSR and samples the wrapper's LOG_CTRL
  elements round robin.
* S6 polls every LOG_CTRL element of every wrapper to 0 and reads LSR and INTR_STATUS.
* S7 writes a length of 1 into all 16 elements with CTRL.EN = 0, holds for 256 LSR reads,
  then enables the engine, receives the 16 headers and logs the LSR reads they took.
* S8 places four logs in 64-byte slots of a 0x400-byte region in the SYS_OUT responder's memory outside the SMC window and
  captures every AR and R on the output AXI port while wrapper 0 fetches them.
* S9 sets each INTR_STATUS bit through INTR_TEST and clears it with RW1C.
* S10 clears the engine's configuration and restores the UART.

Every poll is a counted number of register reads that fails with the last value it read.
The message order is logged and not compared (SF-003); INTR_TEST read values and reserved
bit readbacks are logged and not compared (SF-005).
"""

from __future__ import annotations

import re

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import (
    _REPO,
    GLOBAL_BASE_RESET,
    LOCAL_BASE_RESET,
    REGION_SIZE_RESET,
    SPM_MEMORY_BASE,
    SPM_MEMORY_SIZE,
    log_engine_u32,
    smc_addr,
    smc_indexed_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_log_engine_utils import (
    CTRL_EN,
    LOG_CTRL_PATH,
    LOG_CTRL_PY,
    LOG_LEN,
    LSR_DR,
    LSR_LINE_ERRORS,
    NUM_LOG_ENTRIES,
    RBR_DATA,
    THR_OFFSET,
    UART_EN,
    WRAP,
    WRAP_NUM,
    WRAP_STRIDE_SYMBOL,
    arm_uart,
    engine_reg,
    restore_uart,
    uart_base,
    uart_reg,
    wrap_ctrl_reg,
)
from .smc_output_fabric_vip_utils import (
    OUTBOUND0_END,
    OUTBOUND0_FILTER_CONFIG,
    OUTBOUND0_START,
    OUTPUT_FABRIC_ADDR,
    PASS_ALL_CONFIG,
)
from .smc_regblock_field_sweep_utils import array_reg_instances

_WRAPS = 4
# uart_log_engine_wrap instance N sits at BASE + 0x6000 + N * 0x400 (SF-026).
_WRAP_OFFSET = 0x6000
_WRAP_STRIDE = 0x400

_FETCH_ERR = log_engine_u32("LOG_ENGINE__INTR_STATUS__LOG_FETCH_ERR_bm")
_WRITE_ERR = log_engine_u32("LOG_ENGINE__INTR_STATUS__LOG_WRITE_ERR_bm")
_TEST_FETCH = log_engine_u32("LOG_ENGINE__INTR_TEST__LOG_FETCH_ERR_bm")
_TEST_WRITE = log_engine_u32("LOG_ENGINE__INTR_TEST__LOG_WRITE_ERR_bm")
_ENABLE_BITS = log_engine_u32("LOG_ENGINE__INTR_ENABLE__LOG_FETCH_ERR_bm") | log_engine_u32(
    "LOG_ENGINE__INTR_ENABLE__LOG_WRITE_ERR_bm"
)
_SIZE_BITS = log_engine_u32("LOG_ENGINE__LOG_REGION_SIZE__LOG_REGION_SIZE_bm")
_ADDR_HI_BITS = log_engine_u32("LOG_ENGINE__LOG_REGION_ADDR__LOG_REGION_ADDR_HI_bm") >> 32
_ADDR_HI_RESERVED = log_engine_u32("LOG_ENGINE__LOG_REGION_ADDR__RESERVED_bm") >> 32
_WORD = 0xFFFF_FFFF

# log_engine.adoc: LOG_REGION_SIZE[19:0], LOG_REGION_ADDR [55:32] and [31:0] with [63:56]
# reading 0, LOG_WRITE_ADDR[31:0], INTR_ENABLE bits 0 and 4, LOG_CTRL.LOG_LEN [15:0];
# INTR_STATUS bit 0 LOG_FETCH_ERR and bit 4 LOG_WRITE_ERR.
assert _SIZE_BITS == 0xF_FFFF and _ADDR_HI_BITS == 0xFF_FFFF and _ADDR_HI_RESERVED == 0xFF00_0000
assert _ENABLE_BITS == 0x11 and LOG_LEN == 0xFFFF and CTRL_EN == 0x1
assert (_FETCH_ERR, _WRITE_ERR, _TEST_FETCH, _TEST_WRITE) == (0x01, 0x10, 0x01, 0x10)

_PATTERN = 0xA5A5_A5A5
_RW_VALUES = (_PATTERN, ~_PATTERN & _WORD, 0)
_LOOP_CHARS = (0x55, 0xAA)

_BEAT = 8
# S5 / S7: the smallest 128-byte aligned region, 16 slots of one fetch word each.
_REGION_SIZE = 0x80
_SLOT_STRIDE = _REGION_SIZE // NUM_LOG_ENTRIES
_LENS = (8, 1, 7, 2, 3, 4, 5, 6, 8, 1, 7, 2, 3, 4, 5, 6)
assert _SLOT_STRIDE == _BEAT and max(_LENS) <= _BEAT and min(_LENS) >= 1
assert sum(_LENS) == 72 and {n % 8 for n in _LENS} >= {0, 1, 7}
_LOG_BUFFER_OFFSET = 0x40000
# S8: four logs in 64-byte slots of SYS_OUT memory.
_OUT_REGION_SIZE = 0x400
_OUT_SLOT_STRIDE = _OUT_REGION_SIZE // NUM_LOG_ENTRIES
_OUT_LENS = (8, 9, 16, 1)
_OUT_REGION = OUTPUT_FABRIC_ADDR + 0x4000
_ARPROT_FETCH = 0b010

# S11 bounds, in register reads.
_RX_POLLS_PER_BYTE = 400
_HWCLR_POLLS = 64
_FIRST_CHAR_POLLS = 400
_HOLD_READS = 256

_TERMS = (
    "SETUP",
    "RESET-READ",
    "REG-RW",
    "LOOPBACK",
    "ALL16",
    "CLEARED",
    "HOLD-ENABLE",
    "OUTBOUND-FETCH",
    "INTR-TEST",
    "RESTORED",
)
_RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}

_WRAP_ADDR_H = (
    _REPO / "hw" / "ip" / "uart" / "uart_log_engine_wrap" / "regs" / "gen" / "c"
) / "uart_log_engine_wrap_addr.h"


def _wrap_map_registers() -> list[tuple[str, int]]:
    """The registers the generated uart_log_engine_wrap map lists, in offset order."""
    text = _WRAP_ADDR_H.read_text()
    bases = re.findall(r"#define UART_LOG_ENGINE_WRAP_(\w+)_BASE_ADDR (0x[0-9A-Fa-f]+)\s", text)
    blocks = set(re.findall(r"#define UART_LOG_ENGINE_WRAP_(\w+)_SIZE ", text))
    regs = [(name, int(value, 16)) for name, value in bases if name not in blocks]
    return sorted(regs, key=lambda reg: reg[1])


def _log_byte(wrap: int, slot: int, offset: int) -> int:
    """Byte ``offset`` of slot ``slot`` of wrapper ``wrap`` in the S5 byte scheme."""
    if offset == 0:
        return wrap * NUM_LOG_ENTRIES + slot
    return 0x40 + ((7 * slot + 13 * offset + 29 * wrap) % 0xC0)


def _words(length: int) -> int:
    return (length + _BEAT - 1) // _BEAT


def _slot_words(wrap: int, slot: int, length: int) -> list[int]:
    """The 64-bit words of a slot, least significant lane first."""
    words = []
    for word in range(_words(length)):
        value = 0
        for lane in range(_BEAT):
            value |= _log_byte(wrap, slot, word * _BEAT + lane) << (8 * lane)
        words.append(value)
    return words


class _OutputAxiCapture:
    """Passive capture of AR and R handshakes on the SYS_OUT AXI port."""

    def __init__(self) -> None:
        self.ars: list[tuple[int, int, int, int]] = []
        self.r_beats: list[int] = []
        self.outstanding = 0
        self.max_outstanding = 0
        self.overlapped = 0

    @staticmethod
    def _bit(ifc, name: str) -> int:
        value = getattr(ifc, name).value
        assert value.is_resolvable, f"u_output_axi_if.{name} is X/Z ({value})"
        return int(value)

    async def run(self) -> None:
        ifc = cocotb.top.u_output_axi_if
        while True:
            await RisingEdge(cocotb.top.clk_smc_i)
            await ReadOnly()
            ar = self._bit(ifc, "arvalid") and self._bit(ifc, "arready")
            r = self._bit(ifc, "rvalid") and self._bit(ifc, "rready")
            if ar:
                fields = tuple(self._bit(ifc, f"ar{n}") for n in ("addr", "len", "size", "prot"))
                self.ars.append(fields)
                if self.outstanding:
                    self.overlapped += 1
                self.outstanding += 1
                self.max_outstanding = max(self.max_outstanding, self.outstanding)
            if r:
                self.r_beats.append(self._bit(ifc, "rresp"))
                if self._bit(ifc, "rlast"):
                    self.outstanding -= 1


class smc_log_engine_transfer_test_seq(SmcCsrSeq):
    """Register surface, all-16-slot transfers, enable gate and outbound fetch of every wrap."""

    def __init__(self, name: str = "smc_log_engine_transfer_test_seq") -> None:
        super().__init__(name)
        self.transfers = 0
        self.bytes_checked = 0
        self.hwclr_elements = 0
        self.wraps = 0
        self._terms: list[tuple[str, int, int]] = []
        self._term_start = 0
        self._elements: dict[int, list] = {}
        self._waits: dict[str, list] = {}
        self._lsr_samples = 0
        self._other_dr_samples = 0
        self._len_samples = 0
        self._inflight: dict[int, int] = {}
        self._zeroed: set[tuple[int, int]] = set()

    # -- bookkeeping -----------------------------------------------------

    def _term(self, term: str) -> None:
        count = self.accesses - self._term_start
        assert count > 0, f"fence term {term} issued no SEP_IN access"
        self._terms.append((term, int(get_sim_time("ns")), count))
        self._term_start = self.accesses

    def _wait(self, kind: str, bound: str, used: int, last: str) -> None:
        entry = self._waits.setdefault(kind, [0, bound, 0, ""])
        entry[0] += 1
        entry[2] = max(entry[2], used)
        entry[3] = last

    # -- accesses --------------------------------------------------------

    async def _read_resp(self, name: str, addr: int, allow_error: bool) -> tuple[int, int]:
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.allow_error = allow_error
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None, f"{name} @ 0x{addr:08x}: no read response"
        return item.resp_code, item.rdata

    async def _read_okay(self, name: str, addr: int) -> int:
        resp, data = await self._read_resp(name, addr, allow_error=False)
        assert resp == 0, f"{name} @ 0x{addr:08x}: answered {_RESP_NAME.get(resp, resp)}"
        return data

    async def _lsr(self, wrap: int, label: str) -> int:
        status = await self.csr_read(f"{label}_W{wrap}_LSR", uart_reg(wrap, "LSR"))
        self._lsr_samples += 1
        assert status & LSR_LINE_ERRORS == 0, (
            f"{label} wrapper {wrap}: LSR 0x{status:02x} reports overrun, parity, framing or "
            f"break (0x{status & LSR_LINE_ERRORS:02x})"
        )
        return status

    def _classify(self, wrap: int, slot: int, value: int, length: int, heads: set[int]) -> None:
        """One LOG_CTRL sample: the submitted length or 0, never back after 0."""
        self._len_samples += 1
        assert value in (length, 0), (
            f"wrapper {wrap} LOG_CTRL[{slot}] read 0x{value:08x}; it holds the submitted "
            f"length {length} or 0, never a partial count"
        )
        key = (wrap, slot)
        if value == 0:
            self._zeroed.add(key)
            return
        assert key not in self._zeroed, (
            f"wrapper {wrap} LOG_CTRL[{slot}] read {value} after it had read 0 in this transfer"
        )
        if _log_byte(wrap, slot, 0) in heads:
            self._inflight[wrap] = self._inflight.get(wrap, 0) + 1

    async def _await_clear(self, wrap: int, slot: int, length: int, label: str) -> None:
        addr = self._elements[wrap][slot].addr
        value = None
        for poll in range(1, _HWCLR_POLLS + 1):
            value = await self.csr_read(f"{label}_W{wrap}_LOG_CTRL{slot}", addr)
            self._classify(wrap, slot, value, length, set())
            if value == 0:
                self._wait("LOG_CTRL clear poll", f"{_HWCLR_POLLS} reads", poll, "0x0")
                return
        raise AssertionError(
            f"{label} wrapper {wrap} LOG_CTRL[{slot}] @ 0x{addr:08x} still read 0x{value:08x} "
            f"after {_HWCLR_POLLS} reads; hardware did not clear the completed length"
        )

    async def _drain(self, wrap: int, expected: int, label: str, side=None) -> tuple[list, int]:
        """Read ``expected`` bytes from RBR; ``side`` runs while the receiver is empty."""
        rbr = uart_reg(wrap, "RBR")
        received: list[int] = []
        heads: set[int] = set()
        limit = expected * _RX_POLLS_PER_BYTE
        reads = 0
        status = 0
        while len(received) < expected:
            assert reads < limit, (
                f"{label} wrapper {wrap}: {len(received)} of {expected} byte(s) reached the "
                f"receiver within {limit} LSR reads; last LSR 0x{status:02x}"
            )
            status = await self._lsr(wrap, label)
            reads += 1
            if status & LSR_DR:
                byte = (await self.csr_read(f"{label}_W{wrap}_RBR", rbr)) & RBR_DATA
                received.append(byte)
                heads.add(byte)
            elif side is not None:
                await side(heads)
        self._wait("LSR drain poll", f"{_RX_POLLS_PER_BYTE} reads/byte", reads, f"0x{status:02x}")
        return received, reads

    def _partition(self, wrap: int, received: list[int], lens, label: str) -> list[int]:
        """Split a stream into whole messages; returns the slot order."""
        order: list[int] = []
        pos = 0
        while pos < len(received):
            slot = received[pos] - wrap * NUM_LOG_ENTRIES
            assert 0 <= slot < len(lens) and slot not in order, (
                f"{label} wrapper {wrap}: byte {pos} is 0x{received[pos]:02x}, which is not the "
                f"header of a slot still to come (delivered {order})"
            )
            want = [_log_byte(wrap, slot, j) for j in range(lens[slot])]
            got = received[pos : pos + lens[slot]]
            assert got == want, (
                f"{label} wrapper {wrap} slot {slot}: message at byte {pos} is "
                f"{[f'0x{b:02x}' for b in got]}, slot holds {[f'0x{b:02x}' for b in want]}"
            )
            order.append(slot)
            pos += lens[slot]
        assert sorted(order) == list(range(len(lens))), (
            f"{label} wrapper {wrap}: slots {order} delivered, {len(lens)} were requested"
        )
        return order

    # -- addressing ------------------------------------------------------

    @staticmethod
    def _buffer(wrap: int) -> int:
        base = SPM_MEMORY_BASE + _LOG_BUFFER_OFFSET + wrap * _REGION_SIZE
        assert base % _BEAT == 0 and base + _REGION_SIZE <= SPM_MEMORY_BASE + SPM_MEMORY_SIZE, (
            f"the log region of wrapper {wrap} at 0x{base:08x} leaves the SPM window"
        )
        return base

    async def _program_region(self, wrap: int, label: str, region: int, size: int) -> None:
        await self.csr_write(f"{label}_W{wrap}_SIZE", engine_reg(wrap, "LOG_REGION_SIZE"), size)
        addr = engine_reg(wrap, "LOG_REGION_ADDR")
        await self.csr_write(f"{label}_W{wrap}_ADDR_LO", addr, region & _WORD)
        await self.csr_write(f"{label}_W{wrap}_ADDR_HI", addr + 4, region >> 32)

    # -- S1 / S2 ---------------------------------------------------------

    def _setup(self) -> None:
        self.wraps = smc_addr(WRAP_NUM)
        assert self.wraps == _WRAPS, f"the generated map declares {self.wraps} UART wraps, not 4"
        for wrap in range(self.wraps):
            base = smc_indexed_addr(f"{WRAP}BASE_ADDR", wrap)
            want = LOCAL_BASE_RESET + _WRAP_OFFSET + wrap * _WRAP_STRIDE
            assert base == want, f"wrapper {wrap} at 0x{base:08x}, not 0x{want:08x}"
            elements = array_reg_instances(LOG_CTRL_PATH, LOG_CTRL_PY, WRAP_STRIDE_SYMBOL, wrap)
            assert len(elements) == NUM_LOG_ENTRIES, (
                f"wrapper {wrap}: the generated map declares {len(elements)} LOG_CTRL elements"
            )
            for slot, inst in enumerate(elements):
                want = engine_reg(wrap, "CTRL") + 0x40 + 4 * slot
                assert inst.addr == want, f"wrapper {wrap} LOG_CTRL[{slot}] at 0x{inst.addr:08x}"
            self._elements[wrap] = elements
        assert self.cfg is not None and self.cfg.sys_out_mem is not None, (
            "the SYS_OUT responder is not bound, so S8 cannot seed its logs"
        )

    def _engine_words(self, wrap: int) -> list[tuple[str, int]]:
        addr = engine_reg(wrap, "LOG_REGION_ADDR")
        words = [
            ("CTRL", engine_reg(wrap, "CTRL")),
            ("LOG_REGION_SIZE", engine_reg(wrap, "LOG_REGION_SIZE")),
            ("LOG_REGION_ADDR_LO", addr),
            ("LOG_REGION_ADDR_HI", addr + 4),
            ("LOG_WRITE_ADDR", engine_reg(wrap, "LOG_WRITE_ADDR")),
            ("INTR_STATUS", engine_reg(wrap, "INTR_STATUS")),
            ("INTR_ENABLE", engine_reg(wrap, "INTR_ENABLE")),
        ]
        words += [(f"LOG_CTRL{n}", e.addr) for n, e in enumerate(self._elements[wrap])]
        return words

    async def _reset_reads(self) -> tuple[str, str]:
        regs = _wrap_map_registers()
        first_name, first_offset = regs[0]
        assert (first_name, first_offset) == ("UART_LOG_ENGINE_CTRL_CTRL", 0), (
            f"the generated wrapper map's first register is {first_name} @ 0x{first_offset:x}"
        )
        others = [(n, off) for n, off in regs[1:] if not n.startswith("LOG_ENGINE_")]
        assert others, "the generated wrapper map lists no register outside the log-engine bank"
        reads = 0
        intr_test = []
        for wrap in range(self.wraps):
            for name, addr in self._engine_words(wrap):
                data = await self._read_okay(f"S2_W{wrap}_{name}", addr)
                assert data == 0, f"S2 wrapper {wrap} {name}: reset read 0x{data:08x}, not 0x0"
                reads += 1
            resp, data = await self._read_resp(
                f"S2_W{wrap}_INTR_TEST", engine_reg(wrap, "INTR_TEST"), allow_error=True
            )
            intr_test.append(f"w{wrap}=0x{data:08x}/{_RESP_NAME.get(resp, resp)}")
            ctrl = await self._read_okay(f"S2_W{wrap}_UART_EN", wrap_ctrl_reg(wrap))
            assert ctrl & UART_EN == 0, f"S2 wrapper {wrap}: CTRL.UART_EN reset read 0x{ctrl:x}"
            base = smc_indexed_addr(f"{WRAP}BASE_ADDR", wrap)
            for name, offset in others:
                await self._read_okay(f"S2_W{wrap}_{name}", base + offset)
        total = self.wraps * len(self._engine_words(0))
        assert reads == total == 92, f"{reads} reset reads of {total}"
        self._term("RESET-READ")
        cocotb.log.info(
            "CHK-LE-REG-RESET: %d wrappers x 23 words, %d/%d read 0x0 OKAY; INTR_TEST rd %s",
            self.wraps,
            reads,
            total,
            " ".join(intr_test),
        )
        offsets = ",".join(f"0x{off:03x}" for _, off in others)
        names = ",".join(n for n, _ in others)
        return f"{len(others)}", f"{offsets} = {names}"

    # -- S3 --------------------------------------------------------------

    def _rw_registers(self, wrap: int) -> list[tuple[str, int, int, int]]:
        """(name, address, documented RW mask, bits that read 0) per writable register."""
        addr = engine_reg(wrap, "LOG_REGION_ADDR")
        regs = [
            ("LOG_REGION_SIZE", engine_reg(wrap, "LOG_REGION_SIZE"), _SIZE_BITS, 0),
            ("LOG_REGION_ADDR_LO", addr, _WORD, 0),
            ("LOG_REGION_ADDR_HI", addr + 4, _ADDR_HI_BITS, _ADDR_HI_RESERVED),
            ("LOG_WRITE_ADDR", engine_reg(wrap, "LOG_WRITE_ADDR"), _WORD, 0),
            ("INTR_ENABLE", engine_reg(wrap, "INTR_ENABLE"), _ENABLE_BITS, 0),
        ]
        log_ctrl = {e.addr for e in self._elements[wrap]}
        assert not log_ctrl & {addr for _, addr, _, _ in regs}, (
            f"S3 wrapper {wrap}: the register sweep reaches a LOG_CTRL element"
        )
        return regs

    async def _register_rw(self, others: tuple[str, str]) -> None:
        compares = 0
        reserved: dict[str, set[int]] = {}
        for wrap in range(self.wraps):
            ctrl = await self._read_okay(f"S3_W{wrap}_EN_OFF", engine_reg(wrap, "CTRL"))
            assert ctrl & CTRL_EN == 0, f"S3 wrapper {wrap}: CTRL.EN reads set before S3"
            for name, addr, mask, zero in self._rw_registers(wrap):
                for value in _RW_VALUES:
                    await self.csr_write(f"S3_W{wrap}_{name}_0x{value:08x}", addr, value)
                    got = await self._read_okay(f"S3_W{wrap}_{name}_0x{value:08x}_RB", addr)
                    assert got & mask == value & mask, (
                        f"S3 wrapper {wrap} {name}: wrote 0x{value:08x}, RW bits 0x{mask:08x} "
                        f"read 0x{got & mask:08x}"
                    )
                    assert got & zero == 0, (
                        f"S3 wrapper {wrap} {name}: bits 0x{zero:08x} read 0x{got & zero:08x}, "
                        f"they read as zero"
                    )
                    reserved.setdefault(name.rstrip("0123456789"), set()).add(
                        got & ~(mask | zero) & _WORD
                    )
                    compares += 1
            for value in (UART_EN, 0):
                await self.csr_write(f"S3_W{wrap}_UART_EN_{value}", wrap_ctrl_reg(wrap), value)
                got = await self._read_okay(f"S3_W{wrap}_UART_EN_{value}_RB", wrap_ctrl_reg(wrap))
                assert got & UART_EN == value, (
                    f"S3 wrapper {wrap}: CTRL.UART_EN wrote {value}, read 0x{got:08x}"
                )
        assert compares == self.wraps * 5 * 3 == 60, f"{compares} RW compares, 60 planned"
        self._term("REG-RW")
        cocotb.log.info(
            "CHK-LE-REG-RW: %d wrappers x 5 regs x 3 values, %d/%d RW-bit match, "
            "ADDR_HI[31:24]=0, LOG_CTRL excluded (non-zero LOG_LEN starts a transfer); "
            "UART_EN 0->1->0 x%d; other ctrl regs %s x%d read OKAY (offsets %s)",
            self.wraps,
            compares,
            self.wraps * 5 * 3,
            self.wraps,
            others[0],
            self.wraps,
            others[1],
        )
        cocotb.log.info(
            "LE-REG-RW reserved-bit readbacks, logged only (SF-005): %s",
            " ".join(f"{k}={sorted(hex(v) for v in vals)}" for k, vals in reserved.items()),
        )

    # -- S4 --------------------------------------------------------------

    async def _loopback(self) -> None:
        returned = 0
        for wrap in range(self.wraps):
            await arm_uart(self, wrap)
            thr = uart_base(wrap) + THR_OFFSET
            for char in _LOOP_CHARS:
                await self.csr_write(f"S4_W{wrap}_THR_0x{char:02x}", thr, char)
                status = 0
                for poll in range(1, _RX_POLLS_PER_BYTE + 1):
                    status = await self._lsr(wrap, "S4")
                    if status & LSR_DR:
                        break
                else:
                    raise AssertionError(
                        f"S4 wrapper {wrap}: 0x{char:02x} not received within "
                        f"{_RX_POLLS_PER_BYTE} LSR reads; last LSR 0x{status:02x}"
                    )
                self._wait("LSR drain poll", f"{_RX_POLLS_PER_BYTE} reads/byte", poll, "DR=1")
                got = await self.csr_read(f"S4_W{wrap}_RBR_0x{char:02x}", uart_reg(wrap, "RBR"))
                assert got & RBR_DATA == char, (
                    f"S4 wrapper {wrap}: wrote 0x{char:02x} to THR, RBR returned "
                    f"0x{got & RBR_DATA:02x}"
                )
                after = await self._lsr(wrap, "S4_AFTER")
                assert after & LSR_DR == 0, (
                    f"S4 wrapper {wrap}: LSR.DR still 1 (0x{after:02x}) after the RBR read"
                )
                returned += 1
        assert returned == self.wraps * len(_LOOP_CHARS)
        self._term("LOOPBACK")
        cocotb.log.info(
            "CHK-LE-UART-LOOP: %d wrappers x {0x55,0xAA}, %d/%d returned exact, DR 1->0 each",
            self.wraps,
            returned,
            self.wraps * len(_LOOP_CHARS),
        )

    # -- S5 --------------------------------------------------------------

    async def _load(self, wrap: int, region: int) -> None:
        for slot, length in enumerate(_LENS):
            for word, value in enumerate(_slot_words(wrap, slot, length)):
                addr = region + slot * _SLOT_STRIDE + word * _BEAT
                await self.csr_write(f"S5_W{wrap}_S{slot}_W{word}", addr, value, length=8)
        for slot, length in enumerate(_LENS):
            for word, value in enumerate(_slot_words(wrap, slot, length)):
                addr = region + slot * _SLOT_STRIDE + word * _BEAT
                await self.csr_read(
                    f"S5_W{wrap}_S{slot}_W{word}_RB", addr, expected=value, length=8
                )

    async def _all16(self, wrap: int) -> tuple[list[int], int]:
        region = self._buffer(wrap)
        await self._load(wrap, region)
        await self._program_region(wrap, "S5", region, _REGION_SIZE)
        await self.csr_write(
            f"S5_W{wrap}_WRITE_ADDR",
            engine_reg(wrap, "LOG_WRITE_ADDR"),
            uart_base(wrap) + THR_OFFSET,
        )
        status_addr = engine_reg(wrap, "INTR_STATUS")
        await self.csr_write(f"S5_W{wrap}_INTR_CLEAR", status_addr, _FETCH_ERR | _WRITE_ERR)
        await self.csr_read(f"S5_W{wrap}_INTR_IDLE", status_addr, expected=0)
        await self.csr_write(f"S5_W{wrap}_EN", engine_reg(wrap, "CTRL"), CTRL_EN)
        await self.csr_read(f"S5_W{wrap}_EN_RB", engine_reg(wrap, "CTRL"), expected=CTRL_EN)
        for slot, length in enumerate(_LENS):
            await self.csr_write(f"S5_W{wrap}_GO{slot}", self._elements[wrap][slot].addr, length)

        others = [w for w in range(self.wraps) if w != wrap]
        turn = [0]

        async def side(heads: set[int]) -> None:
            for other in others:
                status = await self._lsr(other, f"S5_OTHER_OF_W{wrap}")
                assert status & LSR_DR == 0, (
                    f"S5: wrapper {other}'s receiver reports data (LSR 0x{status:02x}) while "
                    f"wrapper {wrap} transfers"
                )
                self._other_dr_samples += 1
            slot = turn[0] % NUM_LOG_ENTRIES
            value = await self.csr_read(
                f"S5_W{wrap}_LOG_CTRL{slot}_SAMPLE", self._elements[wrap][slot].addr
            )
            self._classify(wrap, slot, value, _LENS[slot], heads)
            turn[0] += 1

        received, reads = await self._drain(wrap, sum(_LENS), "S5", side)
        order = self._partition(wrap, received, _LENS, "S5")
        self.bytes_checked += len(received)
        self.transfers += 1
        return order, reads

    # -- S7 --------------------------------------------------------------

    async def _hold_then_enable(self, wrap: int) -> tuple[int, int]:
        ctrl = engine_reg(wrap, "CTRL")
        await self.csr_write(f"S7_W{wrap}_EN_OFF", ctrl, 0)
        for slot in range(NUM_LOG_ENTRIES):
            await self.csr_write(f"S7_W{wrap}_GO{slot}", self._elements[wrap][slot].addr, 1)
        for _ in range(_HOLD_READS):
            status = await self._lsr(wrap, "S7_HOLD")
            assert status & LSR_DR == 0, (
                f"S7 wrapper {wrap}: a character arrived (LSR 0x{status:02x}) with CTRL.EN = 0"
            )
        self._wait("S7 EN=0 hold window", f"{_HOLD_READS} LSR reads", _HOLD_READS, "DR=0")
        for slot in range(NUM_LOG_ENTRIES):
            value = await self.csr_read(
                f"S7_W{wrap}_LOG_CTRL{slot}_HELD", self._elements[wrap][slot].addr
            )
            assert value == 1, (
                f"S7 wrapper {wrap} LOG_CTRL[{slot}] read 0x{value:08x} after the EN=0 hold; "
                f"the pending length 1 is retained"
            )
            self._classify(wrap, slot, value, 1, set())
        await self.csr_write(f"S7_W{wrap}_EN", ctrl, CTRL_EN)
        status = 0
        for first in range(1, _FIRST_CHAR_POLLS + 1):
            status = await self._lsr(wrap, "S7_FIRST")
            if status & LSR_DR:
                break
        else:
            raise AssertionError(
                f"S7 wrapper {wrap}: no character within {_FIRST_CHAR_POLLS} LSR reads after "
                f"CTRL.EN = 1; last LSR 0x{status:02x}"
            )
        self._wait("S7 first-character poll", f"{_FIRST_CHAR_POLLS} reads", first, "DR=1")
        received = [(await self.csr_read(f"S7_W{wrap}_RBR0", uart_reg(wrap, "RBR"))) & RBR_DATA]
        turn = [0]

        async def side(heads: set[int]) -> None:
            slot = turn[0] % NUM_LOG_ENTRIES
            value = await self.csr_read(
                f"S7_W{wrap}_LOG_CTRL{slot}_SAMPLE", self._elements[wrap][slot].addr
            )
            self._classify(wrap, slot, value, 1, heads | set(received))
            turn[0] += 1

        rest, reads = await self._drain(wrap, NUM_LOG_ENTRIES - 1, "S7", side)
        received += rest
        self._partition(wrap, received, (1,) * NUM_LOG_ENTRIES, "S7")
        for slot in range(NUM_LOG_ENTRIES):
            await self._await_clear(wrap, slot, 1, "S7")
        return first, first + reads

    # -- S8 --------------------------------------------------------------

    async def _outbound_fetch(self) -> tuple[int, int, int]:
        wrap = 0
        region = _OUT_REGION
        assert region % _BEAT == 0
        for base in (LOCAL_BASE_RESET, GLOBAL_BASE_RESET):
            assert not (
                base <= region < base + REGION_SIZE_RESET
                or base <= region + _OUT_REGION_SIZE - 1 < base + REGION_SIZE_RESET
            ), f"S8 region 0x{region:x} overlaps the SMC window at 0x{base:x}"
        ctrl = engine_reg(wrap, "CTRL")
        await self.csr_write("S8_EN_OFF", ctrl, 0)
        filters = (
            ("OUT0_START", OUTBOUND0_START, 0),
            ("OUT0_END", OUTBOUND0_END, 0x00FF_FFFF_FFFF_FFFF),
            ("OUT0_CFG", OUTBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG),
        )
        saved = []
        for label, addr, _ in filters:
            saved.append(await self.csr_read(f"S8_{label}_SAVE", addr, length=8))
        for label, addr, value in filters:
            await self.csr_write(f"S8_{label}", addr, value, length=8)
        mem = self.cfg.sys_out_mem
        for slot, length in enumerate(_OUT_LENS):
            for word, value in enumerate(_slot_words(wrap, slot, length)):
                mem.write_int(region + slot * _OUT_SLOT_STRIDE + word * _BEAT, value, _BEAT)
        await self._program_region(wrap, "S8", region, _OUT_REGION_SIZE)
        capture = _OutputAxiCapture()
        task = cocotb.start_soon(capture.run())
        try:
            await self.csr_write("S8_EN", ctrl, CTRL_EN)
            for slot, length in enumerate(_OUT_LENS):
                await self.csr_write(f"S8_GO{slot}", self._elements[wrap][slot].addr, length)
            turn = [0]

            async def side(heads: set[int]) -> None:
                slot = turn[0] % len(_OUT_LENS)
                value = await self.csr_read(
                    f"S8_LOG_CTRL{slot}_SAMPLE", self._elements[wrap][slot].addr
                )
                self._classify(wrap, slot, value, _OUT_LENS[slot], heads)
                turn[0] += 1

            self._zeroed = set()
            received, _ = await self._drain(wrap, sum(_OUT_LENS), "S8", side)
            order = self._partition(wrap, received, _OUT_LENS, "S8")
            for slot, length in enumerate(_OUT_LENS):
                await self._await_clear(wrap, slot, length, "S8")
        finally:
            task.kill()
        await self.csr_write("S8_EN_DONE", ctrl, 0)
        for (label, addr, _), value in zip(filters, saved):
            await self.csr_write(f"S8_{label}_RESTORE", addr, value, length=8)

        want = sorted(
            region + slot * _OUT_SLOT_STRIDE + word * _BEAT
            for slot, length in enumerate(_OUT_LENS)
            for word in range(_words(length))
        )
        inside = [ar for ar in capture.ars if region <= ar[0] < region + _OUT_REGION_SIZE]
        assert len(inside) == len(want) == 6, (
            f"S8: {len(inside)} ARs for the region on output_axi, {len(want)} slot words "
            f"requested (all ARs {[hex(a[0]) for a in capture.ars]})"
        )
        assert sorted(ar[0] for ar in inside) == want, (
            f"S8: AR addresses {[hex(a[0]) for a in inside]}, slot words {[hex(a) for a in want]}"
        )
        for addr, arlen, arsize, arprot in inside:
            assert (arlen, arsize, arprot) == (0, 3, _ARPROT_FETCH), (
                f"S8: AR 0x{addr:x} ARLEN {arlen} ARSIZE {arsize} ARPROT 0b{arprot:03b}; a fetch "
                f"is one 8-byte beat with ARPROT 0b010"
            )
        assert capture.overlapped == 0 and capture.max_outstanding == 1, (
            f"S8: {capture.overlapped} AR(s) issued with a fetch outstanding "
            f"(max outstanding {capture.max_outstanding})"
        )
        assert all(resp == 0 for resp in capture.r_beats), f"S8: R responses {capture.r_beats}"
        self._term("OUTBOUND-FETCH")
        cocotb.log.info(
            "CHK-LE-FETCH-OUTBOUND: wrapper 0, %d/%d AR ARLEN=0 ARSIZE=3 ARPROT=0b010 on slot "
            "words, max outstanding %d, %d/%d bytes exact; region 0x%x, AR order %s, message "
            "order %s, %d AR(s) outside the region",
            len(inside),
            len(want),
            capture.max_outstanding,
            len(received),
            sum(_OUT_LENS),
            region,
            [hex(a[0]) for a in inside],
            order,
            len(capture.ars) - len(inside),
        )
        return len(inside), capture.max_outstanding, len(received)

    # -- S9 / S10 --------------------------------------------------------

    async def _intr_test(self) -> int:
        cleared = 0
        for wrap in range(self.wraps):
            status_addr = engine_reg(wrap, "INTR_STATUS")
            await self.csr_read(f"S9_W{wrap}_INTR_EN", engine_reg(wrap, "INTR_ENABLE"), expected=0)
            for test_bit, status_bit in ((_TEST_FETCH, _FETCH_ERR), (_TEST_WRITE, _WRITE_ERR)):
                tag = f"S9_W{wrap}_B{status_bit:02x}"
                await self.csr_write(f"{tag}_TEST", engine_reg(wrap, "INTR_TEST"), test_bit)
                got = await self.csr_read(f"{tag}_SET", status_addr)
                assert got == status_bit, (
                    f"S9 wrapper {wrap}: INTR_TEST 0x{test_bit:02x} left INTR_STATUS "
                    f"0x{got:08x}, not 0x{status_bit:02x} alone"
                )
                await self.csr_write(f"{tag}_W0", status_addr, 0)
                got = await self.csr_read(f"{tag}_KEPT", status_addr)
                assert got == status_bit, (
                    f"S9 wrapper {wrap}: a write of 0 left INTR_STATUS 0x{got:08x}; RW1C keeps "
                    f"0x{status_bit:02x}"
                )
                await self.csr_write(f"{tag}_W1C", status_addr, status_bit)
                got = await self.csr_read(f"{tag}_CLEARED", status_addr)
                assert got == 0, f"S9 wrapper {wrap}: the W1C left INTR_STATUS 0x{got:08x}"
                cleared += 1
        assert cleared == 2 * self.wraps
        return cleared

    async def _restore(self) -> None:
        for wrap in range(self.wraps):
            ctrl = engine_reg(wrap, "CTRL")
            await self.csr_write(f"S10_W{wrap}_EN_OFF", ctrl, 0)
            await self.csr_read(f"S10_W{wrap}_EN_OFF_RB", ctrl, expected=0)
            addr = engine_reg(wrap, "LOG_REGION_ADDR")
            for name, reg in (
                ("SIZE", engine_reg(wrap, "LOG_REGION_SIZE")),
                ("ADDR_LO", addr),
                ("ADDR_HI", addr + 4),
                ("WRITE_ADDR", engine_reg(wrap, "LOG_WRITE_ADDR")),
            ):
                await self.csr_write(f"S10_W{wrap}_{name}_CLR", reg, 0)
                await self.csr_read(f"S10_W{wrap}_{name}_CLR_RB", reg, expected=0)
            await restore_uart(self, wrap)
            await self.csr_read(f"S10_W{wrap}_UART_EN_RB", wrap_ctrl_reg(wrap), expected=0)

    # -- body ------------------------------------------------------------

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        self._setup()
        await self.csr_read("S1_W0_EN", engine_reg(0, "CTRL"))
        self._term("SETUP")

        others = await self._reset_reads()
        await self._register_rw(others)
        await self._loopback()

        orders = []
        drain_reads = []
        self._zeroed = set()
        for wrap in range(self.wraps):
            order, reads = await self._all16(wrap)
            orders.append(order)
            drain_reads.append(reads)
        self._term("ALL16")
        for wrap in range(self.wraps):
            for slot, length in enumerate(_LENS):
                await self._await_clear(wrap, slot, length, "S6")
                self.hwclr_elements += 1
            quiet = await self._lsr(wrap, "S6_QUIET")
            assert quiet & LSR_DR == 0, (
                f"S6 wrapper {wrap}: the receiver reports data (LSR 0x{quiet:02x}) after the "
                f"last expected byte"
            )
            status = await self.csr_read(f"S6_W{wrap}_INTR", engine_reg(wrap, "INTR_STATUS"))
            assert status == 0, f"S6 wrapper {wrap}: INTR_STATUS 0x{status:08x} after the transfer"
        self._term("CLEARED")
        total = self.wraps * sum(_LENS)
        assert self.bytes_checked == total and self.hwclr_elements == self.wraps * NUM_LOG_ENTRIES
        assert all(self._inflight.get(w, 0) > 0 for w in range(self.wraps)), (
            f"in-flight LOG_CTRL samples per wrapper {self._inflight}: a wrapper had none"
        )
        inflight_s5 = dict(self._inflight)
        samples_s5 = self._len_samples
        cocotb.log.info(
            "CHK-LOG-ENGINE-TRANSFER-BYTES: %d wrappers x 16 one-word slots, %d/%d bytes in "
            "place, lens %s, order %s; other receivers DR=0 on %d samples",
            self.wraps,
            self.bytes_checked,
            total,
            _LENS,
            " ".join(f"w{w}={o}" for w, o in enumerate(orders)),
            self._other_dr_samples,
        )
        cocotb.log.info(
            "CHK-LE-FIFO-DRAIN: %d wrappers x %d bytes > 32-entry FIFO, <%s> LSR reads, "
            "OE/PE/FE/BI=0 on %d samples",
            self.wraps,
            sum(_LENS),
            ",".join(str(r) for r in drain_reads),
            self._lsr_samples,
        )
        cocotb.log.info(
            "CHK-LOG-ENGINE-TRANSFER-HWCLR: %d/%d LOG_CTRL elements (16 x %d wrappers, one-word "
            "slots) written non-zero then read 0 after completion, 0 software clears",
            self.hwclr_elements,
            self.wraps * NUM_LOG_ENTRIES,
            self.wraps,
        )

        firsts = []
        enabled_reads = []
        pending = 0
        for wrap in range(self.wraps):
            self._zeroed = set()
            first, reads = await self._hold_then_enable(wrap)
            firsts.append(first)
            enabled_reads.append(reads)
            pending += NUM_LOG_ENTRIES
        self._term("HOLD-ENABLE")
        cocotb.log.info(
            "CHK-LE-LEN-PENDING: %d samples in {L_i, 0}, 0 partial, 0 re-rise; in-flight hits "
            "w0..w3=<%s>; pending %d/%d read 1 (S5 samples %d)",
            self._len_samples,
            ",".join(str(inflight_s5.get(w, 0)) for w in range(self.wraps)),
            pending,
            self.wraps * NUM_LOG_ENTRIES,
            samples_s5,
        )
        cocotb.log.info(
            "CHK-LE-ENABLE-GATE: %d wrappers, EN=0 hold %d LSR reads DR=0, 16/16 LOG_CTRL=1 "
            "kept; EN=1 first char after <%s> reads, 16/16 headers delivered and cleared, "
            "E_N=<%s>",
            self.wraps,
            _HOLD_READS,
            ",".join(str(f) for f in firsts),
            ",".join(str(e) for e in enabled_reads),
        )

        await self._outbound_fetch()

        cleared = await self._intr_test()
        self._term("INTR-TEST")
        cocotb.log.info(
            "CHK-LOG-ENGINE-TRANSFER-CLEAN: clean INTR_STATUS=0 x%d; INTR_TEST bit0/bit4 set, "
            "W0 kept, W1C cleared, %d/%d",
            self.wraps,
            cleared,
            2 * self.wraps,
        )

        await self._restore()
        self._term("RESTORED")

        sb = getattr(getattr(self, "env", None), "scoreboard", None)
        assert sb is not None, "no scoreboard on this sequence's env"
        assert sb.sys_axi_checks_seen >= self.accesses, (
            f"the scoreboard checked {sb.sys_axi_checks_seen} SEP_IN items, this sequence "
            f"issued {self.accesses}"
        )
        assert [t for t, _, _ in self._terms] == list(_TERMS), f"fence {self._terms}"
        times = [t for _, t, _ in self._terms]
        assert times == sorted(times) and len(set(times)) == len(times), f"fence {self._terms}"
        cocotb.log.info(
            "CHK-NONVAC: %s (counts and times per term: %s)",
            " < ".join(_TERMS),
            ", ".join(f"{t}={c}@{ns}ns" for t, ns, c in self._terms),
        )
        self._wait(
            "SEP_IN access",
            f"{self.cfg.axi_timeout_ns} ns",
            self.accesses,
            "every access answered",
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, bound/last-state per wait, 0 expired; %s",
            sum(entry[0] for entry in self._waits.values()),
            "; ".join(
                f"{kind} x{n} bound {bound} max used {used} last {last}"
                for kind, (n, bound, used, last) in self._waits.items()
            ),
        )
