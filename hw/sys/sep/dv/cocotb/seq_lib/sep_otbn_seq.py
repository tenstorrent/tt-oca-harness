# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OTBN run-control driver (direct AXI on the SEP CPU-LSU bus).

Loads an OTBN program into IMEM over the AXI front door (the OTBN TL/AXI adapter
SECDED-encodes each word into the external IMEM macro, so a faithful memory
responder backs a genuinely executing OpenTitan OTBN core), issues EXECUTE, polls
STATUS to IDLE, and reads DMEM / ERR_BITS back. Mirrors the reference suite
sep_km_otbn_sideload_kat_test_seq run mechanics.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from sep_reg_meta import OTBN, sym

from seq_lib.sep_axi_reg_driver import SepAxiRegDriver

# OTBN SEP register map (direct AXI).
OTBN_BASE = sym("OTBN_REG_MAP_BASE_ADDR")
OTBN_ADDR_CMD = OTBN.addr("CMD")
OTBN_ADDR_STATUS = OTBN.addr("STATUS")
OTBN_ADDR_ERRBIT = OTBN.addr("ERR_BITS")
OTBN_ADDR_LOAD_CHECKSUM = OTBN.addr("LOAD_CHECKSUM")
OTBN_LOAD_CHECKSUM_RESET = OTBN.reset32("LOAD_CHECKSUM")
OTBN_IMEM_BASE = sym("OTBN_IMEM_MEM_BASE_ADDR")
OTBN_DMEM_BASE = sym("OTBN_DMEM_MEM_BASE_ADDR")

# CMD.cmd EXECUTE and STATUS IDLE / LOCKED from
# vendor/lowRISC/opentitan/upstream/hw/ip/otbn/data/otbn.hjson.
OTBN_CMD_EXECUTE = 0x0000_00D8
OTBN_STATUS_IDLE = 0x0000_0000
OTBN_STATUS_LOCK = 0x0000_00FF

# DMEM result layout (keydump.s + share dump):
#   result_lo  @ 0x00  key[255:0]    (w2 = S0_L ^ S1_L, 8 words)
#   result_hi  @ 0x20  key[383:256]  (w5 = S0_H ^ S1_H, low 4 words + zero pad)
#   share0_lo  @ 0x40  share0[255:0] (w0 = KEY_S0_L)
#   share0_hi  @ 0x60  share0[383:256] (w3 = KEY_S0_H, low 4 words + zero pad)
#   share1_lo  @ 0x80  share1[255:0] (w1 = KEY_S1_L)
#   share1_hi  @ 0xA0  share1[383:256] (w4 = KEY_S1_H, low 4 words + zero pad)
# Dumping the raw shares (the OTBN's own legitimate KEY_S0/S1 WSR reads, no
# backdoor) lets the host prove the 2-share masking is non-degenerate.
OTBN_DMEM_RESULT_LO = 0x00
OTBN_DMEM_RESULT_HI = 0x20
OTBN_DMEM_SHARE0_LO = 0x40
OTBN_DMEM_SHARE0_HI = 0x60
OTBN_DMEM_SHARE1_LO = 0x80
OTBN_DMEM_SHARE1_HI = 0xA0

# Assembled OTBN key-dump program (OTBN_KEYDUMP_PROG). Reads the sideload key
# WSRs (KEY_S0_L=4, KEY_S0_H=5, KEY_S1_L=6, KEY_S1_H=7), reconstructs
# key = share0 ^ share1, and writes both the key and the two raw shares to
# DMEM. bn.sid encoding: (wdr_idx_reg<<20)|(base_reg<<15)|(0b101<<12)|0x0B.
OTBN_KEYDUMP_PROG = (
    0x0040700B,  # bn.wsrr w0, KEY_S0_L    (share0[255:0])
    0x0060708B,  # bn.wsrr w1, KEY_S1_L    (share1[255:0])
    0x0010617B,  # bn.xor  w2, w0, w1      (key[255:0])
    0x0050718B,  # bn.wsrr w3, KEY_S0_H    (share0[383:256])
    0x0070720B,  # bn.wsrr w4, KEY_S1_H    (share1[383:256])
    0x0041E2FB,  # bn.xor  w5, w3, w4      (key[383:256])
    0x00200113,  # addi    x2, x0, 2       (WDR idx 2 = key_lo)
    0x00500293,  # addi    x5, x0, 5       (WDR idx 5 = key_hi)
    0x00000337,  # lui     x6, 0x0
    0x00030313,  # addi    x6, x6, 0       (dmem result_lo @ 0x00)
    0x000003B7,  # lui     x7, 0x0
    0x02038393,  # addi    x7, x7, 32      (dmem result_hi @ 0x20)
    0x0023500B,  # bn.sid  x2, 0(x6)       dmem[0x00] = key_lo
    0x0053D00B,  # bn.sid  x5, 0(x7)       dmem[0x20] = key_hi
    0x04000513,  # addi    x10, x0, 64     (dmem share0_lo @ 0x40)
    0x06000593,  # addi    x11, x0, 96     (dmem share0_hi @ 0x60)
    0x08000613,  # addi    x12, x0, 128    (dmem share1_lo @ 0x80)
    0x0A000693,  # addi    x13, x0, 160    (dmem share1_hi @ 0xA0)
    0x00300713,  # addi    x14, x0, 3      (WDR idx 3 = share0_hi)
    0x00400793,  # addi    x15, x0, 4      (WDR idx 4 = share1_hi)
    0x00100813,  # addi    x16, x0, 1      (WDR idx 1 = share1_lo)
    0x0005500B,  # bn.sid  x0,  0(x10)     dmem[0x40] = share0_lo (w0)
    0x00E5D00B,  # bn.sid  x14, 0(x11)     dmem[0x60] = share0_hi (w3)
    0x0106500B,  # bn.sid  x16, 0(x12)     dmem[0x80] = share1_lo (w1)
    0x00F6D00B,  # bn.sid  x15, 0(x13)     dmem[0xA0] = share1_hi (w4)
    0x00000073,  # ecall
)

# OTBN RND drain program (OTBN_RND_PROG). Each `csrrs x10, RND, x0` reads the
# RND CSR. The OTBN ISA specification
# (`vendor/lowRISC/opentitan/upstream/hw/ip/otbn/data/csr.yml`, `rnd`) puts RND
# at address 0xfc0, states that the number "is sourced from the EDN via a single
# -entry cache", and that "reads when the cache is empty will cause OTBN to be
# stalled until a new random number is fetched from the EDN". That stall is what
# holds `crypto_edn_req[2]` for the request checker, and the single-entry cache
# is why each read is a new EDN fetch rather than a re-read of a latched word.
# No RND_PREFETCH (0x7d8) is issued, so the first read stalls. Stores the four
# words to DMEM 0x00..0x0C for the host.
OTBN_RND_PROG = (
    0x00000313,  # addi   x6, x0, 0        (dmem base 0x00)
    0xFC002573,  # csrrs  x10, 0xFC0, x0   RND read 1
    0x00A32023,  # sw     x10, 0(x6)
    0xFC002573,  # csrrs  x10, 0xFC0, x0   RND read 2
    0x00A32223,  # sw     x10, 4(x6)
    0xFC002573,  # csrrs  x10, 0xFC0, x0   RND read 3
    0x00A32423,  # sw     x10, 8(x6)
    0xFC002573,  # csrrs  x10, 0xFC0, x0   RND read 4
    0x00A32623,  # sw     x10, 12(x6)
    0x00000073,  # ecall
)

# Number of RND CSR reads OTBN_RND_PROG retires, and the DMEM words it leaves.
OTBN_RND_READS = 4
OTBN_DMEM_RND_BASE = 0x00


class SepOtbn(SepAxiRegDriver):
    """Direct-AXI OTBN run control. The test owns one instance.

    OTBN IMEM/DMEM are 32-bit SECDED words; the inherited _wr/_rd drive 32-bit
    AXI beats (size=2). A default 64-bit beat is rejected on IMEM/DMEM (SLVERR).
    """

    _DRIVER_TAG = "OTBN"

    async def wait_idle(self, tag: str, *, timeout: int = 4_000, poll_cycles: int = 20) -> None:
        """Poll STATUS until IDLE (0x00). Fail on LOCKED (0xFF) or timeout."""
        for i in range(timeout):
            st = await self._rd(OTBN_ADDR_STATUS)
            if st == OTBN_STATUS_IDLE:
                self.log.info("OTBN IDLE (%s) after %d polls", tag, i)
                return
            if st == OTBN_STATUS_LOCK:
                raise AssertionError(f"OTBN LOCKED ({tag})")
            if i and i % 500 == 0:
                self.log.info("OTBN wait_idle (%s): poll %d, STATUS=0x%08x", tag, i, st)
            await ClockCycles(cocotb.top.clk_i, poll_cycles)
        raise AssertionError(f"OTBN did not reach IDLE ({tag})")

    async def load_program(self, prog=OTBN_KEYDUMP_PROG) -> None:
        # IMEM/DMEM are writable only while OTBN is IDLE. After a reset release
        # OTBN runs an initial secure wipe (STATUS busy); wait it out, else the
        # IMEM write is rejected with a non-OKAY AXI response.
        await self.wait_idle("pre-program-load")
        for i, word in enumerate(prog):
            await self._wr(OTBN_IMEM_BASE + i * 4, word)
        self.log.info("OTBN loaded %d-word program into IMEM", len(prog))

    async def start_execute(self) -> None:
        """Issue EXECUTE and return without polling STATUS.

        A program that blocks on an entropy CSR holds its `crypto_edn_req` bit
        while it waits, so a caller that wants to observe that request must not
        be sitting in wait_idle() when it happens.
        """
        await self._wr(OTBN_ADDR_CMD, OTBN_CMD_EXECUTE)

    async def execute(self) -> None:
        await self.start_execute()
        await self.wait_idle("post-execute")

    async def read_errbits(self) -> int:
        return await self._rd(OTBN_ADDR_ERRBIT)

    async def read_dmem(self, offset: int) -> int:
        return await self._rd(OTBN_DMEM_BASE + offset)

    async def write_dmem(self, offset: int, val: int) -> None:
        await self._wr(OTBN_DMEM_BASE + offset, val & 0xFFFF_FFFF)

    async def write_load_checksum(self, val: int) -> None:
        """LOAD_CHECKSUM is a 32-bit RW CSR in the OTBN rst_ni domain (reset 0)."""
        await self._wr(OTBN_ADDR_LOAD_CHECKSUM, val & 0xFFFF_FFFF)

    async def read_load_checksum(self) -> int:
        return await self._rd(OTBN_ADDR_LOAD_CHECKSUM)

    async def read_dmem_words(self, base_offset: int, count: int) -> list[int]:
        return [await self.read_dmem(base_offset + i * 4) for i in range(count)]

    async def read_keydump_outputs(self) -> tuple[list[int], list[int], list[int], list[int]]:
        """Read the key-dump program's DMEM outputs via the named offsets (no raw
        addresses in the test). Returns (key, share0, share1, key_hi_pad):
        key/share0/share1 are 12-word lists (lo 8 words + hi 4 words); key_hi_pad is
        the 4 upper words of result_hi (the zero pad above the 384b key)."""
        res_lo = await self.read_dmem_words(OTBN_DMEM_RESULT_LO, 8)
        res_hi = await self.read_dmem_words(OTBN_DMEM_RESULT_HI, 8)
        share0 = (await self.read_dmem_words(OTBN_DMEM_SHARE0_LO, 8)) + (
            await self.read_dmem_words(OTBN_DMEM_SHARE0_HI, 8)
        )[:4]
        share1 = (await self.read_dmem_words(OTBN_DMEM_SHARE1_LO, 8)) + (
            await self.read_dmem_words(OTBN_DMEM_SHARE1_HI, 8)
        )[:4]
        return res_lo + res_hi[:4], share0, share1, res_hi[4:]
