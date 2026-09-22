# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KM -> KMAC sideload consume-proof KAT (reference suite, sep_km_kmac_sideload_kat_test).

Real DRBG entropy boots the real KM firmware (rom_main). The host (CPU-LSU
frontdoor AXI) provisions a KNOWN 256-bit key into a KPV handle via CMD_KEY_LOAD,
then CMD_KEY_TRANSFERs it to the OpenTitan KMAC engine. KMAC computes a keyed
KMAC-256 (cSHAKE, PREFIX="KMAC") over a fixed message; the test proves KMAC
consumed exactly the sideloaded key.

KMAC DOES have a CFG.sideload bit, so (like AES, unlike HMAC) the consume-proof is
a sideload-vs-SW cross-check rather than a comparison against a known answer
(env/sep_kmac_golden.py holds a bit-exact KMAC model; sep_kmac_mode_strength_rand_test
compares it against this engine). The OSS port is a FRONTDOOR
known-key variant: it loads a KNOWN distinct-word key, so the cross-check ties the
sideload output to that specific key via the SW path, and the dummy-key negative
reference proves the key actually drives the output. Consume-proof is
sideload-vs-SW plus decoy difference, not a KMAC golden.

VPLAN-parity checkers:
  CHK0      boot KM on real DRBG -> RESP_KM_READY
  CHK-A     CMD_KEY_LOAD known key (frontdoor; wrapper shares are write-only)
  CHK-NEG   negative ref: keyed MAC with a DUMMY SW key -> c_dummy (a real op)
  CHK-ISO   key-bus isolation by SW_RESET_N read-back: only KMAC of the four
            sideload targets released; AES/HMAC/OTBN parked
  CHK-B     CMD_KEY_TRANSFER rc=0 to KMAC
  PUB-OBS   public KMAC KEY_SHARE0/1 read back zero after sideload. NOT a checker:
            kmac.hjson declares them swaccess=wo, so the read cannot fail
  CHK-SIDE  sideload digest != dummy digest (the sideloaded key drives the output)
  CHK-MAC   sideload digest == SW-key(KNOWN key) digest (consume-proof: KMAC used
            exactly the KM-delivered known key)
  CHK-ENT   KMAC consumed real DRBG/EDN masking entropy during the keyed ops --
            proven by the CHK5_kmac sink (>=1 post-adapter crypto-EDN beat to KMAC),
            the OSS frontdoor analog of the reference suite's backdoor kmac EDN ack-count delta
  CHK-ERR   KMAC ERR_CODE == 0
  CHK1..CHK4 strict DRBG golden + CHK5_km observed (KM boot/load consumer)

Scope deltas vs the reference suite:
  * Like the reference suite, no bit-exact KMAC golden -- the consume-proof is the cross-check.
    The OSS port strengthens it with a KNOWN distinct-word key (vs the reference suite's
    backdoor-reconstructed KM-generated key), so no backdoor and no key/mask
    non-degeneracy guards are needed (the known key is non-degenerate by
    construction; the wrapper-internal SHARE0 mask non-degeneracy is out of
    frontdoor scope, covered by the OTBN sideload KAT, as for the AES / HMAC KATs).
  * key-bus isolation uses SW_RESET_N read-back (no OSS frontdoor analog of the reference suite's
    key-bus AW monitor); CHK-MAC additionally proves KMAC got the correct key.

Boot recipe matches the OTBN/AES/HMAC KATs (real fuse-sense, valid PROD OTP image).
KMAC IS an EDN consumer (masking entropy), so it is parked through KM boot/load for
clean isolation + entropy dedication, then released before the transfer,
after which its keyed ops pull real EDN masking entropy (scored via CHK5_kmac).
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_km_mailbox_seq import KM_DEST_KMAC, SepKmMailbox
from seq_lib.sep_kmac_seq import SepKmac
from seq_lib.sep_sw_reset_seq import SW_RESET_N_BIT

# Known 256-bit KAT key: 8 DISTINCT 32-bit words (non-degenerate by construction).
KAT_KEY = (
    0xDEADBEEF,
    0x00112233,
    0x44556677,
    0x8899AABB,
    0xCCDDEEFF,
    0x01234567,
    0x89ABCDEF,
    0xFEDCBA98,
)

# Fixed message (reference KMAC_MSG): bytes 0x00..0x1f as 8 words.
KMAC_MSG = (
    0x00010203,
    0x04050607,
    0x08090A0B,
    0x0C0D0E0F,
    0x10111213,
    0x14151617,
    0x18191A1B,
    0x1C1D1E1F,
)

# Unrelated dummy key for the negative reference.
KMAC_DUMMY_KEY = (
    0xDEADBEEF,
    0xCAFEF00D,
    0x12345678,
    0x9ABCDEF0,
    0x0F0E0D0C,
    0x0B0A0908,
    0x07060504,
    0x03020100,
)


@pyuvm.test()
class sep_km_kmac_sideload_kat_test(sep_base_test):
    """KM->KMAC sideload consume-proof (frontdoor, real rom_main, known key)."""

    async def run_scenario(self) -> None:
        # --- Boot the real KM firmware on real entropy -------------------------
        image = self.select_efuse_image(lc_raw=0x1)  # LC_PROD (KM reads OTP at boot)
        self.write_efuse_image(image)
        await self.bring_up_no_cpu(park=("otbn", "aes", "hmac", "kmac"))

        self.km = SepKmMailbox(self)
        self.kmac = SepKmac(self)

        # All four sideload targets JTAG-held across rst_ni release, then parked in SW_RESET_N. KMAC is released only
        # before the transfer so its keyed ops pull EDN masking entropy.

        # Strict entropy bring-up: CHK1..CHK4 bit-exact golden; CHK5_km observed
        # (KM boot/load consumer). score_sinks kmac="observe": prove KMAC pulls real
        # post-adapter crypto-EDN masking beats during its keyed ops -- the frontdoor
        # analog of the reference suite's backdoor kmac EDN ack-count (CHK-ENT). The drain keeps the
        # ESRC FIFO from overflowing during the long entropy phase.
        await self.bring_up_entropy(
            strict=True, score_km="observe", score_sinks={"kmac": "observe"}
        )
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.start_fifo_drain()
        self.logger.info("real entropy flowing; releasing KM firmware (rom_main)")

        await self.swrst.release("km")
        await self.km.wait_km_ready()
        self.logger.info("CHK0 KM firmware boot PASS: RESP_KM_READY over the mailbox")

        # --- Frontdoor consume-proof: load known key -> transfer -> keyed MAC ---
        # CHK-A: provision the KNOWN key into a KPV handle over the frontdoor.
        handle = await self.km.key_load(key_words=list(KAT_KEY), dest=KM_DEST_KMAC)
        self.logger.info("CHK-A CMD_KEY_LOAD PASS: known key staged, handle=0x%02x", handle)

        # Release KMAC before the transfer: the KM writes the KMAC wrapper key CSRs
        # (kmac sw-reset domain). Released here so it can also run the negative-ref MAC.
        await self.swrst.release("kmac")

        # CHK-NEG: negative reference -- keyed MAC with an unrelated DUMMY SW key.
        c_dummy = await self.kmac.keyed_mac(
            list(KMAC_MSG), sideload=False, sw_key=list(KMAC_DUMMY_KEY)
        )
        # c_dummy is the negative reference CHK-SIDE compares against, so it has to be
        # a real observation before that comparison means anything: an all-zero garbage
        # read would satisfy `a_side != c_dummy` while proving nothing. There is no
        # bit-exact KMAC golden wired up here (see the module docstring), so this is an
        # alive-check, not a value check. An all-zero dummy digest would make CHK-SIDE
        # vacuous.
        assert any(w != 0 for w in c_dummy), (
            "dummy-key KMAC returned an all-zero digest -- the negative reference is "
            f"not a real observation, so CHK-SIDE below would be vacuous: {[hex(w) for w in c_dummy]}"
        )
        self.logger.info(
            "CHK-NEG dummy-key KMAC PASS: non-zero digest observed (alive, not "
            "value-compared): c_dummy=%s",
            [hex(w) for w in c_dummy],
        )

        # CHK-ISO: only KMAC (of the four sideload targets) is released; others parked.
        rst = await self.swrst.read_back()
        parked = (
            (1 << SW_RESET_N_BIT["aes"])
            | (1 << SW_RESET_N_BIT["hmac"])
            | (1 << SW_RESET_N_BIT["otbn"])
        )
        assert (rst & parked) == 0, (
            f"key-bus isolation: AES/HMAC/OTBN not parked (SW_RESET_N=0x{rst:08x})"
        )
        assert rst & (1 << SW_RESET_N_BIT["kmac"]), (
            f"KMAC not released for the transfer (SW_RESET_N=0x{rst:08x})"
        )
        self.logger.info(
            "CHK-ISO key-bus isolation PASS: only KM+KMAC released, "
            "AES/HMAC/OTBN parked (SW_RESET_N=0x%02x)",
            rst,
        )

        # CHK-B: sideload the handle's key to the KMAC wrapper KEY CSRs.
        rc, _ = await self.km.key_transfer(handle=handle, dest=KM_DEST_KMAC)
        assert rc == 0, f"CMD_KEY_TRANSFER returned rc={rc} (expected 0)"
        self.logger.info("CHK-B CMD_KEY_TRANSFER PASS: rc=0 (key sideloaded to KMAC)")

        # PUB-OBSERVATION: the public KEY_SHARE CSRs read zero. Logged, not scored
        # -- kmac.hjson declares them swaccess=wo, so "reads zero" holds on any RTL.
        s0_pub, s1_pub, ctl_pub = await self.kmac.read_public_key_shares()
        assert all(w == 0 for w in s0_pub + s1_pub), (
            "KMAC public KEY_SHARE0/1 not all zero after sideload (key leak): "
            f"s0={[hex(w) for w in s0_pub if w]} s1={[hex(w) for w in s1_pub if w]}"
        )
        assert ctl_pub != 0, (
            "PUB-OBSERVATION positive control failed: KMAC STATUS read back 0 over the same "
            "frontdoor, so the all-zero KEY_SHARE reads prove nothing about the key"
        )
        self.logger.info(
            "PUB-OBSERVATION KMAC public KEY_SHARE0/1 frontdoor reads zero after "
            "sideload. Not scored: kmac.hjson declares them swaccess=wo, so this read "
            "cannot fail. Read path alive: STATUS=%#010x",
            ctl_pub,
        )

        # CHK-SIDE/CHK-MAC: sideload MAC, then SW-key MAC with the KNOWN key.
        a_side = await self.kmac.keyed_mac(list(KMAC_MSG), sideload=True)
        assert a_side != c_dummy, (
            "KMAC sideload digest equals the dummy-key digest (key not consumed)"
        )
        self.logger.info("CHK-SIDE PASS: sideload digest != dummy-key digest")

        b_swref = await self.kmac.keyed_mac(list(KMAC_MSG), sideload=False, sw_key=list(KAT_KEY))
        assert a_side == b_swref, (
            "KMAC sideload vs SW-key(known) digest mismatch -- KMAC did not consume "
            "the exact KM-delivered key:\n"
            f"  a_side ={[hex(w) for w in a_side]}\n"
            f"  b_swref={[hex(w) for w in b_swref]}"
        )
        # Not "KAT": both digests come from this engine, so this is a cross-check
        # against the known key, not a comparison with a known answer.
        self.logger.info(
            "CHK-MAC KM->KMAC sideload PASS: sideload digest == SW-key(known) digest "
            "(engine cross-check, not a golden)"
        )

        # CHK-ERR: KMAC raised no error across the keyed ops.
        await self.kmac.check_status_clean("EOT")

        # --- EOT: entropy health + clean shutdown ------------------------------
        # CHK-ENT (KMAC masking entropy) + CHK1..CHK5 are finalized by the strict
        # scoreboard report: CHK5_kmac requires >=1 real crypto-EDN beat to KMAC.
        await self.km.check_outbound_empty("EOT")
        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report()
        self.logger.info("CHK-ENT + CHK1..CHK5 alive + entropy alerts PASS (DRBG scoreboard)")
