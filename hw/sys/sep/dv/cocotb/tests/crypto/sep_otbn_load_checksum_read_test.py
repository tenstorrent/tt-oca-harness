# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A host read of OTBN IMEM or DMEM leaves ``LOAD_CHECKSUM`` unchanged.

Spec (``ToO`` = ``vendor/lowRISC/opentitan/upstream/hw/ip/otbn/doc/theory_of_operation.md``):
"The register exposes a cumulative CRC checksum which is updated on every write to
either memory." (ToO:441); "The stream over which the checksum is computed is the
stream of writes that have been seen since the last write to LOAD_CHECKSUM."
(ToO:449); ``LOAD_CHECKSUM`` is "A 32-bit CRC checksum of data written to memory"
(``vendor/lowRISC/opentitan/upstream/hw/ip/otbn/data/otbn.hjson`` :763). A read is
not a write, so it is not in the stream.

Flow (one seed draws the plan, logged in one ``PLAN`` line): the entropy chain is
brought up, OTBN is released from its software reset and reaches IDLE (the memories
are accessible only at IDLE, ``otbn.hjson`` :797-802 and :821-826). Then for IMEM,
then DMEM:

  1. ``LOAD_CHECKSUM`` <- 0 (ToO:456-457, :461).
  2. One full-word write of a drawn word (every byte non-zero) to a drawn word index.
  3. ``LOAD_CHECKSUM`` is read: X.
  4. One 32-bit read of that word; ``LOAD_CHECKSUM`` is read again.
  5. One 8-bit read of a drawn byte lane of that word; ``LOAD_CHECKSUM`` is read again.

Controls:
  CTRL-OTBN-IDLE            ``STATUS`` reads IDLE before the first memory access.
  CTRL-OTBN-<MEM>-CRC-LIVE  X equals ``binascii.crc32`` of the one 48b record
                            ``{imem, idx[14:0], wdata}`` (ToO:447-453; ``imem`` is 1
                            for IMEM and 0 for DMEM) in little- or big-endian byte
                            order. The text fixes the record layout, not its byte
                            order, so both are accepted. This proves the register
                            follows writes to that memory.
  CTRL-OTBN-<MEM>-READBACK  the 32-bit read returns the written word and the 8-bit
                            read returns its byte at the drawn lane (the AXI driver
                            fails the leaf on a response other than OKAY). A read
                            at a non-IDLE state returns 0 (``otbn.hjson``
                            :801-802), which no drawn byte equals, so the reads
                            reached the memory.

Checks:
  CHK-OTBN-IMEM-READ-CRC    ``LOAD_CHECKSUM`` == X after the 32-bit IMEM read, and
                            again after the 8-bit IMEM read.
  CHK-OTBN-DMEM-READ-CRC    the same for DMEM.
"""

from __future__ import annotations

import binascii

import pyuvm
from env.sep_chk_log import SepChkLog
from env.sep_seeded_rng import SepSeededRng
from env.sep_spec_tables import ot_rdl_table_code
from sep_base_test import sep_base_test
from sep_reg_meta import OTBN, sym
from seq_lib.sep_otbn_seq import OTBN_ADDR_STATUS, SepOtbn

TEST = "sep_otbn_load_checksum_read_test"

ST_IDLE = ot_rdl_table_code("otbn", "STATUS", "IDLE")
M_STATUS = OTBN.field_mask("STATUS", "status")

# (name, imem flag of the record, window base, window size in bytes)
MEMS = (
    ("IMEM", 1, sym("OTBN_IMEM_MEM_BASE_ADDR"), sym("OTBN_IMEM_MEM_SIZE")),
    ("DMEM", 0, sym("OTBN_DMEM_MEM_BASE_ADDR"), sym("OTBN_DMEM_MEM_SIZE")),
)
WORD_BYTES = 4
AXI_SIZE_BYTE = 0
CKSUM_ORDERS = ("little", "big")


def load_checksum_golden(imem: int, idx: int, wdata: int, order: str) -> int:
    """CRC-32-IEEE of one 48b ``{imem, idx[14:0], wdata}`` record from 0 (ToO:447-453)."""
    rec = ((imem & 1) << 47) | ((idx & 0x7FFF) << 32) | (wdata & 0xFFFF_FFFF)
    return binascii.crc32(rec.to_bytes(6, order), 0)


def draw_plan(seed: int) -> list[tuple[int, int, int]]:
    """Per memory of ``MEMS``: (word index, word with every byte non-zero, byte lane)."""
    rng = SepSeededRng(seed)
    plan = []
    for _name, _imem, _base, size in MEMS:
        idx = rng.randrange(0, size // WORD_BYTES)
        wdata = 0
        for lane in range(WORD_BYTES):
            wdata |= rng.randrange(1, 256) << (8 * lane)
        plan.append((idx, wdata, rng.randrange(0, WORD_BYTES)))
    return plan


@pyuvm.test()
class sep_otbn_load_checksum_read_test(sep_base_test):
    """A host read of OTBN IMEM or DMEM leaves ``LOAD_CHECKSUM`` unchanged."""

    required_evidence = ("CHK-OTBN-IMEM-READ-CRC", "CHK-OTBN-DMEM-READ-CRC")

    async def _mem_leg(self, name: str, imem: int, base: int, idx: int, wdata: int, lane: int):
        chk, otbn = self.chk, self.otbn
        addr = base + idx * WORD_BYTES
        await otbn.write_load_checksum(0)
        await otbn._wr(addr, wdata)
        before = await otbn.read_load_checksum()
        cands = [load_checksum_golden(imem, idx, wdata, o) for o in CKSUM_ORDERS]
        chk.ctrl(
            f"OTBN-{name}-CRC-LIVE",
            before in cands,
            idx=idx,
            wdata=f"0x{wdata:08x}",
            crc=f"0x{before:08x}",
            candidates=[f"0x{c:08x}" for c in cands],
        )

        word = (await otbn._rd(addr)) & 0xFFFF_FFFF
        chk.ctrl(
            f"OTBN-{name}-READBACK",
            word == wdata,
            read="word",
            addr=f"0x{addr:08x}",
            rdata=f"0x{word:08x}",
            expect=f"0x{wdata:08x}",
        )
        await self._grade_crc(name, "word", addr, before)

        byte_addr = addr + lane
        byte = (await otbn._read_access(byte_addr, size=AXI_SIZE_BYTE, length=1)) & 0xFF
        exp_byte = (wdata >> (8 * lane)) & 0xFF
        chk.ctrl(
            f"OTBN-{name}-READBACK",
            byte == exp_byte,
            read="byte",
            addr=f"0x{byte_addr:08x}",
            rdata=f"0x{byte:02x}",
            expect=f"0x{exp_byte:02x}",
        )
        await self._grade_crc(name, "byte", byte_addr, before)

    async def _grade_crc(self, name: str, read: str, addr: int, before: int) -> None:
        after = await self.otbn.read_load_checksum()
        self.chk.ok(
            f"OTBN-{name}-READ-CRC",
            after == before,
            read=read,
            addr=f"0x{addr:08x}",
            before=f"0x{before:08x}",
            after=f"0x{after:08x}",
            expect="after==before",
        )

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu(park=("otbn", "aes", "hmac", "kmac", "abr"))
        await self.bring_up_entropy(
            strict=True, score_km=False, score_sinks={"otbn_urnd": "observe"}
        )
        self.start_fifo_drain()

        seed = self.random_seed()
        plan = draw_plan(seed)
        self.logger.info(
            "PLAN seed=%d %s",
            seed,
            " ".join(
                f"{m[0].lower()}_idx={i} {m[0].lower()}_wdata=0x{w:08x} {m[0].lower()}_lane={ln}"
                for m, (i, w, ln) in zip(MEMS, plan)
            ),
        )
        self.chk = SepChkLog(self, TEST, seed)
        self.otbn = SepOtbn(self)

        await self.swrst.release("otbn")
        await self.otbn.wait_idle("post-release")
        status = (await self.otbn._rd(OTBN_ADDR_STATUS)) & M_STATUS
        self.chk.ctrl("OTBN-IDLE", status == ST_IDLE, status=f"0x{status:02x}")

        for (name, imem, base, _size), (idx, wdata, lane) in zip(MEMS, plan):
            await self._mem_leg(name, imem, base, idx, wdata, lane)

        await self.stop_fifo_drain()
        assert self.drbg_sb.report()
        self.chk.finish()
