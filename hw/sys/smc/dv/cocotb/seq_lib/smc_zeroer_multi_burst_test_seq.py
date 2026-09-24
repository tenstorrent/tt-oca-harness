# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A zeroer job too large for one AXI burst.

`smc_zeroer_sanity_test` clears eight bytes and its busy probe clears 0x800,
and `hw/sys/smc/doc/zeroer.adoc` describes an operation as an address phase
followed by a data phase, repeated until the size is exhausted. Both of those
sizes fit a single AXI4 burst -- `AxLEN` is eight bits, so a burst carries at
most 256 transfers, which on the 64-bit output path is 0x800 bytes -- so every
enrolled job so far has needed exactly one address phase.

This sequence programs 0x1000 bytes, which no single AXI4 burst can carry, and
so requires the zeroer to return from its data phase to a second address phase
before the job can finish.

The evidence is the job itself rather than the burst count alone: four probe
words spread across both halves of the region -- the first and last word of the
first 0x800 and the first and last word of the second -- are poisoned with
distinct values beforehand and have to read back as zero, and a witness word
immediately past the end of the region has to keep its own poison, so a job
that stopped after one burst, ran past its size, or wrote the wrong half fails.
The output responder's write-transaction counter is required to advance by at
least the two bursts the size demands, and `CTRL_STATUS.STATUS` has to leave
the level it rests at while the zeroer is idle and come back to it.

Which level of `CTRL_STATUS.STATUS` means busy is not asserted here. The RDL
describes the field as "whether zeroer has completed" while the implemented
field is observed to read the other way round, and that disagreement is an open
specification issue; this sequence only requires the field to follow the
zeroer's activity, as `smc_zeroer_sanity_test` does.

The job is aimed at the output-fabric responder window, never at memory another
leaf reads, and `SIZE` and `DEST_ADDR` are cleared afterwards so a later write
to `CTRL_STATUS` -- the register whose write side effect is the trigger --
cannot start a job over anything.
"""

from __future__ import annotations

import cocotb
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_output_fabric_vip_utils import (
    OUTPUT_FABRIC_ADDR,
    OUTPUT_FABRIC_MODEL_BASE,
    OUTPUT_FABRIC_MODEL_REGION,
    OUTPUT_FABRIC_MODEL_SIZE,
    check_output_responder_delta,
    output_fabric_pass_all_cfg_seq,
    output_responder_counts,
)
from .smc_zeroer_dma_timeout_test_seq import (
    STATUS_BM,
    ZEROER_CTRL_STATUS,
    ZEROER_CTRL_STATUS_ARMED,
    ZEROER_CTRL_STATUS_START,
    ZEROER_DEST_ADDR,
    ZEROER_SIZE,
)

# AXI4 carries at most 256 transfers in one burst (`AxLEN` is eight bits), and
# the output data path is 64 bits wide, so one burst moves at most this many
# bytes.
_MAX_BYTES_PER_BURST = 256 * 8
# Job size: two maximal bursts. Any split the design chooses needs at least two
# address phases.
_JOB_BYTES = 2 * _MAX_BYTES_PER_BURST
_MIN_BURSTS = 2

# Probe words: the first and last word of each half of the job, so a job that
# stopped after one burst leaves the second half poisoned and a job that
# started late leaves the first half poisoned.
_PROBES = (
    ("FIRST", 0x0, 0xA0A1_A2A3_A4A5_A6A7),
    ("BURST0_LAST", _MAX_BYTES_PER_BURST - 8, 0xB0B1_B2B3_B4B5_B6B7),
    ("BURST1_FIRST", _MAX_BYTES_PER_BURST, 0xC0C1_C2C3_C4C5_C6C7),
    ("LAST", _JOB_BYTES - 8, 0xD0D1_D2D3_D4D5_D6D7),
)
# Witness word immediately past the end of the job. It must keep its poison.
_WITNESS_OFFSET = _JOB_BYTES
_WITNESS_POISON = 0xE0E1_E2E3_E4E5_E6E7
_WORD_BYTES = 8

# Bounds are liveness ceilings, not checked quantities: expiry FAILS.
_BUSY_ASSERT_CYCLES = 4000
_BUSY_CLEAR_CYCLES = 40000
_BURST_WAIT_CYCLES = 40000


class smc_zeroer_multi_burst_test_seq(output_fabric_pass_all_cfg_seq):
    """Clear a region larger than one AXI burst and check both halves."""

    def __init__(self, name: str = "smc_zeroer_multi_burst_test_seq") -> None:
        super().__init__(name)
        self.int_en_held = 0
        self.checked_bytes = 0
        self.bursts_observed = 0
        #: CTRL_STATUS.STATUS level read with the zeroer idle. No meaning is
        #: attached to the level; the check is that the field leaves it and
        #: comes back.
        self.status_idle_level = -1

    def _ensure_model_region(self) -> None:
        if OUTPUT_FABRIC_MODEL_REGION not in self.memory_model.regions:
            self.memory_model.add_region(
                OUTPUT_FABRIC_MODEL_REGION,
                OUTPUT_FABRIC_MODEL_BASE,
                OUTPUT_FABRIC_MODEL_SIZE,
            )

    async def _fabric_write(self, addr: int, value: int) -> None:
        item = SmcSysAxiItem(f"fabric_preload_0x{addr:x}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = _WORD_BYTES
        item.wdata = value
        await _OneShot(item, f"fabric_preload_0x{addr:x}_os").start(
            self.env.jtag_axi_agent.sequencer
        )

    async def _fabric_read(self, addr: int) -> int:
        item = SmcSysAxiItem(f"fabric_readback_0x{addr:x}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = _WORD_BYTES
        await _OneShot(item, f"fabric_readback_0x{addr:x}_os").start(
            self.env.jtag_axi_agent.sequencer
        )
        return item.rdata

    async def _status(self) -> int:
        word = await self.csr_read("ZEROER_CTRL_STATUS_POLL", ZEROER_CTRL_STATUS, length=8)
        return 1 if word & STATUS_BM else 0

    async def _await_status(self, want: int, cycles: int, what: str) -> None:
        for _ in range(cycles):
            if await self._status() == want:
                return
            await cocotb.triggers.ClockCycles(cocotb.top.clk_smc_i, 1)
        raise AssertionError(
            f"CTRL_STATUS.STATUS never {what} within {cycles} clk_smc_i cycles of a "
            f"{_JOB_BYTES}-byte job; the field does not follow the zeroer's activity"
        )

    async def body(self) -> None:
        assert _WITNESS_OFFSET + _WORD_BYTES <= OUTPUT_FABRIC_MODEL_SIZE, (
            f"the job and its witness need 0x{_WITNESS_OFFSET + _WORD_BYTES:x} bytes of the "
            f"0x{OUTPUT_FABRIC_MODEL_SIZE:x}-byte output-fabric model region"
        )
        assert len({poison for _n, _o, poison in _PROBES} | {_WITNESS_POISON}) == len(_PROBES) + 1
        self._ensure_model_region()
        await self.program_inbound_pass_all()
        await self.program_outbound_pass_all()

        for name, offset, poison in _PROBES:
            await self._fabric_write(OUTPUT_FABRIC_ADDR + offset, poison)
        await self._fabric_write(OUTPUT_FABRIC_ADDR + _WITNESS_OFFSET, _WITNESS_POISON)
        for name, offset, poison in _PROBES:
            got = await self._fabric_read(OUTPUT_FABRIC_ADDR + offset)
            assert got == poison, (
                f"probe {name} @ 0x{OUTPUT_FABRIC_ADDR + offset:08x} reads 0x{got:016x} "
                f"after a preload of 0x{poison:016x}; the region was not poisoned, so a "
                f"later read of zero would prove nothing"
            )
        witness = await self._fabric_read(OUTPUT_FABRIC_ADDR + _WITNESS_OFFSET)
        assert witness == _WITNESS_POISON, (
            f"the witness word @ 0x{OUTPUT_FABRIC_ADDR + _WITNESS_OFFSET:08x} reads "
            f"0x{witness:016x} after a preload of 0x{_WITNESS_POISON:016x}"
        )
        cocotb.log.info(
            "CHK-ZEROER-MULTI-BURST-PRELOAD: %d probe words spanning both halves of the "
            "0x%x-byte job and one witness word past its end were poisoned with distinct "
            "values and read back exactly, so the zero readbacks below can fail",
            len(_PROBES),
            _JOB_BYTES,
        )

        await self.csr_write("ZEROER_DEST_ADDR", ZEROER_DEST_ADDR, OUTPUT_FABRIC_ADDR, length=8)
        await self.csr_write("ZEROER_SIZE", ZEROER_SIZE, _JOB_BYTES, length=8)
        await self.csr_read(
            "ZEROER_DEST_ADDR_RB", ZEROER_DEST_ADDR, expected=OUTPUT_FABRIC_ADDR, length=8
        )
        await self.csr_read("ZEROER_SIZE_RB", ZEROER_SIZE, expected=_JOB_BYTES, length=8)

        self.status_idle_level = await self._status()
        start_writes, start_reads = output_responder_counts()

        await self.csr_write(
            "ZEROER_CTRL_STATUS_START", ZEROER_CTRL_STATUS, ZEROER_CTRL_STATUS_START, length=8
        )
        await self._await_status(
            1 - self.status_idle_level, _BUSY_ASSERT_CYCLES, "left its idle level"
        )
        # The responder counts one write transaction per B handshake, so the
        # delta is the number of bursts the zeroer issued. `exact_writes=False`
        # because the design is free to split the job into more than the two
        # maximal bursts AXI4 allows; what the size forbids is doing it in one.
        # A job that overran its size is caught by the witness word instead.
        await check_output_responder_delta(
            start_writes=start_writes,
            start_reads=start_reads,
            write_delta=_MIN_BURSTS,
            read_delta=0,
            exact_writes=False,
            timeout_cycles=_BURST_WAIT_CYCLES,
        )
        await self._await_status(
            self.status_idle_level, _BUSY_CLEAR_CYCLES, "returned to its idle level"
        )
        end_writes, _end_reads = output_responder_counts()
        self.bursts_observed = end_writes - start_writes
        assert self.bursts_observed >= _MIN_BURSTS, (
            f"the output responder booked {self.bursts_observed} write transaction(s) for a "
            f"{_JOB_BYTES}-byte job; AxLEN caps an AXI4 burst at 256 transfers, so on a "
            f"64-bit path it cannot be fewer than {_MIN_BURSTS}"
        )
        cocotb.log.info(
            "CHK-ZEROER-MULTI-BURST-STATUS: CTRL_STATUS.STATUS left the level it rests at "
            "while the zeroer is idle (%d) and returned to it, and the output responder "
            "booked %d write transaction(s) for the 0x%x-byte job, which AxLEN's 256-transfer "
            "cap makes impossible in fewer than %d, so the zeroer took a second address "
            "phase after its first data phase",
            self.status_idle_level,
            self.bursts_observed,
            _JOB_BYTES,
            _MIN_BURSTS,
        )

        for name, offset, poison in _PROBES:
            got = await self._fabric_read(OUTPUT_FABRIC_ADDR + offset)
            assert got == 0, (
                f"probe {name} @ 0x{OUTPUT_FABRIC_ADDR + offset:08x} still reads "
                f"0x{got:016x} after a {_JOB_BYTES}-byte zeroing that covers it (poison was "
                f"0x{poison:016x})"
            )
            self.checked_bytes += _WORD_BYTES
        witness = await self._fabric_read(OUTPUT_FABRIC_ADDR + _WITNESS_OFFSET)
        assert witness == _WITNESS_POISON, (
            f"the witness word @ 0x{OUTPUT_FABRIC_ADDR + _WITNESS_OFFSET:08x} reads "
            f"0x{witness:016x}; it sits immediately past the end of the job, so the zeroing "
            f"ran past the size it was given"
        )
        # `ZEROER_CTRL_STATUS_START` is packed with `int_en=1`, so the start
        # write above left `CTRL_STATUS.INT_EN` holding a one. The field is bit
        # 0 of a 64-bit register, so a four-byte write at the upper half leaves
        # its byte lane deasserted and a field that retains has to keep it.
        # Any write of this register is also the zeroer's trigger, so the leg
        # waits the operation out before reading.
        await self.csr_write("ZEROER_CTRL_STATUS_UPPER_HALF", ZEROER_CTRL_STATUS + 4, 0, length=4)
        await self._await_status(
            self.status_idle_level, _BUSY_CLEAR_CYCLES, "returned to its idle level"
        )
        word = await self.csr_read("ZEROER_CTRL_STATUS_INT_EN", ZEROER_CTRL_STATUS, length=8)
        assert word & ZEROER_CTRL_STATUS_START, (
            f"CTRL_STATUS reads 0x{word:x} after a four-byte write at its upper half; that "
            f"write did not select the lane INT_EN sits in, so the bit the start write set "
            f"has to still be there"
        )
        assert word & ~STATUS_BM & 0xFFFF_FFFF_FFFF_FFFF == ZEROER_CTRL_STATUS_ARMED, (
            f"CTRL_STATUS reads 0x{word:x} outside the STATUS bit after the half write; "
            f"the armed word this leaf left is 0x{ZEROER_CTRL_STATUS_ARMED:x}, so the "
            f"write moved something it did not select"
        )
        self.int_en_held = 1

        cocotb.log.info(
            "CHK-ZEROER-MULTI-BURST-ZEROED: all %d probe words of the 0x%x-byte job read 0 "
            "(%d bytes compared), including the first and last word of each half, and the "
            "witness word immediately past the end still holds 0x%016x",
            len(_PROBES),
            _JOB_BYTES,
            self.checked_bytes,
            _WITNESS_POISON,
        )

        armed = await self.csr_read("ZEROER_CTRL_STATUS_RB", ZEROER_CTRL_STATUS, length=8)
        assert armed & ~STATUS_BM == ZEROER_CTRL_STATUS_ARMED, (
            f"CTRL_STATUS reads 0x{armed & ~STATUS_BM:x} outside the STATUS bit, the RDL "
            f"contract for the armed register is 0x{ZEROER_CTRL_STATUS_ARMED:x}"
        )
        # The same two halves with INT_EN clear. A four-byte write at the low
        # half selects INT_EN's lane and clears it; one at the upper half then
        # leaves the cleared bit's lane deasserted, and it has to stay clear.
        # Both writes are triggers too, and DEST_ADDR and SIZE still describe
        # this leaf's own job, so each re-runs the job over the region it has
        # already zeroed and is waited out. INT_EN ends at its RDL reset of 0.
        for tag, addr in (
            ("LOW_HALF_CLEAR", ZEROER_CTRL_STATUS),
            ("UPPER_HALF_CLEAR", ZEROER_CTRL_STATUS + 4),
        ):
            await self.csr_write(f"ZEROER_CTRL_STATUS_{tag}", addr, 0, length=4)
            await self._await_status(
                self.status_idle_level, _BUSY_CLEAR_CYCLES, "returned to its idle level"
            )
            word = await self.csr_read(f"ZEROER_CTRL_STATUS_{tag}_RB", ZEROER_CTRL_STATUS, length=8)
            assert word & ZEROER_CTRL_STATUS_START == 0, (
                f"CTRL_STATUS reads 0x{word:x} after a four-byte write of 0 at "
                f"{'its low half, which selects INT_EN' if addr == ZEROER_CTRL_STATUS else 'its upper half, with INT_EN already clear'}; "
                f"INT_EN has to read clear"
            )
        self.int_en_held = 2
        cocotb.log.info(
            "CHK-ZEROER-INT-EN-HALF-WRITE: CTRL_STATUS.INT_EN held a one across a "
            "four-byte write at the half of the 64-bit register it does not occupy, was "
            "cleared by a four-byte write at the half it does, and stayed clear across a "
            "second write at the other half; every write re-ran this leaf's own job and was "
            "waited out, and INT_EN ended at its RDL reset",
        )
        # SIZE and DEST_ADDR carry no write side effect, so clearing them cannot
        # start a job. CTRL_STATUS is written above, while they still describe
        # this leaf's own job, and not after.
        await self.csr_write("ZEROER_SIZE_CLEAR", ZEROER_SIZE, 0, length=8)
        await self.csr_write("ZEROER_DEST_ADDR_CLEAR", ZEROER_DEST_ADDR, 0, length=8)
        await self.csr_read("ZEROER_SIZE_CLEAR_RB", ZEROER_SIZE, expected=0, length=8)
