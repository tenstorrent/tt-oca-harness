# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Mailbox multi-instance sweep.

The generated map (``smc_addr.h``) exports one ``*_MAILBOX_<n>_BASE_ADDR``
symbol per instance and direction; the instance count is derived from those
symbols and required to equal the SMC integration value ``periphs.adoc`` gives
for ``NumMailboxes`` (32, against an IP default of 2). The instances sit at:

  * SMC_MAILBOX_OUTBOUND_MAILBOX_N (smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR") + N * 0x1000)
  * SMC_MAILBOX_INBOUND_MAILBOX_N  (smc_addr("SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_0_BASE_ADDR") + N * 0x1000)

This test reads the STATUS register (offset +0x010 for outbound,
+0x010 for inbound at +0x800 sub-offset) of every instance against its idle
expectation, to prove each mailbox pair's decode is alive, and write/read-backs
IRQEN on mailbox 0 of each direction.

It then takes every one of the 64 apertures through the access results of
``axi_lite_mailbox_unit/doc/interface.adoc`` (Access Results): writes to the
read-only ``READ_DATA``, ``STATUS``, ``ERROR_FLAGS`` and ``IRQP`` answer
``SLVERR`` and are ignored, an empty ``READ_DATA`` read answers ``SLVERR`` with
low data word 0xFEEDDEAD and sets the read-error flag and ``IRQS[2]``, and an
``ERROR_FLAGS`` read returns and clears the flags; back-to-back and pipelined
empty reads, and an ``ERROR_FLAGS`` read pipelined behind an empty read, close
the sequence. Values the document does not state (SF-030, SF-032, SF-033) are
printed without a compare.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge, SimTimeoutError, with_timeout
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import _REPO, _field_mask, smc_addr, smc_addr_symbols
from .smc_csr_seq_utils import SmcCsrSeq

# Same generated header the sibling `smc_mailbox_irq_test_seq.py` reads.
_AXIL_MAILBOX_H = (
    _REPO / "hw" / "ip" / "axi_lite_mailbox_unit" / "regs" / "gen" / "c" / "axil_mailbox_smc_wrap.h"
)
# Idle STATUS of an untouched mailbox, per field from the generated header --
# the same constant the sibling `smc_mailbox_irq_test_seq.py` compares
# against. EMPTY is "1: Data is not available to read" (axil_mailbox.rdl), and
# FULL / *_LEVEL_ABOVE_THRESH are 0.
MAILBOX_STATUS_IDLE = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__STATUS__EMPTY_bm")

_CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
_MAILBOX_CG_EN = 1 << 1

_OUTBOUND_MAILBOX_BASE = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR")
_INBOUND_MAILBOX_BASE = smc_addr("SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_0_BASE_ADDR")
_MAILBOX_STRIDE = 0x1000
_STATUS_OFFSET = 0x010

# Instance count from the generated map, one symbol per instance and direction.
# `periphs.adoc` ("Peripheral parameter overrides") gives NumMailboxes = 32 at
# the SMC level, and the two directions must agree with each other and with it.
_SPEC_NUM_MAILBOXES = 32
_OUTBOUND_SYMBOLS = smc_addr_symbols(r"SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_\d+_BASE_ADDR")
_INBOUND_SYMBOLS = smc_addr_symbols(r"SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_\d+_BASE_ADDR")
_MAILBOX_COUNT = len(_OUTBOUND_SYMBOLS)
if _MAILBOX_COUNT != _SPEC_NUM_MAILBOXES or len(_INBOUND_SYMBOLS) != _SPEC_NUM_MAILBOXES:
    raise AssertionError(
        f"generated map exports {len(_OUTBOUND_SYMBOLS)} outbound and "
        f"{len(_INBOUND_SYMBOLS)} inbound mailbox instances; periphs.adoc gives "
        f"NumMailboxes = {_SPEC_NUM_MAILBOXES}"
    )
# IRQEN's three fields are `sw = rw; hw = r` (`axil_mailbox.rdl`), plain
# software-owned storage, so a write/read-back compares the written word. The
# rest of the mailbox map takes no write/read-back, on the same RDL attributes:
#   * `IRQS` fields are `sw = rw; hw = r` but their description makes a write
#     an acknowledge ("Acknowledge and clear interrupt request") -- software
#     can never set a bit, only clear one
#   * `IRQP` is `sw = r; hw = r`, "the current status of the interrupts sent to
#     the CPU", a read-only view of IRQS gated by IRQEN
#   * `CTRL` fields are `sw = w`, write-only flush strobes, so a readback is
#     never the written value
#   * `WIRQT`/`RIRQT` are `sw = rw` but their description clamps any written
#     value >= MailboxDepth to MailboxDepth - 1; with the SMC depth of 2
#     (`periphs.adoc`, MAILBOX_DEPTH) every value >= 2 reads back as 1 -- one
#     bit of information
#   * `STATUS`/`READ_DATA`/`ERROR` are declared `sw = r; hw = r`: unwritable
#     from either side.
_IRQEN_OFFSET = 0x038
_IRQEN_MASK = 0x7

# Interrupt leg on one channel above the low byte. The SMC interrupt-vector map
# (`interrupts.adoc`, "SMC CPU Interrupt Vector Map") gives `mailbox_interrupts`
# one bit per mailbox, 32 wide, and the CSR sweep above only proves that each
# instance decodes. The last instance sits at the far end of that vector, so
# raising its bit shows the vector is wired to full width.
_IRQ_CHANNEL = _MAILBOX_COUNT - 1
_WRITE_DATA_OFFSET = 0x000
_IRQS_OFFSET = 0x030
_IRQP_OFFSET = 0x040
_CTRL_OFFSET = 0x048
_IRQEN_WTIRQ = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__IRQEN__WTIRQ_bm")
_IRQS_WTIRQ = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__IRQS__WTIRQ_bm")
_IRQP_WTIRQ = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__IRQP__WTIRQ_bm")
_STATUS_WRITE_ABOVE = _field_mask(
    _AXIL_MAILBOX_H, "AXIL_MAILBOX__STATUS__WRITE_LEVEL_ABOVE_THRESH_bm"
)
_STATUS_FULL = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__STATUS__FULL_bm")
_CTRL_WFLUSH = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__CTRL__WFLUSH_bm")
# `periphs.adoc` ("Peripheral parameter overrides") gives MAILBOX_DEPTH = 2 at
# the SMC level; the STATUS expectation after one push is built from that
# value, and CPU_CTRL.SMC_ATTRIBUTES, which publishes the integration's depth
# to software, is read back and required to agree with it.
_SPEC_MAILBOX_DEPTH = 2
_CPU_CTRL_H = _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "cpu_ctrl.h"
_SMC_ATTRIBUTES = smc_addr("SMC_TOP_SMC_CPU_CTRL_SMC_ATTRIBUTES_BASE_ADDR")
_MAILBOX_DEPTH_BM = _field_mask(_CPU_CTRL_H, "CPU_CTRL__SMC_ATTRIBUTES__MAILBOX_DEPTH_bm")
_MAILBOX_DEPTH_BP = _field_mask(_CPU_CTRL_H, "CPU_CTRL__SMC_ATTRIBUTES__MAILBOX_DEPTH_bp")
# WIRQT resets to 0 and its RDL description raises the write threshold IRQ
# "when the usage pointer of the FIFO connected to the W channel exceeds this
# value", so one pushed word is already above the threshold and no WIRQT
# programming is needed.
_IRQ_PATTERN = 0xA5A5_5A5A_1234_5678
# Liveness ceiling on WRITE_DATA push -> IRQS -> IRQP -> mailbox_interrupts.
# Expiry is a FAILURE carrying the last observed vector.
_IRQ_BOUND_CYCLES = 128


# Access-result legs. Register addresses come per aperture from the generated
# map; the expected codes and words come from the Access Results table of
# `axi_lite_mailbox_unit/doc/interface.adoc` and the field tables of
# `axil_mailbox.adoc`.
_AXI_OKAY = 0
_AXI_SLVERR = 2
_EMPTY_READ_LOW = 0xFEEDDEAD
_LOW_WORD = 0xFFFF_FFFF
_READ_ERROR = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__ERROR__READ_ERROR_bm")
_IRQS_EIRQ = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__IRQS__EIRQ_bm")
_RO_READ_DATA_WORD = 0x0123_4567_89AB_CDEF
_RO_STATUS_WORD = 0xFFFF_FFFF_FFFF_FFFF
_RO_ERROR_FLAGS_WORD = 0x3
_RO_IRQP_WORD = 0x7
_APERTURES = tuple(
    (f"{tag}{i}", f"SMC_TOP_SMC_MAILBOX_{side}_MAILBOX_{i}")
    for tag, side in (("OUT", "OUTBOUND"), ("IN", "INBOUND"))
    for i in range(_MAILBOX_COUNT)
)
# Apertures of the back-to-back and same-window legs: the last and the first
# instance of each direction.
_B2B_APERTURES = (f"OUT{_MAILBOX_COUNT - 1}", f"IN{_MAILBOX_COUNT - 1}")
_SAME_WINDOW_APERTURES = ("OUT0", "IN0")
_B2B_PAIR = 2
_B2B_PIPELINED = 4
# Liveness ceiling on one group of outstanding accesses; the driver's own
# per-access limit is longer, so expiry here is the reported failure.
_GROUP_BOUND_NS = 40_000
_TERMS = ("IDLE-SWEEP", "RO-WRITES", "RO-EFFECT", "EMPTY-READ", "FLAGS", "RC")
_GLOBAL_TERMS = ("B2B", "SAME-WINDOW")
# Accesses per aperture: S2 4, S3 5, S4 3, S5 2, S6 5, S7 2; per back-to-back
# aperture 6 reads, STATUS and a two-access clean-up; per same-window aperture
# the pre-state read, the pipelined pair, two ERROR_FLAGS reads and the IRQS
# acknowledge.
_PER_APERTURE_ACCESSES = 4 + 5 + 3 + 2 + 5 + 2
_PER_B2B_ACCESSES = _B2B_PAIR + _B2B_PIPELINED + 1 + 2
_PER_SAME_WINDOW_ACCESSES = 1 + 2 + 2 + 1


def _reg(prefix: str, reg: str) -> int:
    return smc_addr(f"{prefix}_{reg}_BASE_ADDR")


class _SepInMonitor:
    """Passive per-clock record of the SEP_IN AR, R and B handshakes."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.cycle = 0
        self.ar: list[int] = []
        self.r: list[tuple[int, int, int]] = []
        self.b: list[tuple[int, int]] = []
        self.unresolved: list[tuple[int, str]] = []

    def _val(self, name: str) -> int | None:
        value = getattr(self.dut, f"s_axi_{name}").value
        return int(value) if value.is_resolvable else None

    async def run(self) -> None:
        clk = self.dut.clk_smc_i
        while True:
            await RisingEdge(clk)
            await ReadOnly()
            self.cycle += 1
            lines = {n: self._val(n) for n in ("arvalid", "arready", "rvalid", "rready")}
            lines.update({n: self._val(n) for n in ("bvalid", "bready")})
            bad = [n for n, v in lines.items() if v is None]
            if bad:
                self.unresolved.append((self.cycle, ",".join(bad)))
                continue
            if lines["arvalid"] and lines["arready"]:
                self.ar.append(self.cycle)
            if lines["rvalid"] and lines["rready"]:
                resp, data = self._val("rresp"), self._val("rdata")
                if resp is None or data is None:
                    self.unresolved.append((self.cycle, "rresp/rdata"))
                else:
                    self.r.append((self.cycle, resp, data))
            if lines["bvalid"] and lines["bready"]:
                resp = self._val("bresp")
                if resp is None:
                    self.unresolved.append((self.cycle, "bresp"))
                else:
                    self.b.append((self.cycle, resp))


class smc_mailbox_multi_instance_test_seq(SmcCsrSeq):
    def __init__(self, name: str = "smc_mailbox_multi_instance_test_seq") -> None:
        super().__init__(name)
        #: Vector sampled while inbound mailbox `_IRQ_CHANNEL` was asserted.
        self.irq_vector_asserted = -1
        self.stamps: dict[str, dict[str, int]] = {t: {} for t in _TERMS}
        self.global_stamps: dict[str, list[int]] = {t: [] for t in _GLOBAL_TERMS}
        self.waits: list[str] = []
        self.mon: _SepInMonitor | None = None

    def _interrupt_vector(self) -> int:
        raw = cocotb.top.tb_mailbox_interrupts.value
        assert raw.is_resolvable, f"tb_mailbox_interrupts is X/Z: {raw}"
        return int(raw)

    async def _await_interrupt_vector(self, want: int, label: str) -> int:
        last = -1
        for cycle in range(1, _IRQ_BOUND_CYCLES + 1):
            await ClockCycles(cocotb.top.clk_smc_i, 1)
            last = self._interrupt_vector()
            if last == want:
                return cycle
        raise AssertionError(
            f"{label}: mailbox_interrupts never reached {want:#010x} within "
            f"{_IRQ_BOUND_CYCLES} clk_smc_i cycles (last {last:#010x})"
        )

    async def _prove_channel_raises_its_own_bit(self) -> None:
        """Inbound mailbox `_IRQ_CHANNEL` raises bit `_IRQ_CHANNEL` and no other.

        The comparisons below are against the WHOLE 32-bit vector, not a masked
        bit: a vector that is one channel wide, that ties the upper channels
        together, or that offsets the index fails on the equality rather than
        passing a per-bit test that another channel also satisfies.
        """
        base = _INBOUND_MAILBOX_BASE + _IRQ_CHANNEL * _MAILBOX_STRIDE
        expected = 1 << _IRQ_CHANNEL
        # STATUS with one word in this port's write FIFO: EMPTY still 1 (nothing
        # was pushed the other way, so this port's READ FIFO is empty),
        # WRITE_LEVEL_ABOVE_THRESH 1 (WIRQT at its reset 0 is exceeded by one
        # word), READ_LEVEL_ABOVE_THRESH 0, and FULL 1 only if the depth is a
        # single entry. Every bit is accounted for from the RDL field
        # descriptions and the periphs.adoc depth; the depth the DUT publishes
        # in SMC_ATTRIBUTES is a compare against that value, not its source.
        attrs = await self.csr_read("SMC_ATTRIBUTES", _SMC_ATTRIBUTES, length=8)
        depth = (attrs & _MAILBOX_DEPTH_BM) >> _MAILBOX_DEPTH_BP
        assert depth == _SPEC_MAILBOX_DEPTH, (
            f"CPU_CTRL.SMC_ATTRIBUTES.MAILBOX_DEPTH reads {depth} "
            f"(SMC_ATTRIBUTES=0x{attrs:x}); periphs.adoc gives MAILBOX_DEPTH = "
            f"{_SPEC_MAILBOX_DEPTH} for the SMC integration"
        )
        status_one_pushed = MAILBOX_STATUS_IDLE | _STATUS_WRITE_ABOVE
        if _SPEC_MAILBOX_DEPTH == 1:
            status_one_pushed |= _STATUS_FULL
        idle = self._interrupt_vector()
        assert idle == 0, (
            f"mailbox_interrupts is {idle:#010x} before this leg pushed anything; "
            f"a later sample would not be attributable to channel {_IRQ_CHANNEL}"
        )
        await self.csr_write(
            f"MBOX_IN_{_IRQ_CHANNEL}_IRQEN_WTIRQ",
            base + _IRQEN_OFFSET,
            _IRQEN_WTIRQ,
            length=8,
        )
        await self.csr_read(
            f"MBOX_IN_{_IRQ_CHANNEL}_IRQEN_WTIRQ_RB",
            base + _IRQEN_OFFSET,
            expected=_IRQEN_WTIRQ,
            length=8,
        )
        # Enabling alone must not raise anything: IRQP is IRQS & IRQEN, so this
        # separates the enable from the event.
        armed = self._interrupt_vector()
        assert armed == 0, (
            f"mailbox_interrupts became {armed:#010x} on the IRQEN write alone, "
            f"before any FIFO push"
        )
        await self.csr_write(
            f"MBOX_IN_{_IRQ_CHANNEL}_WRITE_DATA",
            base + _WRITE_DATA_OFFSET,
            _IRQ_PATTERN,
            length=8,
        )
        latency = await self._await_interrupt_vector(expected, f"MBOX_IN_{_IRQ_CHANNEL}_PUSH")
        self.irq_vector_asserted = expected
        await self.csr_read(
            f"MBOX_IN_{_IRQ_CHANNEL}_STATUS_ABOVE_THRESH",
            base + _STATUS_OFFSET,
            expected=status_one_pushed,
            length=8,
        )
        await self.csr_read(
            f"MBOX_IN_{_IRQ_CHANNEL}_IRQP",
            base + _IRQP_OFFSET,
            expected=_IRQP_WTIRQ,
            length=8,
        )

        # Disarm and restore. Dropping IRQEN is the deassert leg: it proves the
        # enable gates the output, and it is the only clear that holds while the
        # FIFO is still above threshold -- the RDL describes the threshold IRQ
        # as raised whenever the usage pointer exceeds WIRQT, a level condition
        # an IRQS acknowledge cannot hold down while the word is still queued.
        await self.csr_write(f"MBOX_IN_{_IRQ_CHANNEL}_IRQEN_OFF", base + _IRQEN_OFFSET, 0, length=8)
        await self._await_interrupt_vector(0, f"MBOX_IN_{_IRQ_CHANNEL}_DISARM")
        await self.csr_write(
            f"MBOX_IN_{_IRQ_CHANNEL}_CTRL_WFLUSH", base + _CTRL_OFFSET, _CTRL_WFLUSH, length=8
        )
        await self.csr_write(
            f"MBOX_IN_{_IRQ_CHANNEL}_IRQS_CLEAR", base + _IRQS_OFFSET, _IRQS_WTIRQ, length=8
        )
        await self.csr_read(
            f"MBOX_IN_{_IRQ_CHANNEL}_STATUS_RESTORED",
            base + _STATUS_OFFSET,
            expected=MAILBOX_STATUS_IDLE,
            length=8,
        )
        cocotb.log.info(
            "CHK-MAILBOX-CHANNEL-VECTOR: inbound mailbox %d raised "
            "mailbox_interrupts = %#010x (whole vector, %d clk_smc_i cycles "
            "after the WRITE_DATA push), idle before the push was %#010x and "
            "%#010x with IRQEN armed but nothing pushed; the vector returned to "
            "0 when IRQEN was cleared",
            _IRQ_CHANNEL,
            expected,
            latency,
            idle,
            armed,
        )

    # -- access-result legs ------------------------------------------------

    @staticmethod
    def _now() -> int:
        return int(get_sim_time("ns"))

    def _stamp(self, term: str, aperture: str) -> None:
        self.stamps[term][aperture] = self._now()

    @staticmethod
    def _item(label: str, op: SmcSysAxiOp, addr: int, data: int, error: bool) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"{op.value}_{label}")
        item.op = op
        item.addr = addr
        item.length = 8
        item.wdata = data
        item.expected_resp = _AXI_SLVERR if error else _AXI_OKAY
        item.expect_error = item.allow_error = error
        return item

    @staticmethod
    def _checked(item: SmcSysAxiItem) -> SmcSysAxiItem:
        want = item.expected_resp
        assert item.resp_code == want, (
            f"{item.get_name()} @ 0x{item.addr:x}: resp {item.resp_code}, want {want}"
            f" (rdata=0x{item.rdata:x})"
        )
        if item.op is SmcSysAxiOp.READ:
            assert isinstance(item.rdata, int), (
                f"{item.get_name()}: unresolved read data {item.rdata!r}"
            )
        return item

    async def _acc(
        self, label: str, op: SmcSysAxiOp, addr: int, data: int = 0, error: bool = False
    ) -> SmcSysAxiItem:
        item = self._item(label, op, addr, data, error)
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        return self._checked(item)

    async def _rd(self, label: str, addr: int, error: bool = False) -> int:
        return (await self._acc(label, SmcSysAxiOp.READ, addr, error=error)).rdata

    async def _wr(self, label: str, addr: int, data: int, error: bool = False) -> int:
        item = await self._acc(label, SmcSysAxiOp.WRITE, addr, data, error)
        return item.resp_code

    async def _group(self, label: str, items: list[SmcSysAxiItem]) -> list[int]:
        """Keep ``items`` outstanding together; return the AR handshake cycles of the group."""
        assert self.mon is not None
        ar0, r0 = len(self.mon.ar), len(self.mon.r)
        group = SmcSysAxiGroupItem(label, items)

        async def issue() -> None:
            await self.start_item(group)
            await self.finish_item(group)

        try:
            await with_timeout(issue(), _GROUP_BOUND_NS, "ns")
        except SimTimeoutError as exc:
            ars, rs = len(self.mon.ar) - ar0, len(self.mon.r) - r0
            last = self.mon.r[-1] if self.mon.r else None
            raise AssertionError(
                f"{label}: {len(items) - rs} of {len(items)} reads still outstanding after "
                f"{_GROUP_BOUND_NS} ns ({ars} AR handshakes, {rs} R handshakes; last R record "
                f"{last})"
            ) from exc
        self.waits.append(f"{label}<={_GROUP_BOUND_NS}ns last=R{len(self.mon.r) - r0}")
        self.accesses += len(items)
        for item in items:
            self._checked(item)
        ars = self.mon.ar[ar0:]
        assert len(ars) == len(items) and len(self.mon.r) - r0 == len(items), (
            f"{label}: {len(ars)} AR and {len(self.mon.r) - r0} R handshakes for {len(items)} reads"
        )
        return ars

    def _empty_word(self, label: str, item_or_data) -> int:
        data = item_or_data if isinstance(item_or_data, int) else item_or_data.rdata
        assert data & _LOW_WORD == _EMPTY_READ_LOW, (
            f"{label}: empty READ_DATA returned 0x{data:016x}, low word must be "
            f"0x{_EMPTY_READ_LOW:08x}"
        )
        return data >> 32

    @staticmethod
    def _uniform(label: str, values: dict[str, int]) -> int:
        distinct = sorted(set(values.values()))
        assert len(distinct) == 1, (
            f"{label}: differs between apertures for the same access: "
            + ", ".join(f"{a}=0x{v:x}" for a, v in values.items() if v != distinct[0])
            + f" (others 0x{distinct[0]:x})"
        )
        return distinct[0]

    async def _ro_writes(self) -> None:
        """S2-S4 on every aperture: read-only registers refuse writes with SLVERR."""
        bresp = 0
        status_ok = irqp_ok = 0
        flags_after: dict[str, int] = {}
        irqs_after: dict[str, int] = {}
        flags_clear: dict[str, int] = {}
        for ap, pfx in _APERTURES:
            status_before = await self._rd(f"{ap}_RO_STATUS_PRE", _reg(pfx, "STATUS"))
            codes = [
                await self._wr(
                    f"{ap}_RO_READ_DATA", _reg(pfx, "READ_DATA"), _RO_READ_DATA_WORD, error=True
                ),
                await self._wr(f"{ap}_RO_STATUS", _reg(pfx, "STATUS"), _RO_STATUS_WORD, error=True),
            ]
            status_after = await self._rd(f"{ap}_RO_STATUS_POST", _reg(pfx, "STATUS"))
            assert (status_before, status_after) == (MAILBOX_STATUS_IDLE, MAILBOX_STATUS_IDLE), (
                f"{ap}: STATUS 0x{status_before:x} -> 0x{status_after:x} around the READ_DATA "
                f"and STATUS writes, want 0x{MAILBOX_STATUS_IDLE:x} -> 0x{MAILBOX_STATUS_IDLE:x}"
            )
            status_ok += 1
            irqp_before = await self._rd(f"{ap}_RO_IRQP_PRE", _reg(pfx, "IRQP"))
            codes += [
                await self._wr(
                    f"{ap}_RO_ERROR_FLAGS",
                    _reg(pfx, "ERROR_FLAGS"),
                    _RO_ERROR_FLAGS_WORD,
                    error=True,
                ),
                await self._wr(f"{ap}_RO_IRQP", _reg(pfx, "IRQP"), _RO_IRQP_WORD, error=True),
            ]
            bresp += sum(1 for c in codes if c == _AXI_SLVERR)
            irqp_after = await self._rd(f"{ap}_RO_IRQP_POST", _reg(pfx, "IRQP"))
            flags_after[ap] = await self._rd(f"{ap}_RO_ERROR_FLAGS_POST", _reg(pfx, "ERROR_FLAGS"))
            assert (irqp_before, irqp_after) == (0, 0), (
                f"{ap}: IRQP 0x{irqp_before:x} -> 0x{irqp_after:x} around the ERROR_FLAGS and "
                f"IRQP writes, want 0x0 -> 0x0"
            )
            irqp_ok += 1
            self._stamp("RO-WRITES", ap)
            irqs_after[ap] = await self._rd(f"{ap}_RO_IRQS", _reg(pfx, "IRQS"))
            flags_clear[ap] = await self._rd(f"{ap}_RO_CLEAR_EF", _reg(pfx, "ERROR_FLAGS"))
            await self._wr(f"{ap}_RO_CLEAR_IRQS", _reg(pfx, "IRQS"), _IRQS_EIRQ)
            self._stamp("RO-EFFECT", ap)
        n = len(_APERTURES)
        assert bresp == 4 * n, f"{bresp}/{4 * n} read-only writes answered SLVERR"
        cocotb.log.info(
            "CHK-MBX-RO-WRITE-STATUS: %d apertures, %d/%d BRESP=SLVERR, STATUS 0x%x->0x%x x%d",
            n,
            2 * n,
            2 * n,
            MAILBOX_STATUS_IDLE,
            MAILBOX_STATUS_IDLE,
            status_ok,
        )
        flags_seen = ",".join(f"0x{v:x}" for v in sorted(set(flags_after.values())))
        cocotb.log.info(
            "CHK-MBX-RO-WRITE-FLAGS: %d apertures, %d/%d BRESP=SLVERR, IRQP 0x0->0x0 x%d, "
            "ERROR_FLAGS after=%s (measured, LINKED-ISSUE SF-030)",
            n,
            2 * n,
            2 * n,
            irqp_ok,
            flags_seen,
        )
        flags = self._uniform("ERROR_FLAGS after the read-only writes", flags_after)
        irqs = self._uniform("IRQS after the read-only writes", irqs_after)
        clear = ",".join(f"0x{v:x}" for v in sorted(set(flags_clear.values())))
        cocotb.log.info(
            "CHK-MBX-RO-WRITE-EFFECT: %d apertures, ERROR_FLAGS=0x%x IRQS=0x%x (uniform), "
            "second ERROR_FLAGS read=%s, LINKED-ISSUE SF-030",
            n,
            flags,
            irqs,
            clear,
        )

    async def _empty_reads(self) -> None:
        """S5-S7 on every aperture: empty READ_DATA, its flags, ERROR_FLAGS read-to-clear."""
        upper: dict[str, int] = {}
        flags_ok = rc_ok = 0
        for idx, (ap, pfx) in enumerate(_APERTURES):
            nap, npfx = _APERTURES[(idx + 1) % len(_APERTURES)]
            status = await self._rd(f"{ap}_EMPTY_STATUS", _reg(pfx, "STATUS"))
            assert status & MAILBOX_STATUS_IDLE, (
                f"{ap}: STATUS 0x{status:x} has empty clear before the empty read"
            )
            data = await self._rd(f"{ap}_EMPTY_READ_DATA", _reg(pfx, "READ_DATA"), error=True)
            upper[ap] = self._empty_word(f"{ap}_EMPTY_READ_DATA", data)
            self._stamp("EMPTY-READ", ap)

            irqs = await self._rd(f"{ap}_EMPTY_IRQS", _reg(pfx, "IRQS"))
            n_irqs = await self._rd(f"{ap}_NEIGHBOUR_{nap}_IRQS", _reg(npfx, "IRQS"))
            n_flags = await self._rd(f"{ap}_NEIGHBOUR_{nap}_EF", _reg(npfx, "ERROR_FLAGS"))
            await self._wr(f"{ap}_EMPTY_IRQS_W1C", _reg(pfx, "IRQS"), _IRQS_EIRQ)
            irqs_cleared = await self._rd(f"{ap}_EMPTY_IRQS_CLEARED", _reg(pfx, "IRQS"))
            assert irqs & _IRQS_EIRQ, f"{ap}: IRQS 0x{irqs:x} after the empty read, IRQS[2] clear"
            assert (n_irqs, n_flags) == (0, 0), (
                f"{ap}: neighbour {nap} IRQS 0x{n_irqs:x} ERROR_FLAGS 0x{n_flags:x}, want 0x0 0x0"
            )
            assert irqs_cleared == 0, f"{ap}: IRQS 0x{irqs_cleared:x} after writing 0x4, want 0x0"
            self._stamp("FLAGS", ap)

            first = await self._rd(f"{ap}_EF_FIRST", _reg(pfx, "ERROR_FLAGS"))
            second = await self._rd(f"{ap}_EF_SECOND", _reg(pfx, "ERROR_FLAGS"))
            assert first & _READ_ERROR, f"{ap}: first ERROR_FLAGS 0x{first:x}, read_error clear"
            assert (first, second) == (_READ_ERROR, 0), (
                f"{ap}: ERROR_FLAGS reads 0x{first:x} then 0x{second:x}, want 0x1 then 0x0"
            )
            flags_ok += 1
            rc_ok += 1
            self._stamp("RC", ap)
        n = len(_APERTURES)
        highs = ",".join(f"0x{v:08x}" for v in sorted(set(upper.values())))
        cocotb.log.info(
            "CHK-MBX-EMPTY-READ: %d/%d RRESP=SLVERR data[31:0]=0x%08X, data[63:32]=%s "
            "(measured, LINKED-ISSUE SF-032)",
            len(upper),
            n,
            _EMPTY_READ_LOW,
            highs,
        )
        cocotb.log.info(
            "CHK-MBX-EMPTY-FLAGS: %d apertures, IRQS[2]=1 EF[0]=1, neighbour IRQS=0x0 EF=0x0, "
            "IRQS after W1C=0x0 (neighbour of %s is %s, already cleared)",
            flags_ok,
            _APERTURES[-1][0],
            _APERTURES[0][0],
        )
        cocotb.log.info(
            "CHK-MBX-ERRFLAGS-RC: %d apertures, first=0x%x second=0x0, RRESP OKAY x%d",
            rc_ok,
            _READ_ERROR,
            2 * rc_ok,
        )

    def _read_items(self, label: str, pfx: str, count: int) -> list[SmcSysAxiItem]:
        return [
            self._item(f"{label}_{k}", SmcSysAxiOp.READ, _reg(pfx, "READ_DATA"), 0, True)
            for k in range(count)
        ]

    async def _back_to_back(self) -> None:
        """S8: empty READ_DATA reads back-to-back and pipelined on the last aperture."""
        prefixes = dict(_APERTURES)
        answered = 0
        gaps: dict[str, list[int]] = {}
        for ap in _B2B_APERTURES:
            pfx = prefixes[ap]
            ars: list[int] = []
            for tag, count in (("B2B", _B2B_PAIR), ("PIPE", _B2B_PIPELINED)):
                items = self._read_items(f"{ap}_{tag}", pfx, count)
                ars += await self._group(f"{ap}_{tag}", items)
                for item in items:
                    self._empty_word(item.get_name(), item)
                    answered += 1
            gaps[ap] = [b - a for a, b in zip(ars, ars[1:])]
            status = await self._rd(f"{ap}_B2B_STATUS", _reg(pfx, "STATUS"))
            assert status == MAILBOX_STATUS_IDLE, (
                f"{ap}: STATUS 0x{status:x} after the empty reads, want 0x{MAILBOX_STATUS_IDLE:x}"
            )
            await self._rd(f"{ap}_B2B_CLEAR_EF", _reg(pfx, "ERROR_FLAGS"))
            await self._wr(f"{ap}_B2B_CLEAR_IRQS", _reg(pfx, "IRQS"), _IRQS_EIRQ)
            self.global_stamps["B2B"].append(self._now())
        reads = len(_B2B_APERTURES) * (_B2B_PAIR + _B2B_PIPELINED)
        cocotb.log.info(
            "CHK-MBX-EMPTY-B2B: %d apertures x %d reads, %d/%d SLVERR 0x%08X, STATUS=0x%x "
            "(AR handshake gaps in clk_smc_i cycles: %s)",
            len(_B2B_APERTURES),
            _B2B_PAIR + _B2B_PIPELINED,
            answered,
            reads,
            _EMPTY_READ_LOW,
            MAILBOX_STATUS_IDLE,
            "; ".join(f"{ap} {g}" for ap, g in gaps.items()),
        )

    async def _same_window(self) -> None:
        """S9: an ERROR_FLAGS read pipelined directly behind an empty READ_DATA read."""
        prefixes = dict(_APERTURES)
        seen: list[str] = []
        for ap in _SAME_WINDOW_APERTURES:
            pfx = prefixes[ap]
            pre = await self._rd(f"{ap}_SW_PRE_EF", _reg(pfx, "ERROR_FLAGS"))
            assert pre == 0, f"{ap}: ERROR_FLAGS 0x{pre:x} before the same-window pair, want 0x0"
            empty = self._item(
                f"{ap}_SW_READ_DATA", SmcSysAxiOp.READ, _reg(pfx, "READ_DATA"), 0, True
            )
            ef1 = self._item(f"{ap}_SW_EF1", SmcSysAxiOp.READ, _reg(pfx, "ERROR_FLAGS"), 0, False)
            ars = await self._group(f"{ap}_SW_PAIR", [empty, ef1])
            self._empty_word(empty.get_name(), empty)
            ef2 = self._item(f"{ap}_SW_EF2", SmcSysAxiOp.READ, _reg(pfx, "ERROR_FLAGS"), 0, False)
            await self._group(f"{ap}_SW_EF2", [ef2])
            third = await self._rd(f"{ap}_SW_EF3", _reg(pfx, "ERROR_FLAGS"))
            await self._wr(f"{ap}_SW_CLEAR_IRQS", _reg(pfx, "IRQS"), _IRQS_EIRQ)
            hits = [k for k, it in ((1, ef1), (2, ef2)) if it.rdata & _READ_ERROR]
            assert len(hits) == 1, (
                f"{ap}: read_error in ERROR_FLAGS reads {hits} (0x{ef1.rdata:x}, 0x{ef2.rdata:x}); "
                f"exactly one of the two must carry it"
            )
            assert third == 0, f"{ap}: third ERROR_FLAGS read 0x{third:x}, want 0x0"
            seen.append(
                f"{ap} read {hits[0]} (0x{ef1.rdata:x},0x{ef2.rdata:x}; AR gap {ars[1] - ars[0]})"
            )
            self.global_stamps["SAME-WINDOW"].append(self._now())
        cocotb.log.info(
            "CHK-MBX-ERRFLAGS-RETAIN: %d apertures, flag seen in %s, third read 0x0 "
            "(LINKED-ISSUE SF-033)",
            len(_SAME_WINDOW_APERTURES),
            "; ".join(seen),
        )

    def _fence(self) -> None:
        aps = [ap for ap, _ in _APERTURES]
        for term in _TERMS:
            missing = [ap for ap in aps if ap not in self.stamps[term]]
            assert not missing, f"CHK-NONVAC: term {term} missing on {missing}"
        for ap in aps:
            times = [self.stamps[t][ap] for t in _TERMS]
            assert all(a < b for a, b in zip(times, times[1:])), (
                f"CHK-NONVAC: {ap} terms out of order {dict(zip(_TERMS, times))}"
            )
        last_rc = max(self.stamps["RC"].values())
        b2b, sw = self.global_stamps["B2B"], self.global_stamps["SAME-WINDOW"]
        assert len(b2b) == len(_B2B_APERTURES) and len(sw) == len(_SAME_WINDOW_APERTURES), (
            f"CHK-NONVAC: B2B x{len(b2b)} SAME-WINDOW x{len(sw)}"
        )
        assert last_rc < min(b2b) and max(b2b) < min(sw), (
            f"CHK-NONVAC: RC last {last_rc} ns, B2B {b2b}, SAME-WINDOW {sw}"
        )
        terms = [
            f"{t} x{len(self.stamps[t])} [{min(self.stamps[t].values())}..{max(self.stamps[t].values())} ns]"
            for t in _TERMS
        ] + [f"{t} x{len(v)} [{min(v)}..{max(v)} ns]" for t, v in self.global_stamps.items()]
        cocotb.log.info(
            "CHK-NONVAC: %s (per aperture for the first %d terms)", " < ".join(terms), len(_TERMS)
        )

    async def _access_results(self) -> None:
        self.mon = _SepInMonitor(cocotb.top)
        task = cocotb.start_soon(self.mon.run())
        try:
            await self._ro_writes()
            await self._empty_reads()
            await self._back_to_back()
            await self._same_window()
        finally:
            task.cancel()
        assert not self.mon.unresolved, (
            f"SEP_IN handshake lines unresolved at {self.mon.unresolved[:4]}"
        )
        self._fence()
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, bound/last-state per wait [%s], 0 expired; "
            "every other access is bounded by the driver's per-access limit, which raises",
            len(self.waits),
            "; ".join(self.waits),
        )

    async def body(self) -> None:
        cg = await self.csr_read("CLOCK_GATE_CONTROL", _CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_CONTROL_EN", _CLOCK_GATE_CONTROL, cg | _MAILBOX_CG_EN)
        # Every STATUS read must return OKAY and the idle value: csr_read routes
        # through the scoreboard, which asserts item.resp_ok and compares
        # `expected=`, so a mis-decoded instance (DECERR or bus hang) or a
        # non-idle word fails the test. STATUS is `sw = r; hw = r` in the RDL,
        # so the idle value comes from the generated field mask.
        for i in range(_MAILBOX_COUNT):
            addr = _OUTBOUND_MAILBOX_BASE + i * _MAILBOX_STRIDE + _STATUS_OFFSET
            await self.csr_read(f"MBOX_OUT_{i}_STATUS", addr, expected=MAILBOX_STATUS_IDLE)
            self._stamp("IDLE-SWEEP", f"OUT{i}")
        for i in range(_MAILBOX_COUNT):
            addr = _INBOUND_MAILBOX_BASE + i * _MAILBOX_STRIDE + _STATUS_OFFSET
            await self.csr_read(f"MBOX_IN_{i}_STATUS", addr, expected=MAILBOX_STATUS_IDLE)
            self._stamp("IDLE-SWEEP", f"IN{i}")
        # IRQEN write/read-back/restore on mailbox 0 of each direction; each
        # compare is enforced by the scoreboard and fails on a wrong word.
        for label, base in (
            ("MBOX_OUT_0", _OUTBOUND_MAILBOX_BASE),
            ("MBOX_IN_0", _INBOUND_MAILBOX_BASE),
        ):
            addr = base + _IRQEN_OFFSET
            await self.csr_read(f"{label}_IRQEN_RESET", addr, expected=0)
            await self.csr_write(f"{label}_IRQEN_WR", addr, _IRQEN_MASK)
            await self.csr_read(f"{label}_IRQEN_RB", addr, expected=_IRQEN_MASK)
            await self.csr_write(f"{label}_IRQEN_RESTORE", addr, 0)
            await self.csr_read(f"{label}_IRQEN_RESTORE_RB", addr, expected=0)

        # The access-result legs run before the channel-vector leg: that leg
        # leaves a word in outbound mailbox `_IRQ_CHANNEL`'s read FIFO until
        # the flush, which latches that aperture's RW1C `IRQS.rtirq`, and the
        # read-only-write legs require every aperture to start from reset.
        await self._access_results()

        await self._prove_channel_raises_its_own_bit()

        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", _CLOCK_GATE_CONTROL, cg)
        # `assert_all_reachable` cross-checks the access count against the
        # scoreboard's own count.
        self.assert_all_reachable(
            3
            + 2 * _MAILBOX_COUNT
            + 10
            + 10
            + len(_APERTURES) * _PER_APERTURE_ACCESSES
            + len(_B2B_APERTURES) * _PER_B2B_ACCESSES
            + len(_SAME_WINDOW_APERTURES) * _PER_SAME_WINDOW_ACCESSES,
            "MAILBOX_MULTI_INSTANCE",
        )
