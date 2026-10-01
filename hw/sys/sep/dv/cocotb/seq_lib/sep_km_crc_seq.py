# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Host client for the KM CRC service ROM (``km_rom_crc.S``).

The CRC engine is a PicoRV32 PCPI co-processor with no register interface, so
the only honest activation is KM firmware issuing the custom-0 instruction.
This client posts one {mode, state, data} request over the SEP-side KM mailbox
and reads the raw result back, which keeps every golden and cross-check on the
host where it is reviewable.

The exchange is raw mailbox words, not the KM firmware message protocol: the
service ROM is a stub and does not frame responses, so there is no header CRC
or sequence number to validate here.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from env.sep_axi_agent import SepAxiOp
from env.sep_crc_golden import MODE_8_ROHC, MODE_32C_BYTE, MODE_32C_WORD
from env.sep_crc_golden import update as crc_golden
from env.sep_seeded_rng import SepSeededRng

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_km_mailbox_seq import (
    KM_MBOX_BASE,
    KM_MBOX_READ_DATA,
    KM_MBOX_STATUS,
    KM_MBOX_WRITE_DATA,
    KM_MBOX_WRITE_SEPARATOR,
    KM_STATUS_OUTBOUND_EMPTY,
)

# Mode selectors, matching the service ROM's request word.
CRC_MODE_32C_WORD = 0
CRC_MODE_32C_BYTE = 1
CRC_MODE_8_ROHC = 2
CRC_REQ_HALT = 0xFFFF_FFFF

# Vectors per mode drawn from the run seed.
N_RAND_VECTORS = 4


class SepKmCrcCfg:
    """Seeded operand set for one run.

    Operands are screened, not merely drawn. A CRC step over an all-zero state
    and an all-zero byte returns zero for both polynomials, so a run that drew
    those would pass against a dead engine; a word whose four bytes are equal
    cannot tell a little-endian consumption order from a big-endian one; and
    every mode has legal FIXED POINTS, operands the engine correctly maps back
    onto their own input state. A fixed point is not a defect, but it makes the
    "the engine moved the state" check unfalsifiable for that vector, so the
    draw rejects one rather than letting the checker tolerate it. Fixed points
    are identified with the independent golden, never by asking the DUT: in
    CRC-8/ROHC one byte in 256 is a fixed point for any given state, so drawing
    without this screen fails a few percent of seeds on correct hardware.
    """

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        self.word_vectors = tuple(self._draw_word(rng) for _ in range(N_RAND_VECTORS))
        self.byte_vectors = tuple(self._draw_byte(rng) for _ in range(N_RAND_VECTORS))
        self.rohc_vectors = tuple(self._draw_rohc(rng) for _ in range(N_RAND_VECTORS))
        # The chained cross-check needs one word whose bytes are all distinct.
        self.chain_state, self.chain_word = self._draw_word(rng)
        # CHK-POLY compares the two polynomial families over the low byte, and
        # two different polynomials agree there for about one operand in 256.
        # That is correct hardware, so the operand is screened rather than the
        # checker loosened -- otherwise the test would fail a fraction of a
        # percent of seeds for no defect.
        self.poly_state, self.poly_data = self._draw_poly(rng)

    @staticmethod
    def _moves(mode: int, state: int, data: int) -> bool:
        """True when the golden says this operand does not sit on a fixed point."""
        return crc_golden(mode, state, data) != state

    @classmethod
    def _draw_word(cls, rng) -> tuple[int, int]:
        while True:
            state = rng.getrandbits(32)
            word = rng.getrandbits(32)
            octets = {(word >> s) & 0xFF for s in (0, 8, 16, 24)}
            if state != 0 and len(octets) == 4 and cls._moves(MODE_32C_WORD, state, word):
                return state, word

    @classmethod
    def _draw_byte(cls, rng) -> tuple[int, int]:
        while True:
            state = rng.getrandbits(32)
            # Nonzero garbage in the upper 24 bits: the byte modes must ignore
            # it, and a run that always sent zeros there could not tell.
            data = rng.getrandbits(32)
            if (
                state != 0
                and (data & 0xFF) != 0
                and (data >> 8) != 0
                and cls._moves(MODE_32C_BYTE, state, data)
            ):
                return state, data

    @classmethod
    def _draw_poly(cls, rng) -> tuple[int, int]:
        """An operand the two polynomial families map to different low bytes."""
        while True:
            state = rng.getrandbits(8)
            data = rng.getrandbits(32)
            if (data & 0xFF) == 0 and state == 0:
                continue
            lo_32c = crc_golden(MODE_32C_BYTE, state, data) & 0xFF
            lo_rohc = crc_golden(MODE_8_ROHC, state, data) & 0xFF
            if lo_32c != lo_rohc:
                return state, data

    @classmethod
    def _draw_rohc(cls, rng) -> tuple[int, int]:
        while True:
            state = rng.getrandbits(8)
            data = rng.getrandbits(32)
            if state == 0 and (data & 0xFF) == 0:
                continue
            if cls._moves(MODE_8_ROHC, state, data):
                return state, data

    def summary(self) -> str:
        return (
            f"seed={self.seed} vectors_per_mode={N_RAND_VECTORS} "
            f"chain_state=0x{self.chain_state:08x} chain_word=0x{self.chain_word:08x} "
            f"poly_state=0x{self.poly_state:02x} poly_data=0x{self.poly_data:08x}"
        )


class SepKmCrc:
    """Drives the KM CRC service ROM over the SEP AXI agent."""

    def __init__(self, test, *, base: int = KM_MBOX_BASE) -> None:
        self.test = test
        self.base = base
        self.log = test.logger

    async def _wr(self, offset: int, data: int) -> None:
        seq = SepAxiAccessSeq(
            "km_crc_wr", op=SepAxiOp.WRITE, addr=self.base + offset, wdata=data, size=2
        )
        await self.test.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(f"KM mailbox write @0x{self.base + offset:08x} not OKAY")

    async def _rd(self, offset: int) -> int:
        seq = SepAxiAccessSeq("km_crc_rd", op=SepAxiOp.READ, addr=self.base + offset, size=2)
        await self.test.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(f"KM mailbox read @0x{self.base + offset:08x} not OKAY")
        return seq.rdata

    async def _post(self, word: int, *, last: bool) -> None:
        if last:
            await self._wr(KM_MBOX_WRITE_SEPARATOR, 1)
        await self._wr(KM_MBOX_WRITE_DATA, word)

    async def update(
        self, mode: int, state: int, data: int, *, timeout: int = 20_000, poll_cycles: int = 20
    ) -> int:
        """Ask the service ROM for one instruction result.

        The wait is bounded and attributed: a service ROM that stops answering
        fails here naming the request, rather than polling an empty mailbox
        until the run's own timeout fires.
        """
        await self._post(mode, last=False)
        await self._post(state & 0xFFFF_FFFF, last=False)
        await self._post(data & 0xFFFF_FFFF, last=True)

        for _ in range(timeout):
            if not (await self._rd(KM_MBOX_STATUS) & (1 << KM_STATUS_OUTBOUND_EMPTY)):
                return await self._rd(KM_MBOX_READ_DATA)
            await ClockCycles(cocotb.top.clk_i, poll_cycles)
        raise AssertionError(
            f"KM CRC service ROM did not answer mode={mode} "
            f"state=0x{state:08x} data=0x{data:08x} within {timeout} polls"
        )

    async def halt(self) -> None:
        """Retire the service loop so the image is not left mid-request."""
        await self._post(CRC_REQ_HALT, last=True)
