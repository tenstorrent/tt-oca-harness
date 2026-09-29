# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Adams Bridge ML-DSA-87 keyGen driver (sep_abr_mldsa_keygen_kat_test).

Aperture base is the ABR row of ``hw/sys/sep/doc/memory_map.adoc``.
Register offsets come from the Caliptra ``abr_reg.rdl``. The RDL declares the
``MLDSA_NAME`` / ``MLDSA_VERSION`` identity words ``sw = r`` with no reset, and
no SEP document gives their values, so this driver holds their addresses
only. 32-bit beats (size=2) on the 64-bit port, one register per access;
STATUS at +0x14 is an odd-word offset. ``[[abr-access-size]]`` in ``hw/sys/sep/doc/adams_bridge.adoc`` gives
the rules for other access sizes.
"""

from __future__ import annotations

from env.sep_seeded_rng import SepSeededRng
from env.sep_spec_tables import (
    abr_ctrl_cmd,
    abr_field_mask,
    abr_off,
    agg_from_pic,
    kv_field_mask,
    window,
)

from seq_lib.sep_axi_reg_driver import SepAxiRegDriver

ABR_BASE = window("ABR").base
ABR_NAME0 = ABR_BASE + abr_off("MLDSA_NAME")
ABR_NAME1 = ABR_NAME0 + 4
ABR_VERSION0 = ABR_BASE + abr_off("MLDSA_VERSION")
ABR_VERSION1 = ABR_VERSION0 + 4
ABR_CTRL = ABR_BASE + abr_off("MLDSA_CTRL")
ABR_STATUS = ABR_BASE + abr_off("MLDSA_STATUS")
ABR_ENTROPY = ABR_BASE + abr_off("ABR_ENTROPY")
ABR_SEED = ABR_BASE + abr_off("MLDSA_SEED")
ABR_PUBKEY = ABR_BASE + abr_off("MLDSA_PUBKEY")
ABR_MLDSA_KV_RD_SEED_CTRL = ABR_BASE + abr_off("kv_mldsa_seed_rd_ctrl")
ABR_KV_RD_SEED_READ_EN = kv_field_mask("kv_read_ctrl_reg", "read_en")
ABR_INTR = ABR_BASE + abr_off("intr_block_rf")
ABR_GLOBAL_INTR_EN = ABR_INTR + abr_off("global_intr_en_r")
ABR_ERROR_INTR_EN = ABR_INTR + abr_off("error_intr_en_r")
ABR_NOTIF_INTR_EN = ABR_INTR + abr_off("notif_intr_en_r")
ABR_ERROR_INTR = ABR_INTR + abr_off("error_internal_intr_r")
ABR_ERROR_TRIG = ABR_INTR + abr_off("error_intr_trig_r")
ABR_NOTIF_INTR = ABR_INTR + abr_off("notif_internal_intr_r")

CMD_KEYGEN = abr_ctrl_cmd("MLDSA_CTRL", "KEYGEN")
CMD_SIGN = abr_ctrl_cmd("MLDSA_CTRL", "SIGN")
CMD_VERIFY = abr_ctrl_cmd("MLDSA_CTRL", "VERIFY")
CTRL_ZEROIZE = abr_field_mask("MLDSA_CTRL", "ZEROIZE")
# MLDSA_CTRL.EXTERNAL_MU. The vendored sigGen/sigVer vectors are the ACVP
# external-mu groups, so the engine is handed mu directly instead of a message.
CTRL_EXTERNAL_MU = abr_field_mask("MLDSA_CTRL", "EXTERNAL_MU")
ST_READY = abr_field_mask("MLDSA_STATUS", "READY")
ST_VALID = abr_field_mask("MLDSA_STATUS", "VALID")
ST_ERROR = abr_field_mask("MLDSA_STATUS", "ERROR")

SEED_WORDS = 8
ENTROPY_WORDS = 16
PK_WORDS = 648
SK_WORDS = 1224
MU_WORDS = 16
SIG_WORDS = 1157
# MLDSA_VERIFY_RES[N] in abr_reg.rdl; c~ is those leading signature words.
VERIFY_RES_WORDS = (abr_off("MLDSA_EXTERNAL_MU") - abr_off("MLDSA_VERIFY_RES")) // 4

# Sign / verify register windows, by symbol from the vendor RDL like the
# keygen ones above.
ABR_MSG = ABR_BASE + abr_off("MLDSA_MSG")
ABR_EXTERNAL_MU = ABR_BASE + abr_off("MLDSA_EXTERNAL_MU")
ABR_SIGN_RND = ABR_BASE + abr_off("MLDSA_SIGN_RND")
ABR_SIGNATURE = ABR_BASE + abr_off("MLDSA_SIGNATURE")
ABR_VERIFY_RES = ABR_BASE + abr_off("MLDSA_VERIFY_RES")
ABR_PRIVKEY_IN = ABR_BASE + abr_off("MLDSA_PRIVKEY_IN")

IRQ_ABR_ERROR = agg_from_pic("Adams Bridge error")
IRQ_ABR_NOTIF = agg_from_pic("Adams Bridge notification")

INTR_ERROR_EN = abr_field_mask("global_intr_en_r", "error_en")
INTR_NOTIF_EN = abr_field_mask("global_intr_en_r", "notif_en")
INTR_GLOBAL_BOTH = INTR_ERROR_EN | INTR_NOTIF_EN
INTR_EVENT_EN = abr_field_mask("error_intr_en_r", "error_internal_en")


class SepAbrKeygenCfg:
    """RANDCFG: masking entropy words, and which seed word/bit the sensitivity flips."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        self.entropy = [rng.getrandbits(32) for _ in range(ENTROPY_WORDS)]
        if not any(w != 0 for w in self.entropy):
            self.entropy[0] = 0xA5A5A5A5
        self.flip_word = rng.randrange(SEED_WORDS)
        self.flip_bit = rng.randrange(32)

    def flipped_seed(self, seed_words: list[int]) -> list[int]:
        out = list(seed_words)
        out[self.flip_word] ^= 1 << self.flip_bit
        return out

    def summary(self) -> str:
        return (
            f"seed={self.seed} flip_word={self.flip_word} flip_bit={self.flip_bit} "
            f"entropy[0]=0x{self.entropy[0]:08x}"
        )


class SepAbr(SepAxiRegDriver):
    """32-bit ABR CSR / memory-window driver on the CPU-LSU bus."""

    _DRIVER_TAG = "ABR"

    async def wr32(self, addr: int, data: int) -> None:
        await self._wr(addr, data & 0xFFFF_FFFF)

    async def rd32(self, addr: int) -> int:
        return await self._rd(addr)

    async def write_words(self, base: int, words: list[int]) -> None:
        for i, w in enumerate(words):
            await self.wr32(base + 4 * i, w)

    async def read_words(self, base: int, n: int) -> list[int]:
        return [await self.rd32(base + 4 * i) for i in range(n)]

    async def enable_notif(self) -> None:
        await self.wr32(ABR_GLOBAL_INTR_EN, INTR_GLOBAL_BOTH)
        await self.wr32(ABR_ERROR_INTR_EN, INTR_EVENT_EN)
        await self.wr32(ABR_NOTIF_INTR_EN, INTR_EVENT_EN)

    async def trigger_error(self) -> None:
        """Pulse error_intr_trig (single-cycle W1S) to set error_internal_sts."""
        await self.wr32(ABR_ERROR_TRIG, INTR_EVENT_EN)

    async def error_state(self) -> int:
        return await self.rd32(ABR_ERROR_INTR)

    async def w1c_error(self) -> int:
        """W1C error_internal_sts; return the post-clear readback."""
        await self.wr32(ABR_ERROR_INTR, INTR_EVENT_EN)
        return await self.rd32(ABR_ERROR_INTR)

    async def notif_state(self) -> int:
        return await self.rd32(ABR_NOTIF_INTR)

    async def w1c_notif(self) -> int:
        """W1C notif_cmd_done_sts; return the post-clear readback."""
        await self.wr32(ABR_NOTIF_INTR, INTR_EVENT_EN)
        return await self.rd32(ABR_NOTIF_INTR)


def _selftest() -> None:
    assert ABR_BASE == 0x1094_0000
    assert ABR_CTRL - ABR_BASE == 0x10
    assert ABR_STATUS - ABR_BASE == 0x14
    assert ABR_ENTROPY - ABR_BASE == 0x18
    assert ABR_SEED - ABR_BASE == 0x58
    assert ABR_PUBKEY - ABR_BASE == 0x1000
    # Sign / verify windows, pinned so a bad RDL resolution fails at import
    # rather than as a mid-simulation wrong-address access.
    assert ABR_SIGN_RND - ABR_BASE == 0x78
    assert ABR_MSG - ABR_BASE == 0x98
    assert ABR_VERIFY_RES - ABR_BASE == 0xD8
    assert ABR_EXTERNAL_MU - ABR_BASE == 0x118
    assert VERIFY_RES_WORDS == 16
    assert ABR_VERIFY_RES + 4 * VERIFY_RES_WORDS == ABR_EXTERNAL_MU
    assert ABR_SIGNATURE - ABR_BASE == 0x2000
    assert ABR_PRIVKEY_IN - ABR_BASE == 0x6000
    # The four windows a sign or verify touches must not overlap each other.
    assert ABR_SIGNATURE + 4 * SIG_WORDS <= ABR_PRIVKEY_IN
    assert ABR_ERROR_INTR - ABR_INTR == 0x14
    assert ABR_ERROR_TRIG - ABR_INTR == 0x1C
    assert ABR_NOTIF_INTR - ABR_INTR == 0x18
    assert ABR_VERSION0 - ABR_NAME0 == 0x8
    cfg = SepAbrKeygenCfg(1)
    assert len(cfg.entropy) == ENTROPY_WORDS
    flipped = cfg.flipped_seed([0] * SEED_WORDS)
    assert flipped[cfg.flip_word] == (1 << cfg.flip_bit)


_selftest()
