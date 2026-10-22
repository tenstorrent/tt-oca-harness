# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_B4_014 ANCHOR: smc_mailbox_irq_test
# DV-TESTCASE-CONTRACT-REVISION: 1 RECORD-SHA256: a6493973ba532cb271a89c12f02a49734e1ec711636622983e9c559f6292b8f0
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/docs/SMC_VPLAN.adoc section 146 `smc_mailbox_irq_test` ENV: cocotb
"""Mailbox CSR and IRQ-control smoke over real SYS AXI, and the write and read
threshold interrupts of every mailbox pair on the external mailbox interrupt output.

Every address and bit on the proof path is imported by symbol from the
generated PeakRDL headers (``smc_addr.h`` for the register bases,
``smc_base_config.h`` for the clock-gate enable, ``axil_mailbox_smc_wrap.h``
for the mailbox field masks) ([ADDRESS-FROM-AUTHORITATIVE-MAP]).
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import _REPO, _field_mask, smc_addr
from .smc_base_test_seq import smc_base_test_seq

# smc_addr_map.py exposes no accessor for these two generated headers;
# `_field_mask` parses them directly.
_SMC_BASE_CFG_H = (
    _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "smc_base_config.h"
)
_AXIL_MAILBOX_H = (
    _REPO / "hw" / "ip" / "axi_lite_mailbox_unit" / "regs" / "gen" / "c" / "axil_mailbox_smc_wrap.h"
)

_CPU_CTRL_H = _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "cpu_ctrl.h"

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
MAILBOX_CG_EN = _field_mask(
    _SMC_BASE_CFG_H, "SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__MAILBOX_CG_EN_bm"
)

#: MailboxDepth of the SMC integration, from the peripheral parameter table in
#: `hw/sys/smc/doc/periphs.adoc` (SMC Peripheral Parameter Overrides: Mailbox
#: `MailboxDepth`, IP default 8, SMC value 2). The threshold clamp below is
#: computed from this value; the depth CPU_CTRL.SMC_ATTRIBUTES publishes to
#: software is compared against it, not used in its place.
MAILBOX_DEPTH = 2
SMC_ATTRIBUTES = smc_addr("SMC_TOP_SMC_CPU_CTRL_SMC_ATTRIBUTES_BASE_ADDR")
MAILBOX_DEPTH_BM = _field_mask(_CPU_CTRL_H, "CPU_CTRL__SMC_ATTRIBUTES__MAILBOX_DEPTH_bm")
MAILBOX_DEPTH_BP = _field_mask(_CPU_CTRL_H, "CPU_CTRL__SMC_ATTRIBUTES__MAILBOX_DEPTH_bp")

MAILBOX_STATUS = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_STATUS_BASE_ADDR")
MAILBOX_ERROR_FLAGS = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_ERROR_FLAGS_BASE_ADDR")
MAILBOX_WIRQT = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_WIRQT_BASE_ADDR")
MAILBOX_RIRQT = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_RIRQT_BASE_ADDR")
MAILBOX_IRQEN = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_IRQEN_BASE_ADDR")

# Idle STATUS of an untouched mailbox, per field ([EXACT-EXPECTATION]): the
# read FIFO is empty (``EMPTY`` is defined as "1: Data is not available to read" in
# axil_mailbox.rdl) and FULL / WRITE_LEVEL_ABOVE_THRESH / READ_LEVEL_ABOVE_THRESH
# are all 0, as is the rest of the 64-bit read-only register.
MAILBOX_STATUS_IDLE = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__STATUS__EMPTY_bm")
# ERROR_FLAGS: no read-from-empty / write-to-full has been attempted yet, so
# both sticky flags (READ_ERROR, WRITE_ERROR) must still be clear.
MAILBOX_ERROR_FLAGS_IDLE = 0

# IRQEN is a plain rw enable register (eirq/rtirq/wtirq), so its readback is an
# exact mirror of what was written.
#
# WIRQT / RIRQT are threshold registers with a SPEC-defined clamp: "When a value
# larger than or equal to the MailboxDepth parameter is written to this register,
# it gets reduced to MailboxDepth - 1" (axil_mailbox register spec, WIRQT/RIRQT
# field descriptions in regs/axil_mailbox.rdl and the generated
# regs/gen/adoc/axil_mailbox_smc_wrap.adoc; the depth parameter itself is
# documented in hw/ip/axi_lite_mailbox_unit/doc/architecture.adoc). So the exact
# readback is `min(written, MAILBOX_DEPTH - 1)` -- a stated exact expectation
# that an all-zero dead register fails ([EXACT-EXPECTATION]). Their
# restore-to-0 leg is exact either way (0 is always in range).
CLAMPED_THRESHOLD = "clamped-to-depth"


def clamped_threshold(written: int, depth: int) -> int:
    """SPEC clamp of a WIRQT/RIRQT write for a mailbox of ``depth`` entries."""
    return written if written < depth else depth - 1


IRQEN_PATTERN = (
    _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__IRQEN__EIRQ_bm")
    | _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__IRQEN__RTIRQ_bm")
    | _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__IRQEN__WTIRQ_bm")
)

WRITE_READBACK = [
    ("WIRQT", MAILBOX_WIRQT, 0x5, CLAMPED_THRESHOLD),
    ("RIRQT", MAILBOX_RIRQT, 0x6, CLAMPED_THRESHOLD),
    ("IRQEN", MAILBOX_IRQEN, IRQEN_PATTERN, IRQEN_PATTERN),
]


# Directed, non-polling access count of `body()`; the callers' protocol-VIP
# stimulus floors are minima below this.
EXPECTED_ACCESSES = 24


class smc_mailbox_irq_test_seq(smc_base_test_seq):
    """Exercise mailbox status and IRQ-control registers."""

    def __init__(self, name: str = "smc_mailbox_irq_test_seq") -> None:
        super().__init__(name)
        self.clock_gate_value: int = 0
        self.accesses = 0

    async def _read(self, name: str, addr: int, expected: int | None = None) -> int:
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 8
        item.expected = expected
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        return item.rdata

    async def _write(self, name: str, addr: int, data: int) -> None:
        item = SmcSysAxiItem(f"wr_{name}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 8
        item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1

    async def body(self) -> None:
        self.clock_gate_value = await self._read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        enabled = self.clock_gate_value | MAILBOX_CG_EN
        await self._write("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL, enabled)
        await self._read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL, expected=enabled)

        # Exact idle expectations: a non-idle STATUS or any sticky error flag on
        # an untouched mailbox fails in the scoreboard value compare instead
        # of only proving the access returned OKAY.
        await self._read("MAILBOX_STATUS", MAILBOX_STATUS, expected=MAILBOX_STATUS_IDLE)
        await self._read(
            "MAILBOX_ERROR_FLAGS", MAILBOX_ERROR_FLAGS, expected=MAILBOX_ERROR_FLAGS_IDLE
        )

        # The depth the DUT publishes must be the documented integration value;
        # the clamp expectation is computed from the documented value.
        attrs = await self._read("SMC_ATTRIBUTES", SMC_ATTRIBUTES)
        published_depth = (attrs & MAILBOX_DEPTH_BM) >> MAILBOX_DEPTH_BP
        assert published_depth == MAILBOX_DEPTH, (
            f"CPU_CTRL.SMC_ATTRIBUTES.MAILBOX_DEPTH reads {published_depth} "
            f"(SMC_ATTRIBUTES=0x{attrs:x}); the SMC peripheral parameter table gives "
            f"MailboxDepth={MAILBOX_DEPTH}"
        )
        depth = MAILBOX_DEPTH

        clamped: list[tuple[str, int, int]] = []
        for name, addr, pattern, readback in WRITE_READBACK:
            if readback == CLAMPED_THRESHOLD:
                expected = clamped_threshold(pattern, depth)
                clamped.append((name, pattern, expected))
            else:
                expected = readback
            await self._write(name, addr, pattern)
            await self._read(name, addr, expected=expected)
        cocotb.log.info(
            "CHK-MAILBOX-IRQT-CLAMP: MailboxDepth=%d from the SMC peripheral parameter "
            "table, and CPU_CTRL.SMC_ATTRIBUTES publishes %d; %s each read back the SPEC "
            "clamp min(written, depth-1) exactly",
            depth,
            published_depth,
            ", ".join(f"{n} (wrote 0x{w:x}, expected 0x{e:x})" for n, w, e in clamped),
        )

        # In-range leg. Every threshold write above is >= depth, so all of them
        # clamp, and a register that returned depth-1 for any write -- or
        # ignored writes entirely -- satisfied them all. Writing depth-1, the
        # largest value the SPEC does NOT clamp, must read back unchanged.
        in_range = depth - 1
        for name, addr, _pattern, readback in WRITE_READBACK:
            if readback != CLAMPED_THRESHOLD:
                continue
            await self._write(f"{name}_IN_RANGE", addr, in_range)
            await self._read(f"{name}_IN_RANGE", addr, expected=in_range)
        cocotb.log.info(
            "CHK-MAILBOX-IRQT-IN-RANGE: WIRQT/RIRQT took 0x%x (depth-1, the "
            "largest unclamped value) back exactly, so the clamp above is a "
            "clamp and not a register stuck at depth-1",
            in_range,
        )

        for name, addr, _pattern, _readback in reversed(WRITE_READBACK):
            await self._write(f"{name}_RESTORE", addr, 0)
            await self._read(f"{name}_RESTORE", addr, expected=0)

        await self._write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, self.clock_gate_value)
        await self._read(
            "CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, expected=self.clock_gate_value
        )
        # 19 mailbox/clock-gate accesses, the SMC_ATTRIBUTES read compared with
        # the documented depth, and the two in-range write/readback pairs.
        assert self.accesses == EXPECTED_ACCESSES, (
            f"mailbox CSR access sequence issued {self.accesses} accesses, "
            f"expected {EXPECTED_ACCESSES}"
        )


#: Mailbox pairs of the SMC integration: `NumMailboxes` 32 in the SMC peripheral
#: parameter table (`hw/sys/smc/doc/periphs.adoc`), one bit per pair on
#: `smc_ext_mailbox_interrupts_o[NumMailboxes-1:0]` (`hw/sys/smc/doc/port_table.adoc`).
NUM_MAILBOX_PAIRS = 32
#: Per-cycle liveness ceiling of every external-vector poll, in clk_smc_i cycles.
#: No SPEC latency exists for this path; expiry fails the leaf with the last vector.
EXT_POLL_BOUND = 128
WTIRQ = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__IRQS__WTIRQ_bm")
RTIRQ = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__IRQS__RTIRQ_bm")
IRQEN_WTIRQ = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__IRQEN__WTIRQ_bm")
IRQEN_RTIRQ = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__IRQEN__RTIRQ_bm")
WRITE_WORD_BASE = 0x5717_0000_0000_0000
READ_WORD_BASE = 0x7A1D_0000_0000_0000
EXT_FENCE_TERMS = ("WIRQ-RAISE", "WIRQ-CLEAR", "RIRQ-RAISE", "RIRQ-CLEAR")


def _pair_addr(direction: str, pair: int, reg: str) -> int:
    return smc_addr(f"SMC_TOP_SMC_MAILBOX_{direction}_MAILBOX_{pair}_{reg}_BASE_ADDR")


@dataclass
class _BoundedWait:
    """One bounded wait: its bound, whether expiry is tolerated, and what it last saw."""

    name: str
    bound: int
    unit: str
    allow_timeout: bool = False
    timed_out: bool = False
    used: int = 0
    last: str = "not sampled"


class smc_mailbox_ext_irq_seq(smc_base_test_seq):
    """Raise and acknowledge the write and read threshold interrupt of every mailbox pair's
    outbound aperture and follow `tb_ext_mailbox_interrupts`.

    The outbound port of mailbox m is at `0xC001_8000 + m * 0x1000`, its inbound partner
    `0x800` above it, and the 32 outbound-port interrupts leave the SMC on
    `smc_ext_mailbox_interrupts_o` (`axi_lite_mailbox_unit/doc/index.adoc`). Which bit each
    pair drives is not specified (SF-032), so the pair-to-bit map is measured and logged and
    only its one-hot shape and distinctness are compared.
    """

    def __init__(self, name: str = "smc_mailbox_ext_irq_seq") -> None:
        super().__init__(name)
        self.accesses = 0
        self.existing: tuple[str, int, int] | None = None
        self.fence: list[tuple[str, int, int]] = []
        self.waits: list[_BoundedWait] = []
        self.axi_items: list[SmcSysAxiItem] = []
        self.wirq_map: dict[int, int] = {}
        self.rirq_map: dict[int, int] = {}

    def _stamp(self, term: str, count: int) -> None:
        self.fence.append((term, count, int(get_sim_time("ns"))))

    async def _access(self, tag: str, addr: int, data: int | None, expected: int | None):
        item = SmcSysAxiItem(f"{'rd' if data is None else 'wr'}_{tag}")
        item.op = SmcSysAxiOp.READ if data is None else SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 8
        item.expected = expected
        if data is not None:
            item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self.axi_items.append(item)
        assert item.resp_ok and not item.timed_out and item.resp_code == 0, (
            f"{tag}: SEP_IN access did not complete OKAY (resp={item.resp_code}, "
            f"timed_out={item.timed_out})"
        )
        return item

    async def _rd(self, tag: str, addr: int, expected: int | None = None) -> int:
        item = await self._access(tag, addr, None, expected)
        assert isinstance(item.rdata, int), f"{tag}: unresolved read data"
        if expected is not None:
            assert item.rdata == expected, f"{tag}: read 0x{item.rdata:x}, want 0x{expected:x}"
        return item.rdata

    async def _wr(self, tag: str, addr: int, data: int) -> None:
        await self._access(tag, addr, data, None)

    @staticmethod
    def _ext_vector() -> int:
        raw = cocotb.top.tb_ext_mailbox_interrupts.value
        assert raw.is_resolvable, f"tb_ext_mailbox_interrupts is not resolvable (X/Z): {raw}"
        return int(raw)

    async def _poll_ext(self, name: str, done) -> int:
        """Sample the vector every clk_smc_i cycle until ``done(vector)``; expiry raises."""
        wait = _BoundedWait(name, EXT_POLL_BOUND, "clk_smc_i cycles")
        self.waits.append(wait)
        for i in range(wait.bound):
            vec = self._ext_vector()
            wait.used = i + 1
            wait.last = f"tb_ext_mailbox_interrupts=0x{vec:08x}"
            if done(vec):
                cocotb.log.info(
                    "WAIT %s: bound=%d %s allow_timeout=%s timed_out=%s used=%d last=%s",
                    wait.name,
                    wait.bound,
                    wait.unit,
                    wait.allow_timeout,
                    wait.timed_out,
                    wait.used,
                    wait.last,
                )
                return vec
            await ClockCycles(cocotb.top.clk_smc_i, 1)
        wait.timed_out = True
        cocotb.log.info(
            "WAIT %s: expired after bound=%d %s allow_timeout=%s timed_out=%s last=%s",
            wait.name,
            wait.bound,
            wait.unit,
            wait.allow_timeout,
            wait.timed_out,
            wait.last,
        )
        if not wait.allow_timeout:
            raise AssertionError(
                f"{wait.name}: condition not met within {wait.bound} {wait.unit}; "
                f"last observed {wait.last}"
            )
        return self._ext_vector()

    def _rising_bit(self, tag: str, baseline: int, vec: int) -> int:
        diff = vec ^ baseline
        assert diff and diff & (diff - 1) == 0 and vec & diff, (
            f"{tag}: tb_ext_mailbox_interrupts 0x{vec:08x} against baseline 0x{baseline:08x}; "
            "want exactly one bit rising with every other bit at baseline"
        )
        return diff.bit_length() - 1

    async def _raise(
        self, kind: str, pair: int, baseline: int, writer: str, word: int, irqs_bit: int
    ) -> int:
        out = "OUTBOUND"
        tag = f"{kind}{pair}"
        start = self.accesses
        cocotb.log.info("STEP %s: pair %d %sIRQ raise", "S2" if kind == "W" else "S4", pair, kind)
        await self._wr(f"{tag}_THRESH", _pair_addr(out, pair, f"{kind}IRQT"), 0)
        enable = IRQEN_WTIRQ if kind == "W" else IRQEN_RTIRQ
        await self._wr(f"{tag}_IRQEN", _pair_addr(out, pair, "IRQEN"), enable)
        lc = f"CHK-MAILBOX-EXT-{kind}IRQ"
        await self._wr(f"{tag}_PUSH", _pair_addr(writer, pair, "WRITE_DATA"), word)
        cocotb.log.info(
            "LIFECYCLE %s set: pair %d %sIRQT=0 IRQEN=0x%x, one word written to %s WRITE_DATA",
            lc,
            pair,
            kind,
            enable,
            writer,
        )
        vec = await self._poll_ext(f"{tag}_RAISE", lambda v: v != baseline)
        bit = self._rising_bit(f"{tag}_RAISE", baseline, vec)
        irqs = await self._rd(f"{tag}_IRQS", _pair_addr(out, pair, "IRQS"))
        irqp = await self._rd(f"{tag}_IRQP", _pair_addr(out, pair, "IRQP"))
        assert irqs & irqs_bit, f"{tag}: IRQS reads 0x{irqs:x}, want bit 0x{irqs_bit:x} set"
        held = self._ext_vector()
        assert held == vec, (
            f"{tag}: tb_ext_mailbox_interrupts moved 0x{vec:08x} -> 0x{held:08x} while the "
            "interrupt was pending"
        )
        cocotb.log.info(
            "LIFECYCLE %s observed: pair %d IRQS=0x%x IRQP=0x%x tb_ext_mailbox_interrupts=0x%08x "
            "bit %d",
            lc,
            pair,
            irqs,
            irqp,
            vec,
            bit,
        )
        self._stamp(f"{kind}IRQ-RAISE({pair})", self.accesses - start)
        return bit

    async def _clear(
        self, kind: str, pair: int, baseline: int, reader: str, word: int, irqs_bit: int
    ) -> None:
        out = "OUTBOUND"
        tag = f"{kind}{pair}"
        start = self.accesses
        lc = f"CHK-MAILBOX-EXT-{kind}IRQ"
        cocotb.log.info("STEP %s: pair %d %sIRQ clear", "S3" if kind == "W" else "S5", pair, kind)
        await self._rd(f"{tag}_POP", _pair_addr(reader, pair, "READ_DATA"), expected=word)
        await self._wr(f"{tag}_ACK", _pair_addr(out, pair, "IRQS"), irqs_bit)
        cocotb.log.info(
            "LIFECYCLE %s cleared: pair %d word popped from %s READ_DATA, IRQS written 0x%x",
            lc,
            pair,
            reader,
            irqs_bit,
        )
        await self._poll_ext(f"{tag}_CLEAR", lambda v: v == baseline)
        irqs = await self._rd(f"{tag}_IRQS_CLR", _pair_addr(out, pair, "IRQS"))
        assert not irqs & irqs_bit, (
            f"{tag}: IRQS reads 0x{irqs:x} after the acknowledge, want bit 0x{irqs_bit:x} clear"
        )
        held = self._ext_vector()
        assert held == baseline, (
            f"{tag}: tb_ext_mailbox_interrupts 0x{held:08x} after the acknowledge, want "
            f"baseline 0x{baseline:08x}"
        )
        await self._wr(f"{tag}_IRQEN_OFF", _pair_addr(out, pair, "IRQEN"), 0)
        cocotb.log.info(
            "LIFECYCLE %s checked_cleared: pair %d IRQS=0x%x tb_ext_mailbox_interrupts=0x%08x",
            lc,
            pair,
            irqs,
            held,
        )
        self._stamp(f"{kind}IRQ-CLEAR({pair})", self.accesses - start)

    def _check_map(self, kind: str, bits: dict[int, int]) -> str:
        assert sorted(bits) == list(range(NUM_MAILBOX_PAIRS)), (
            f"{kind}IRQ map covers pairs {sorted(bits)}, want 0..{NUM_MAILBOX_PAIRS - 1}"
        )
        owners: dict[int, list[int]] = {}
        for pair, bit in bits.items():
            owners.setdefault(bit, []).append(pair)
        shared = {b: p for b, p in owners.items() if len(p) > 1}
        assert not shared, f"{kind}IRQ: pairs share an output bit {shared}"
        return " ".join(f"{k}:{bits[k]}" for k in sorted(bits))

    def _nonvac(self) -> None:
        assert self.existing is not None, "EXISTING-LEGS term was not recorded"
        want = ["EXISTING-LEGS"] + [
            f"{t}({k})" for k in range(NUM_MAILBOX_PAIRS) for t in EXT_FENCE_TERMS
        ]
        fence = [self.existing, *self.fence]
        terms = [t for t, _c, _ns in fence]
        assert terms == want, f"fence terms {terms}, want {want}"
        zero = [t for t, c, _ns in fence if c <= 0]
        assert not zero, f"fence terms with zero count {zero}"
        times = [ns for _t, _c, ns in fence]
        assert all(b > a for a, b in zip(times, times[1:])), f"fence times not increasing {times}"
        cocotb.log.info(
            "CHK-NONVAC: EXISTING-LEGS < WIRQ-RAISE(k) < WIRQ-CLEAR(k) < RIRQ-RAISE(k) < "
            "RIRQ-CLEAR(k), for every pair k of %d (%d terms: %s)",
            NUM_MAILBOX_PAIRS,
            len(fence),
            ", ".join(f"{t} count={c} t={ns}ns" for t, c, ns in fence),
        )

    def _timeout_paths(self) -> None:
        bounds = sorted({item.timeout_ns or self.cfg.axi_timeout_ns for item in self.axi_items})
        axi_allow = sum(1 for item in self.axi_items if item.allow_timeout)
        axi_expired = sum(1 for item in self.axi_items if item.timed_out)
        expired = [w.name for w in self.waits if w.timed_out]
        tolerant = [w.name for w in self.waits if w.allow_timeout]
        assert not expired and not tolerant and not axi_expired and not axi_allow, (
            f"bounded waits expired {expired} / tolerating expiry {tolerant}; SEP_IN accesses "
            f"expired {axi_expired} / tolerating expiry {axi_allow}"
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, bound/last-state per wait, %d expired: %s; "
            "%d SEP_IN accesses bound %s ns allow_timeout=%d timed_out=%d; expiry raises "
            "AssertionError with the last observed state",
            len(self.waits),
            len(expired),
            "; ".join(
                f"{w.name} bound={w.bound} {w.unit} allow_timeout={w.allow_timeout} "
                f"timed_out={w.timed_out} used={w.used} last={w.last}"
                for w in self.waits
            ),
            len(self.axi_items),
            bounds,
            axi_allow,
            axi_expired,
        )

    async def body(self) -> None:
        width = len(cocotb.top.tb_ext_mailbox_interrupts)
        assert width == NUM_MAILBOX_PAIRS, (
            f"tb_ext_mailbox_interrupts is {width} bits, want NumMailboxes={NUM_MAILBOX_PAIRS}"
        )
        cg = await self._rd("EXT_CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self._wr("EXT_CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL, cg | MAILBOX_CG_EN)
        await self._rd("EXT_CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL, expected=cg | MAILBOX_CG_EN)

        baseline = self._ext_vector()
        cocotb.log.info(
            "STEP S1: tb_ext_mailbox_interrupts baseline 0x%08x, every FIFO empty and IRQEN 0",
            baseline,
        )
        for pair in range(NUM_MAILBOX_PAIRS):
            wword = WRITE_WORD_BASE | pair
            rword = READ_WORD_BASE | pair
            self.wirq_map[pair] = await self._raise("W", pair, baseline, "OUTBOUND", wword, WTIRQ)
            await self._clear("W", pair, baseline, "INBOUND", wword, WTIRQ)
            self.rirq_map[pair] = await self._raise("R", pair, baseline, "INBOUND", rword, RTIRQ)
            await self._clear("R", pair, baseline, "OUTBOUND", rword, RTIRQ)

        await self._wr("EXT_CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, cg)
        await self._rd("EXT_CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, expected=cg)

        wmap = self._check_map("W", self.wirq_map)
        cocotb.log.info(
            "CHK-MAILBOX-EXT-WIRQ: %d/%d pairs raise one distinct bit and clear it; "
            "map=<%s> (bit assignment SF-032, logged)",
            len(self.wirq_map),
            NUM_MAILBOX_PAIRS,
            wmap,
        )
        rmap = self._check_map("R", self.rirq_map)
        differ = [k for k in self.rirq_map if self.rirq_map[k] != self.wirq_map[k]]
        cocotb.log.info(
            "CHK-MAILBOX-EXT-RIRQ: %d/%d pairs raise one distinct bit and clear it; "
            "map=<%s>; pairs whose read bit differs from the write bit: %s (SF-032, logged)",
            len(self.rirq_map),
            NUM_MAILBOX_PAIRS,
            rmap,
            differ or "none",
        )
        self._nonvac()
        self._timeout_paths()
