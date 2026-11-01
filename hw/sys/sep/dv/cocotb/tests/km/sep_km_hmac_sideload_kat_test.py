# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""HMAC computes with exactly the key the KM sideloads, not the software decoy key.

Real DRBG entropy boots the real KM firmware (rom_main). The host (CPU-LSU
frontdoor AXI) provisions a KNOWN 256-bit key into a KPV handle via CMD_KEY_LOAD,
then CMD_KEY_TRANSFERs it to the OpenTitan HMAC engine. The host runs a keyed
HMAC-SHA256 over a fixed message with the sideloaded key and proves HMAC consumed
exactly that key: the engine digest equals an independent HMAC-SHA256 golden
(env/sep_hmac_golden.py, Python stdlib hmac/hashlib, RFC 4231 self-tested) of the
known key.

HMAC has NO CFG sideload bit and KEY_VALID is set on the KM's private key bus
(the host cannot clear it), so the AES-style run of the same operation once with
the SW key and once with the sideload key is not possible. The decoy leg takes
its place: before the transfer, while KEY_CTRL.KEY_VALID is clear, the host
writes a seeded software decoy key to the public KEY CSRs and runs the keyed
MAC; that digest must equal the golden of the decoy (CTRL-DECOY-LIVE), which
proves the decoy is in the KEY CSRs and the engine uses them. After the
transfer, with KEY_VALID set, the host writes the same decoy to the KEY CSRs
again (each write OKAY), and neither writes WIPE_SECRET (the register that
clears the secret key, hmac.hjson) nor resets the HMAC domain before the graded
MAC. The digest after the transfer must equal the golden of the KM key and
differ from the golden of the decoy, so an engine that takes the CSR key over
the sideloaded key, a transfer that lands in the KEY CSR storage, or a KEY
write that displaces the sideloaded key fails.

The key is known a priori and the digest is checked directly against the golden
under key_word_rev=1, key_be=1, msg_be=0, so a truncated, word-swapped or
wrong-key sideload changes the digest and fails.

Checkers:
  CHK0      boot KM on real DRBG -> RESP_KM_READY
  CHK-A     CMD_KEY_LOAD known key (frontdoor; wrapper shares are write-only)
  CHK-ISO   key-bus isolation by SW_RESET_N read-back: only HMAC of the four
            non-ABR sideload engines released; AES/KMAC/OTBN parked
  CTRL-DECOY-LIVE  before the transfer, the keyed digest with the decoy in the
            KEY CSRs == HMAC-SHA256(decoy_key, msg) golden under the SW-key
            convention (KEY_0 first, big-endian per word)
  CHK-B     CMD_KEY_TRANSFER rc=0 to HMAC
  CTRL-DECOY-REWRITE  after the transfer, every write of the decoy to the
            KEY CSRs answers OKAY
  PUB-OBSERVATION  HMAC public KEY CSRs read back zero after the sideload. NOT a
            checker: hmac.hjson declares KEY swaccess=wo, so the read returns zero
            whether the key is protected, mirrored elsewhere, or never delivered.
            CHK-DECOY and CHK-MAC carry the key-protection evidence that can fail.
  CHK-DECOY engine keyed digest != HMAC-SHA256(decoy_key, msg) golden, where the
            decoy is the seeded SW key that CTRL-DECOY-LIVE proved live in the
            public KEY CSRs (the engine did not use the CSR key)
  CHK-MAC   engine keyed digest == HMAC-SHA256(known_key, msg) golden (consume-proof)
  CHK-RW1C  HMAC done event W1C-clears (INTR_STATE.hmac_done -> 0)
  CHK-ERR   HMAC ERR_CODE == 0 and INTR_STATE.hmac_err == 0
  CHK1..CHK4 strict DRBG golden + CHK5_km observed (the KM boot/load consumer);
            HMAC is not an EDN consumer, so no crypto EDN sink is scored.
  CHK5      the KM draws real entropy beats while the key is staged: the
            CHK5_km beat count taken just before CMD_KEY_LOAD is lower than
            the count taken after the CMD_KEY_TRANSFER response

Scope:
  * The known-key golden compare under key_word_rev=1 / key_be=1 proves the exact
    key flowed. The HMAC-wrapper-internal SHARE0 mask non-degeneracy is out of
    frontdoor scope; km/sep_km_otbn_sideload_kat_test CHK-F covers it frontdoor,
    as for km/sep_km_aes_sideload_kat_test.
  * Key-bus isolation is graded by SW_RESET_N read-back; CHK-MAC also proves HMAC
    got the correct key.

Boot recipe matches km/sep_km_otbn_sideload_kat_test and
km/sep_km_aes_sideload_kat_test (real fuse-sense, valid PROD OTP image; rom_main
built with KM_BOOT_WIPE=0 / KM_UNREC_WIPE=0). HMAC is not an EDN consumer, so
(unlike AES) it is parked through KM boot/load for clean isolation and released
just before the transfer (like OTBN), keeping the EDN stream dedicated to the KM.
"""

from __future__ import annotations

import pyuvm
from env.sep_chk_log import SepChkLog
from env.sep_hmac_golden import hmac_sha256_words
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from seq_lib.sep_hmac_seq import SepHmac
from seq_lib.sep_km_mailbox_seq import KM_DEST_HMAC, SepKmMailbox
from seq_lib.sep_sw_reset_seq import SW_RESET_N_BIT

TEST = "sep_km_hmac_sideload_kat_test"

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

# Fixed message: 8 words 0x00010203..0x1C1D1E1F; msg_be=0 feeds each word little-endian.
HMAC_MSG = (
    0x00010203,
    0x04050607,
    0x08090A0B,
    0x0C0D0E0F,
    0x10111213,
    0x14151617,
    0x18191A1B,
    0x1C1D1E1F,
)


@pyuvm.test()
class sep_km_hmac_sideload_kat_test(sep_base_test):
    """The sideloaded known key gives the golden HMAC digest and not the decoy digest."""

    async def run_scenario(self) -> None:
        # --- Boot the real KM firmware on real entropy -------------------------
        image = self.select_efuse_image(lc_raw=0x1)  # LC_PROD (KM reads OTP at boot)
        self.write_efuse_image(image)
        await self.bring_up_no_cpu(park=("otbn", "aes", "hmac", "kmac"))

        self.km = SepKmMailbox(self)
        self.hmac = SepHmac(self)

        # The four non-ABR sideload engines (OTBN, AES, HMAC, KMAC) are JTAG-held
        # across rst_ni release, then parked in SW_RESET_N. HMAC is not an EDN
        # consumer; it stays parked through boot/load and is released only
        # before the transfer.

        # Strict entropy bring-up: CHK1..CHK4 bit-exact golden; CHK5_km observed
        # (rom_main pull order is firmware-driven). No crypto EDN sink scored --
        # HMAC requests no entropy.
        await self.bring_up_entropy(strict=True, score_km="observe")
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.start_fifo_drain()
        self.logger.info("real entropy flowing; releasing KM firmware (rom_main)")

        await self.swrst.release("km")
        await self.km.wait_km_ready()
        self.logger.info("CHK0 KM firmware boot PASS: RESP_KM_READY over the mailbox")

        # --- Frontdoor consume-proof: load known key -> transfer -> keyed MAC ---
        # CHK5 window opens here: KM entropy beats counted from CMD_KEY_LOAD
        # to the CMD_KEY_TRANSFER response, not over the whole run.
        km_beats_at_load = self.drbg_sb.km_beats()

        # CHK-A: provision the KNOWN key into a KPV handle over the frontdoor.
        handle = await self.km.key_load(key_words=list(KAT_KEY), dest=KM_DEST_HMAC)
        self.logger.info("CHK-A CMD_KEY_LOAD PASS: known key staged, handle=0x%02x", handle)

        # Release HMAC before the transfer: CMD_KEY_TRANSFER has the KM write the HMAC
        # wrapper key CSRs, which sit in the hmac sw-reset domain; parked -> the write
        # never lands.
        await self.swrst.release("hmac")

        # CHK-ISO: only HMAC (of the four non-ABR sideload engines) is released; AES/KMAC/OTBN
        # stay parked and cannot receive the key.
        rst = await self.swrst.read_back()
        parked = (
            (1 << SW_RESET_N_BIT["aes"])
            | (1 << SW_RESET_N_BIT["kmac"])
            | (1 << SW_RESET_N_BIT["otbn"])
        )
        assert (rst & parked) == 0, (
            f"key-bus isolation: AES/KMAC/OTBN not parked (SW_RESET_N=0x{rst:08x})"
        )
        assert rst & (1 << SW_RESET_N_BIT["hmac"]), (
            f"HMAC not released for the transfer (SW_RESET_N=0x{rst:08x})"
        )
        self.logger.info(
            "CHK-ISO key-bus isolation PASS: only KM+HMAC released, "
            "AES/KMAC/OTBN parked (SW_RESET_N=0x%02x)",
            rst,
        )

        # Decoy leg: a seeded SW key in the public KEY CSRs. Each decoy word
        # differs from the KM key word at the same index. The write must return
        # OKAY (SepHmac.write_key raises otherwise).
        seed = self.random_seed()
        self.chk = SepChkLog(self, TEST, seed)
        rng = SepSeededRng(seed)
        decoy = []
        for kat_word in KAT_KEY:
            word = rng.getrandbits(32)
            while word == kat_word:
                word = rng.getrandbits(32)
            decoy.append(word)
        await self.hmac.write_key(decoy)
        self.chk.info("DECOY-KEY", key=",".join(hex(w) for w in decoy))
        # Decoy goldens under both key byte conventions: the SW-key register
        # convention (KEY_0 first, big-endian per word; hmac.hjson KEY and
        # CFG.key_swap = 0) and the sideload convention the KM key golden uses.
        golden = hmac_sha256_words(list(KAT_KEY), list(HMAC_MSG))
        decoy_goldens = {
            "sw_key": hmac_sha256_words(decoy, list(HMAC_MSG), key_word_rev=False, key_be=True),
            "sideload": hmac_sha256_words(decoy, list(HMAC_MSG)),
        }
        assert all(g != golden for g in decoy_goldens.values()), (
            "decoy golden equals the KM key golden; the decoy cannot separate the keys"
        )

        # CTRL-DECOY-LIVE: KEY_CTRL.KEY_VALID is clear before the transfer
        # (hmac_wrapper_key.rdl reset 0), so the engine keys from the KEY CSRs.
        await self.hmac.configure_keyed_256()
        live = await self.hmac.run_keyed_mac(list(HMAC_MSG))
        self.chk.ctrl(
            "DECOY-LIVE",
            live == decoy_goldens["sw_key"],
            **{"digest==decoy_sw_golden": int(live == decoy_goldens["sw_key"])},
        )

        # CHK-B: sideload the handle's key to the HMAC wrapper KEY CSRs.
        rc, _ = await self.km.key_transfer(handle=handle, dest=KM_DEST_HMAC)
        assert rc == 0, f"CMD_KEY_TRANSFER returned rc={rc} (expected 0)"
        self.logger.info("CHK-B CMD_KEY_TRANSFER PASS: rc=0 (key sideloaded to HMAC)")

        km_beats_at_xfer = self.drbg_sb.km_beats()
        staged_beats = km_beats_at_xfer - km_beats_at_load
        assert staged_beats > 0, (
            f"CHK5 FAIL: no KM entropy beats while the key was staged "
            f"(CHK5_km count {km_beats_at_load} at CMD_KEY_LOAD, "
            f"{km_beats_at_xfer} after CMD_KEY_TRANSFER)"
        )
        self.logger.info(
            "CHK5 PASS: KM drew %d real entropy beats while the key was staged "
            "(CHK5_km count %d at CMD_KEY_LOAD -> %d after CMD_KEY_TRANSFER)",
            staged_beats,
            km_beats_at_load,
            km_beats_at_xfer,
        )

        # PUB-OBSERVATION: the public KEY CSRs read zero. Both halves are asserted.
        # hmac.hjson declares them swaccess=wo, so "reads zero" holds on any RTL
        # that follows it. The positive control below makes the pair fail on a
        # dead read path, and the zero check fails if these registers leak.
        pub, ctl_pub = await self.hmac.read_public_key()
        assert ctl_pub != 0, (
            "PUB-OBSERVATION positive control failed: HMAC STATUS read back 0 over the same "
            "frontdoor, so the all-zero KEY reads prove nothing about the key"
        )
        assert all(w == 0 for w in pub), (
            "HMAC public KEY CSRs not all zero after sideload (key leak): "
            f"{[hex(w) for w in pub if w]}"
        )
        self.logger.info(
            "INFO-PUB-OBSERVATION HMAC public KEY frontdoor reads zero after sideload. "
            "Asserted, but hmac.hjson declares KEY swaccess=wo, so this read alone "
            "cannot fail. Read path alive: STATUS=%#010x",
            ctl_pub,
        )

        # The decoy goes back into the KEY CSRs with KEY_VALID set, so a transfer
        # that lands in the KEY CSR storage, or a KEY write that displaces the
        # sideloaded key, leaves the decoy keying the graded MAC.
        try:
            await self.hmac.write_key(decoy)
            rewrite_ok = True
        except AssertionError:
            rewrite_ok = False
        self.chk.ctrl(
            "DECOY-REWRITE",
            rewrite_ok,
            words=len(decoy),
            all_okay=int(rewrite_ok),
            key=",".join(hex(w) for w in decoy),
        )

        # Keyed HMAC-SHA256 with the SIDELOAD key live and the decoy in the CSRs.
        await self.hmac.configure_keyed_256()
        digest = await self.hmac.run_keyed_mac(list(HMAC_MSG))  # CHK-RW1C inside

        # CHK-DECOY: the engine did not consume the CSR decoy key.
        used = [name for name, g in decoy_goldens.items() if digest == g]
        self.chk.ok(
            "DECOY",
            not used,
            **{
                "digest!=decoy_sw_golden": int(digest != decoy_goldens["sw_key"]),
                "digest!=decoy_sideload_golden": int(digest != decoy_goldens["sideload"]),
            },
        )

        # CHK-MAC: the digest is the golden of the KM-sideloaded key.
        mac_fields = {"digest==golden": int(digest == golden)}
        if digest != golden:
            mac_fields["digest"] = ",".join(hex(w) for w in digest)
            mac_fields["golden"] = ",".join(hex(w) for w in golden)
        self.chk.ok("MAC", digest == golden, **mac_fields)
        self.logger.info("CHK-RW1C PASS: HMAC done event W1C-cleared (in run_keyed_mac)")

        # CHK-ERR: HMAC raised no error across the keyed op.
        await self.hmac.check_status_clean("EOT")

        # --- EOT: entropy health + clean shutdown ------------------------------
        await self.km.check_outbound_empty("EOT")
        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report()
        self.logger.info("CHK1..CHK5 alive + entropy alerts PASS (DRBG scoreboard)")
        self.chk.finish()
