# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OpenTitan HMAC run-control driver (direct AXI on the SEP CPU-LSU bus).

Configures the HMAC engine for keyed HMAC-SHA256, pushes a message through the
MSG FIFO, waits for done, and reads the digest. Direct AXI, like SepAes/SepOtbn.
32-bit beats (size=2) via the wrapper's 64->32 dw-converter.

HMAC register map (base from the generated SEP header; offsets from hmac.adoc):
  INTR_STATE @ 0x000 (RW1C: bit0 hmac_done, bit2 hmac_err)
  CFG        @ 0x010   CMD @ 0x014   STATUS @ 0x018   ERR_CODE @ 0x01C
  KEY_0..31  @ 0x024..0x0A0   DIGEST_0..7 @ 0x0A4..0x0C0
  MSG_FIFO window @ base+0x1000
When the KM sideloads a key (keymgr_key_i.valid=1) HMAC uses it instead of the
public KEY registers -- there is no CFG sideload bit; the public KEY CSRs stay
write-only and read back zero.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
from cocotb.triggers import ClockCycles
from sep_reg_meta import HMAC, sym

from seq_lib.sep_axi_reg_driver import SepAxiRegDriver

HMAC_BASE = sym("HMAC_REG_MAP_BASE_ADDR")
HMAC_INTR_STATE = HMAC.addr("INTR_STATE")
HMAC_CFG = HMAC.addr("CFG")
HMAC_CMD = HMAC.addr("CMD")
HMAC_STATUS = HMAC.addr("STATUS")
HMAC_ERR_CODE = HMAC.addr("ERR_CODE")
HMAC_KEY_0 = sym("HMAC_KEY_0__REG_ADDR")
HMAC_DIGEST_0 = sym("HMAC_DIGEST_0__REG_ADDR")
HMAC_MSG_FIFO = sym("HMAC_MSG_FIFO_MEM_BASE_ADDR")
HMAC_NUM_PUBLIC_KEY = 32

# CFG keyed HMAC-SHA256, 256-bit key (vendor/lowRISC/opentitan/overlay/regs/hmac/regs/gen/adoc/hmac.adoc): hmac_en[0]=1, sha_en[1]=1,
# digest_size SHA2_256 -> bit5, key_length 256 -> bit10 (field [14:9]=2);
# endian_swap/digest_swap = 0 (digest word0 = MSB == standard big-endian digest).
HMAC_CMD_HASH_START = HMAC.field_mask("CMD", "hash_start")
HMAC_CMD_HASH_PROCESS = HMAC.field_mask("CMD", "hash_process")

HMAC_STATUS_FIFO_FULL = HMAC.field_mask("STATUS", "fifo_full")
# STATUS.hmac_idle: set while the core holds no in-flight message. Taken from
# the generated block, so a field move cannot leave a stale literal here.
HMAC_STATUS_IDLE = HMAC.field_mask("STATUS", "hmac_idle")
HMAC_INTR_DONE = HMAC.field_mask("INTR_STATE", "hmac_done")
HMAC_INTR_ERR = HMAC.field_mask("INTR_STATE", "hmac_err")

# CFG field encodings (hmac.adoc digest_size / key_length, one-hot).
HMAC_DIGEST_SIZE = {256: 0x1, 384: 0x2, 512: 0x4}  # SHA2_256/384/512
HMAC_KEY_LENGTH = {128: 0x1, 256: 0x2, 384: 0x4, 512: 0x8, 1024: 0x10}
# Valid 32-bit DIGEST_* words exposed per SHA-2 variant (hmac.adoc).
HMAC_DIGEST_WORDS = {256: 8, 384: 12, 512: 16}
# SHA-2 block size per digest size, in bits. hmac.adoc: "the key length cannot
# be greater than the block size: up to 1024-bit for SHA-2 384/512 and up to
# 512-bit for SHA-2 256."
HMAC_BLOCK_BITS = {256: 512, 384: 1024, 512: 1024}
# Keyed cells the register specification blocks, derived from that rule rather
# than listed: hmac.adoc states a start with KEY_LENGTH = Key_1024 while
# DIGEST_SIZE = SHA2_256 "is blocked and an error is signalled to SW". Deriving
# it keeps the legal set the specification's, not the design's -- an RTL bound
# that disagreed with the block-size rule would now drive a cell this set calls
# legal.
HMAC_ILLEGAL_KEYED = {
    (sha_bits, key_bits)
    for sha_bits in HMAC_DIGEST_SIZE
    for key_bits in HMAC_KEY_LENGTH
    if key_bits > HMAC_BLOCK_BITS[sha_bits]
}
assert HMAC_ILLEGAL_KEYED == {(256, 1024)}, HMAC_ILLEGAL_KEYED


def build_cfg(
    *,
    hmac_en: bool,
    sha_bits: int,
    key_bits: int | None = None,
    endian_swap: int = 0,
    digest_swap: int = 0,
    key_swap: int = 0,
) -> int:
    """Build the HMAC CFG word for a SHA-2 variant / mode / key-length.

    ``sha_bits`` in {256,384,512}; ``key_bits`` in {128,256,384,512,1024} for keyed
    HMAC (pass None for plain SHA). Field positions come from the HMAC RDL
    through ``HMAC.field_lsb`` / ``HMAC_DIGEST_SIZE``.
    """
    cfg = int(bool(hmac_en)) << HMAC.field_lsb("CFG", "hmac_en")
    cfg |= 1 << HMAC.field_lsb("CFG", "sha_en")
    cfg |= (endian_swap & 1) << HMAC.field_lsb("CFG", "endian_swap")
    cfg |= (digest_swap & 1) << HMAC.field_lsb("CFG", "digest_swap")
    cfg |= (key_swap & 1) << HMAC.field_lsb("CFG", "key_swap")
    cfg |= HMAC_DIGEST_SIZE[sha_bits] << HMAC.field_lsb("CFG", "digest_size")
    if hmac_en:
        assert key_bits is not None, "keyed HMAC needs key_bits"
        cfg |= HMAC_KEY_LENGTH[key_bits] << HMAC.field_lsb("CFG", "key_length")
    return cfg & 0xFFFF_FFFF


HMAC_CFG_KEYED_256 = build_cfg(hmac_en=True, sha_bits=256, key_bits=256)
HMAC_CFG_SHA256 = build_cfg(hmac_en=False, sha_bits=256)


@dataclass
class SepHmacCfg:
    """Single source of truth for one HMAC variant cell: drives BOTH the DUT
    programming (CFG + key) and the golden expectation (env/sep_hmac_golden).

    The SW-key byte convention (``key_word_rev``/``key_be``/``msg_be``/
    ``digest_swap``) follows OT DV key_swap=0: KEY_0 first, big-endian per word
    (distinct from the keymgr sideload path).
    """

    sha_bits: int  # 256/384/512
    hmac_en: bool  # True = keyed HMAC, False = plain SHA
    key_bits: int | None  # 128/256/384/512/1024 (keyed) or None (plain)
    key_words: list[int]  # SW key words (len = key_bits/32); [] for plain
    msg_words: list[int]
    key_word_rev: bool = False
    key_be: bool = True
    msg_be: bool = False
    digest_swap: bool = False

    def cfg_word(self) -> int:
        return build_cfg(
            hmac_en=self.hmac_en,
            sha_bits=self.sha_bits,
            key_bits=self.key_bits,
            digest_swap=1 if self.digest_swap else 0,
        )

    def golden_kwargs(self) -> dict:
        return dict(
            hmac_en=self.hmac_en,
            sha_bits=self.sha_bits,
            msg_words=self.msg_words,
            key_words=self.key_words if self.hmac_en else None,
            key_word_rev=self.key_word_rev,
            key_be=self.key_be,
            msg_be=self.msg_be,
            digest_swap=self.digest_swap,
        )


class SepHmac(SepAxiRegDriver):
    """Direct-AXI OpenTitan HMAC run control. The test owns one instance."""

    _DRIVER_TAG = "HMAC"

    async def configure_keyed_256(self) -> None:
        """Configure keyed HMAC-SHA256, 256-bit key (sideload key used via KEY_VALID)."""
        await self._wr(HMAC_CFG, HMAC_CFG_KEYED_256)
        self.log.info("HMAC configured keyed-SHA256 256b (CFG=0x%08x)", HMAC_CFG_KEYED_256)

    async def read_public_key(self) -> tuple[list[int], int]:
        """Read the 32 public KEY CSRs, plus a positive control.

        These key registers are declared write-only and the generated register
        block ties their read data to a constant '0. Reading them back as zero is
        therefore NOT evidence that the sideloaded key is unexposed -- they read
        zero whether the key is protected, mirrored elsewhere, or never delivered.
        What the readback can do is catch the day they become readable. (The KMAC
        sibling can demonstrate this directly, because it writes a decoy to its key
        registers earlier in the run; nothing writes these HMAC ones, so here the
        claim rests on the generated register block rather than on an observation.)

        For that to be worth anything the read path must be known alive, so this
        also returns STATUS, a readable register in the same window over the same
        bus. A caller asserting the keys are zero must also assert the control
        read is non-zero; otherwise a dead read path returning zeros for everything
        would look identical to a pass.
        """
        keys = [await self._rd(HMAC_KEY_0 + i * 4) for i in range(HMAC_NUM_PUBLIC_KEY)]
        control = await self._rd(HMAC_STATUS)
        return keys, control

    async def run_keyed_mac(self, msg_words: list[int]) -> list[int]:
        """Run one keyed HMAC over msg_words; return the 8 DIGEST words (word0=MSB).

        start -> push message words to MSG_FIFO -> process -> wait done -> read
        DIGEST -> W1C the done event and assert it cleared (RW1C contract).
        """
        await self._wr(HMAC_CMD, HMAC_CMD_HASH_START)
        for word in msg_words:
            await self._wait_fifo_space()
            await self._wr(HMAC_MSG_FIFO, word & 0xFFFF_FFFF)
        await self._wr(HMAC_CMD, HMAC_CMD_HASH_PROCESS)
        await self._wait_done()
        digest = [await self._rd(HMAC_DIGEST_0 + i * 4) for i in range(8)]
        # W1C the done event and prove it clears (RW1C).
        await self._wr(HMAC_INTR_STATE, HMAC_INTR_DONE)
        post = await self._rd(HMAC_INTR_STATE)
        assert (post & HMAC_INTR_DONE) == 0, (
            f"HMAC INTR_STATE.hmac_done not cleared by W1C (0x{post:08x})"
        )
        return digest

    async def configure_sha256(self) -> None:
        """Configure plain SHA-256 (no key) -- a self-contained real hash op that
        leaves the result in the DIGEST CSRs, used as a held reset-domain state."""
        await self._wr(HMAC_CFG, HMAC_CFG_SHA256)
        self.log.info("HMAC configured plain SHA-256 (CFG=0x%08x)", HMAC_CFG_SHA256)

    async def read_digest(self) -> list[int]:
        """Read the 8 DIGEST words (word0 = MSB). Re-readable: HMAC holds DIGEST
        until the next hash_start / wipe / a reset of the HMAC domain."""
        return [await self._rd(HMAC_DIGEST_0 + i * 4) for i in range(8)]

    async def run_sha256(self, msg_words: list[int]) -> list[int]:
        """Run one SHA-256 over msg_words; return the 8 DIGEST words (word0=MSB).

        start -> push message words -> process -> wait done -> read DIGEST -> W1C
        the done event and assert it cleared (RW1C). DIGEST then HOLDS."""
        await self._wr(HMAC_CMD, HMAC_CMD_HASH_START)
        for word in msg_words:
            await self._wait_fifo_space()
            await self._wr(HMAC_MSG_FIFO, word & 0xFFFF_FFFF)
        await self._wr(HMAC_CMD, HMAC_CMD_HASH_PROCESS)
        await self._wait_done()
        digest = await self.read_digest()
        await self._wr(HMAC_INTR_STATE, HMAC_INTR_DONE)
        post = await self._rd(HMAC_INTR_STATE)
        assert (post & HMAC_INTR_DONE) == 0, (
            f"HMAC INTR_STATE.hmac_done not cleared by W1C (0x{post:08x})"
        )
        return digest

    async def configure(self, cfg_word: int) -> None:
        """Write the CFG word (build via ``build_cfg`` / ``SepHmacCfg.cfg_word``)."""
        await self._wr(HMAC_CFG, cfg_word)
        self.log.info("HMAC CFG=0x%08x", cfg_word)

    async def write_key(self, key_words: list[int]) -> None:
        """Write the SW key to the public KEY_0..KEY_{n-1} CSRs (n = len)."""
        for i, word in enumerate(key_words):
            await self._wr(HMAC_KEY_0 + i * 4, word & 0xFFFF_FFFF)

    async def run_mac(self, msg_words: list[int], *, sha_bits: int) -> list[int]:
        """Run one hash (keyed or plain per the current CFG) over msg_words.

        Returns the DIGEST words for the SHA-2 variant (8/12/16). start -> push
        message -> process -> wait done -> read DIGEST -> W1C the done event and
        assert it cleared (RW1C)."""
        await self._wr(HMAC_CMD, HMAC_CMD_HASH_START)
        for word in msg_words:
            await self._wait_fifo_space()
            await self._wr(HMAC_MSG_FIFO, word & 0xFFFF_FFFF)
        await self._wr(HMAC_CMD, HMAC_CMD_HASH_PROCESS)
        await self._wait_done()
        digest = [await self._rd(HMAC_DIGEST_0 + i * 4) for i in range(HMAC_DIGEST_WORDS[sha_bits])]
        await self._wr(HMAC_INTR_STATE, HMAC_INTR_DONE)
        post = await self._rd(HMAC_INTR_STATE)
        assert (post & HMAC_INTR_DONE) == 0, (
            f"HMAC INTR_STATE.hmac_done not cleared by W1C (0x{post:08x})"
        )
        return digest

    async def wait_idle(self, tag: str, *, timeout: int = 4_000, poll_cycles: int = 20) -> None:
        """Poll STATUS until hmac_idle. A caller that has just released this
        domain from reset needs the core to be accepting again before it can
        attribute a refusal to anything other than the core being busy."""
        for i in range(timeout):
            if await self._rd(HMAC_STATUS) & HMAC_STATUS_IDLE:
                self.log.info("HMAC idle (%s) after %d polls", tag, i)
                return
            if i and i % 500 == 0:
                self.log.info("HMAC wait_idle (%s): poll %d", tag, i)
            await ClockCycles(cocotb.top.clk_i, poll_cycles)
        raise AssertionError(f"HMAC did not reach STATUS.hmac_idle ({tag})")

    async def _wait_fifo_space(self, *, timeout: int = 2_000, poll_cycles: int = 10) -> None:
        for _ in range(timeout):
            if not (await self._rd(HMAC_STATUS) & HMAC_STATUS_FIFO_FULL):
                return
            await ClockCycles(cocotb.top.clk_i, poll_cycles)
        raise AssertionError("HMAC MSG FIFO stayed full (no space)")

    async def _wait_done(self, *, timeout: int = 4_000, poll_cycles: int = 20) -> None:
        for i in range(timeout):
            if await self._rd(HMAC_INTR_STATE) & HMAC_INTR_DONE:
                return
            if i and i % 500 == 0:
                self.log.info("HMAC wait_done: poll %d", i)
            await ClockCycles(cocotb.top.clk_i, poll_cycles)
        raise AssertionError("HMAC hash never signaled done")

    async def check_status_clean(self, tag: str = "EOT") -> None:
        """Assert HMAC raised no error: ERR_CODE == 0 and INTR_STATE.hmac_err == 0."""
        err = await self._rd(HMAC_ERR_CODE)
        intr = await self._rd(HMAC_INTR_STATE)
        assert err == 0, f"HMAC ERR_CODE=0x{err:08x} [{tag}]"
        assert (intr & HMAC_INTR_ERR) == 0, f"HMAC INTR_STATE.hmac_err set [{tag}] (0x{intr:08x})"
        self.log.info("HMAC STATUS clean [%s]: ERR_CODE=0, hmac_err=0", tag)
