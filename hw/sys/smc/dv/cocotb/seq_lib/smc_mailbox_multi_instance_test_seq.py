# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Mailbox multi-instance sweep.

The generated map (``smc_addr.h``) exports one ``*_MAILBOX_<n>_BASE_ADDR``
symbol per instance and direction; the instance count is derived from those
symbols and required to equal the SMC integration value ``periphs.adoc`` gives
for ``NUM_MAILBOXES`` (32, against an IP default of 2). The instances sit at:

  * SMC_MAILBOX_OUTBOUND_MAILBOX_N (smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR") + N * 0x1000)
  * SMC_MAILBOX_INBOUND_MAILBOX_N  (smc_addr("SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_0_BASE_ADDR") + N * 0x1000)

This test reads the STATUS register (offset +0x010 for outbound,
+0x010 for inbound at +0x800 sub-offset) of every instance against its idle
expectation, to prove each mailbox pair's decode is alive, and write/read-backs
IRQEN on mailbox 0 of each direction.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import _REPO, _field_mask, smc_addr, smc_addr_symbols
from .smc_csr_seq_utils import SmcCsrSeq

# Same generated header the sibling `smc_mailbox_irq_test_seq.py:28-31` reads.
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
# `periphs.adoc` ("Peripheral parameter overrides") gives NUM_MAILBOXES = 32 at
# the SMC level, and the two directions must agree with each other and with it.
_SPEC_NUM_MAILBOXES = 32
_OUTBOUND_SYMBOLS = smc_addr_symbols(r"SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_\d+_BASE_ADDR")
_INBOUND_SYMBOLS = smc_addr_symbols(r"SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_\d+_BASE_ADDR")
_MAILBOX_COUNT = len(_OUTBOUND_SYMBOLS)
if _MAILBOX_COUNT != _SPEC_NUM_MAILBOXES or len(_INBOUND_SYMBOLS) != _SPEC_NUM_MAILBOXES:
    raise AssertionError(
        f"generated map exports {len(_OUTBOUND_SYMBOLS)} outbound and "
        f"{len(_INBOUND_SYMBOLS)} inbound mailbox instances; periphs.adoc gives "
        f"NUM_MAILBOXES = {_SPEC_NUM_MAILBOXES}"
    )
# IRQEN is the ONE mailbox register in this block that a CSR test can genuinely
# prove: the RDL (`axil_mailbox.rdl`) declares its three fields `sw = rw;
# hw = r`, plain software-owned storage, so a write/read-back has teeth.
#
# The rest of the mailbox map does NOT, and is not swept, on the same RDL
# attributes:
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
#     from either side, so no generated-model CSR test should be credited with
#     covering them.
_IRQEN_OFFSET = 0x038
_IRQEN_MASK = 0x7

# Interrupt leg on one channel above the low byte. The SMC interrupt-vector map
# (`interrupts.adoc`, "SMC CPU Interrupt Vector Map") gives `mailbox_interrupts`
# one bit per mailbox, 32 wide, and the CSR sweep above only proves that each
# instance decodes. Nothing in the package made an instance raise its own bit,
# so everything past bit 7 of that vector was unobserved. The last instance is
# the far end of it.
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


class smc_mailbox_multi_instance_test_seq(SmcCsrSeq):
    def __init__(self, name: str = "smc_mailbox_multi_instance_test_seq") -> None:
        super().__init__(name)
        #: Vector sampled while inbound mailbox `_IRQ_CHANNEL` was asserted.
        self.irq_vector_asserted = -1

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

    async def body(self) -> None:
        cg = await self.csr_read("CLOCK_GATE_CONTROL", _CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_CONTROL_EN", _CLOCK_GATE_CONTROL, cg | _MAILBOX_CG_EN)
        # Every STATUS read must return OKAY and the idle value: csr_read routes
        # through the scoreboard, which asserts item.resp_ok and compares
        # `expected=`, so a mis-decoded instance (DECERR or bus hang) or a
        # non-idle word fails the test. STATUS is `sw = r; hw = r` in the RDL,
        # so the idle value comes from the generated field mask rather than a
        # generated model; csr_read_bounded would tolerate a dead mailbox.
        for i in range(_MAILBOX_COUNT):
            addr = _OUTBOUND_MAILBOX_BASE + i * _MAILBOX_STRIDE + _STATUS_OFFSET
            await self.csr_read(f"MBOX_OUT_{i}_STATUS", addr, expected=MAILBOX_STATUS_IDLE)
        for i in range(_MAILBOX_COUNT):
            addr = _INBOUND_MAILBOX_BASE + i * _MAILBOX_STRIDE + _STATUS_OFFSET
            await self.csr_read(f"MBOX_IN_{i}_STATUS", addr, expected=MAILBOX_STATUS_IDLE)
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

        await self._prove_channel_raises_its_own_bit()

        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", _CLOCK_GATE_CONTROL, cg)
        # `self.accesses` is bumped by this sequence's own csr_* calls, so
        # asserting it against a literal only restates the loops above and
        # cannot fail on anything the DUT did ([NO-ALWAYS-PASS-CHECKER]).
        # `assert_all_reachable` cross-checks the same count against the
        # scoreboard instead.
        self.assert_all_reachable(3 + 2 * _MAILBOX_COUNT + 10 + 10, "MAILBOX_MULTI_INSTANCE")
