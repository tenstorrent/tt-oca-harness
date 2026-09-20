# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sideload varied key material to every crypto engine in one run.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more.

Target (docs/SEP_COV_VPLAN.adoc, "SEP system fabric, system CSR and crypto
interconnect"): `key_csr_hwif_out.KEY_SHARE0[*]` / `KEY_SHARE1[*]` in the HMAC
and KMAC wrappers, `key_csr_hwif_out` in `sep_crypto_otbn_wrapper`,
`abr_key_hwif_out` in `sep_crypto_abr_wrapper`, and `hwif_i` plus the
`read_entry` / `write_entry` indices in `sep_abr_kv_shim`. The per-engine
sideload KATs each run in their own leaf with one fixed key, so the key words
hold one value and the key-vault indices stay at slot 0.

Stimulus: boot the KM firmware on real entropy, then for each of HMAC, KMAC,
OTBN and the ABR ML-DSA seed, provision a key over the mailbox with
CMD_KEY_LOAD and sideload it with CMD_KEY_TRANSFER, in one run. Each engine
gets its own key whose words alternate 0xFFFF_FFFF / 0xAAAA_AAAA /
0x5555_5555, and each CMD_KEY_LOAD takes the next key-vault handle, so the
shim's read and write entry indices leave slot 0.

The bring-up is the one the per-engine sideload KATs use: a PROD eFuse image,
the four sideload targets parked across reset so the EDN stream stays
dedicated to the KM, strict entropy bring-up, then KM release. HMAC, KMAC and
OTBN are released before their transfer, because CMD_KEY_TRANSFER has the KM
write key CSRs that sit in each engine's software-reset domain; ABR keeps its
released reset default.

This leaf does not read a key back and does not run any engine: the sideload
is driven, nothing is compared.

cpu_stub (no_cpu) with real fuse sense.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_km_mailbox_seq import (
    KM_DEST_ABR_MLDSA_SEED,
    KM_DEST_HMAC,
    KM_DEST_KMAC,
    KM_DEST_OTBN,
    SepKmMailbox,
)

# 256-bit keys, one per destination, whose words alternate the three patterns
# so each engine's KEY_SHARE words carry a different bit picture.
KEY_PATTERNS = (0xFFFF_FFFF, 0xAAAA_AAAA, 0x5555_5555)
KEY_WORDS = 8


def _key(rotation: int) -> list[int]:
    """An 8-word key whose pattern order is rotated by ``rotation``."""
    return [KEY_PATTERNS[(rotation + i) % len(KEY_PATTERNS)] for i in range(KEY_WORDS)]


# (destination mask, software-reset engine name to release first, key).
# ABR is not in the parked set, so it needs no release here.
TRANSFERS = (
    (KM_DEST_HMAC, "hmac", _key(0)),
    (KM_DEST_KMAC, "kmac", _key(1)),
    (KM_DEST_OTBN, "otbn", _key(2)),
    (KM_DEST_ABR_MLDSA_SEED, None, _key(0)),
)


@pyuvm.test()
class sep_cov_crypto_key_share_walk_test(sep_base_test):
    """Key sideload to HMAC, KMAC, OTBN and ABR in one run. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        image = self.select_efuse_image(lc_raw=0x1)  # LC_PROD: KM reads OTP at boot
        self.write_efuse_image(image)
        await self.bring_up_no_cpu(park=("otbn", "aes", "hmac", "kmac"))

        self.km = SepKmMailbox(self)

        await self.bring_up_entropy(strict=True, score_km="observe")
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.start_fifo_drain()

        await self.swrst.release("km")
        await self.km.wait_km_ready()

        for dest, engine, key in TRANSFERS:
            if engine is not None:
                await self.swrst.release(engine)
            handle = await self.km.key_load(key_words=key, dest=dest)
            rc, arg = await self.km.key_transfer(handle=handle, dest=dest)
            self.logger.info(
                "sideload driven: dest=0x%02x handle=0x%02x rc=%d arg=0x%08x "
                "(logged, not graded)",
                dest,
                handle,
                rc,
                arg,
            )
