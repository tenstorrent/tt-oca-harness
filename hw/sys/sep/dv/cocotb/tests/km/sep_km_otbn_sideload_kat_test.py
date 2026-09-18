# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KM -> OTBN sideload consume-proof KAT (reference suite, sep_km_otbn_sideload_kat_test).

Real DRBG entropy boots the real KM firmware (rom_main). The host (CPU-LSU
frontdoor AXI) provisions a KNOWN 384-bit key into a KPV handle via CMD_KEY_LOAD,
then CMD_KEY_TRANSFER sideloads it to the OpenTitan OTBN core. A key-dump OTBN
program reads the sideload KEY WSRs, reconstructs key = share0 ^ share1, and
writes the 384-bit result to DMEM. The host asserts DMEM == the exact known key.

This is a fully FRONTDOOR consume-proof: because the host loaded the key value
itself, the expected value is known without reading the wrapper shares (which are
write-only / on the KM-private bus). The reference suite generates a random key
and reconstructs it by a read-only backdoor of the wrapper shares. Here the 12
distinct key words make an exact compare catch any truncation, word-swap, or
share-defeat bug.

VPLAN-parity checkers (mapped to the reference suite's checker list):
  CHK0       boot KM on real DRBG -> RESP_KM_READY
  CHK-A      CMD_KEY_LOAD known key (frontdoor; wrapper shares are write-only)
  CHK-B      CMD_KEY_TRANSFER rc=0 to OTBN
  CHK-C      OTBN EXECUTE -> IDLE, ERR_BITS == 0
  CHK-D/E    DMEM == exact known key; result_hi pad == 0
  CHK-F      mask non-degeneracy: OTBN dumps its own KEY_S0/S1 WSRs (raw shares) to
             DMEM; host asserts share0/share1 are non-trivial, differ, neither equals
             the key, and share0^share1 == K -- 2-share masking proven NOT defeated,
             frontdoor
  CHK1..CHK4 strict golden proof via the DRBG scoreboard;
             CHK5 is alive/observed (not bit-exact, since the pull order is firmware/
             secure-wipe-driven, not golden-predictable). Two real EDN consumers are
             witnessed off one DRBG:
  CHK5_km        post-mux KM tvalid&&tready beats (mux0 -> Key Manager); score_km="observe"
  CHK5_otbn_urnd post-adapter OTBN-URND edn_req&&edn_ack beats (mux1 ->
                 drbg_axis_edn_adapter -> crypto_edn[3]); OTBN's post-op secure wipe
                 refreshes URND from the crypto EDN leg; score_sinks={"otbn_urnd":"observe"}.
                 Proves the crypto leg delivers real entropy, not only the KM leg.
Key-bus isolation (other sideload targets idle) is covered by construction: the transfer
dest mask is OTBN-only and AES/KMAC/HMAC are held parked in SW reset, so they cannot
receive the key; CHK-D (exact distinct key) further proves OTBN consumed the correct
sideloaded key, not stale/zero/another engine's. There is no RW1C done-status bit on
this consume path (OTBN completion is the STATUS->IDLE state + ERR_BITS==0).

Boot recipe (must match the reference subsystem tb to clear the SRAM scrambler cold-boot
without a parity fault): rom_main built with PROD_BOOT_WIPE=0 / PROD_UNREC_WIPE=0,
and the KM SRAM macro is backdoor-filled to zero+valid-parity by tb_backdoor_mem
(tb/tb_top.sv). Real fuse-sense (no +skip_fuse_sense): the KM
firmware reads OTP/lifecycle at boot, so a valid PROD-lifecycle image is staged.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_km_mailbox_seq import KM_DEST_OTBN, SepKmMailbox
from seq_lib.sep_otbn_seq import SepOtbn
from seq_lib.sep_sw_reset_seq import SW_RESET_N_BIT

# Known 384-bit KAT key: 12 DISTINCT 32-bit words so an exact DMEM compare catches
# a truncated / word-swapped / share-defeated sideload (a single repeated word
# would let such bugs pass silently).
KAT_KEY = (
    0xDEADBEEF,
    0x00112233,
    0x44556677,
    0x8899AABB,
    0xCCDDEEFF,
    0x01234567,
    0x89ABCDEF,
    0xFEDCBA98,
    0x13579BDF,
    0x2468ACE0,
    0x0F1E2D3C,
    0x4B5A6978,
)


@pyuvm.test()
class sep_km_otbn_sideload_kat_test(sep_base_test):
    """KM->OTBN sideload consume-proof (frontdoor, real rom_main, known key)."""

    async def run_scenario(self) -> None:
        # --- Boot the real KM firmware on real entropy -------------------------
        # Real fuse-sense with a valid PROD-lifecycle image (the KM firmware reads
        # OTP at boot); stage it before bring-up so sense populates the shadow.
        image = self.select_efuse_image(lc_raw=0x1)  # LC_PROD
        self.write_efuse_image(image)
        await self.bring_up_no_cpu(park=("otbn", "aes", "hmac", "kmac", "abr"))

        self.km = SepKmMailbox(self)
        self.otbn = SepOtbn(self)

        # AES/KMAC/OTBN JTAG-held across rst_ni release, then parked in SW_RESET_N so they never sit as ungranted
        # crypto-EDN requesters through fuse sense. HMAC is parked too for
        # key-bus isolation. KM owns CSRNG/EDN once entropy is up; OTBN is
        # released later for the transfer.

        # Shared entropy bring-up with the STRICT golden scoreboard so this test
        # proves CHK1..CHK4 itself (decorrelator/compressor/seed/genbits), not just
        # "entropy alive". score_km="observe": CHK5_km golden-match needs a
        # predictable KM consumption sequence, which real rom_main does not provide;
        # this mode still requires real post-mux KM tvalid&&tready beats. Fork the
        # concurrent FIFO_RDATA drain so CHK2 is scored without ESRC FIFO overflow.
        # OTBN is released later (release("otbn")) and runs the key-dump; its post-op
        # secure wipe refreshes URND from the crypto EDN leg (entropy_muxed_req[1] ->
        # drbg_axis_edn_adapter -> crypto_edn[3]=OTBN-URND). Score that sink in observe
        # mode so this KAT also proves the crypto EDN leg delivers real beats, not only
        # the KM leg. observe = positive beat evidence, no bit-exact compare (secure-
        # wipe-driven pull order). Only OTBN-URND is scored: the key-dump program issues
        # no BN.WSRR(RND), so crypto_edn[2] (OTBN-RND) never fires here.
        # AES/KMAC stay disabled (parked, no entropy requests).
        await self.bring_up_entropy(
            strict=True, score_km="observe", score_sinks={"otbn_urnd": "observe"}
        )
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.start_fifo_drain()
        self.logger.info("real entropy flowing; releasing KM firmware (rom_main)")

        # Release the KM PicoRV32; it boots rom_main (DRBG seed, SRAM/KPV scrambler
        # init + lock, mailbox flush) and announces RESP_KM_READY on the mailbox.
        await self.swrst.release("km")
        await self.km.wait_km_ready()
        self.logger.info("CHK0 KM firmware boot PASS: RESP_KM_READY over the mailbox")

        # --- Frontdoor consume-proof: load known key -> transfer -> dump -------
        # CHK-A: provision the KNOWN key into a KPV handle over the frontdoor.
        handle = await self.km.key_load(key_words=list(KAT_KEY), dest=KM_DEST_OTBN)
        self.logger.info("CHK-A CMD_KEY_LOAD PASS: known key staged, handle=0x%02x", handle)

        # Release OTBN from SW reset BEFORE the transfer: CMD_KEY_TRANSFER has the
        # KM CPU write the OTBN wrapper KEY_SHARE registers, and the wrapper (incl.
        # its key CSR block) is in the otbn sw-reset domain (sep.sv otbn_sw_rst_ni).
        # If OTBN stays parked the KM's wrapper write never completes and the KM
        # hangs with no mailbox response. OTBN is held parked through KM boot/load
        # so KM owns the entropy stream, then released here to receive the key and
        # run the key-dump (mirrors the reference suite's "release the target engine when ready to
        # receive the key + run the consume op"). Wait for OTBN's post-reset secure
        # wipe to finish (STATUS IDLE) BEFORE transferring, else the wipe can clobber
        # the just-sideloaded key.
        await self.swrst.release("otbn")
        await self.otbn.wait_idle("post-reset")

        # CHK-ISO: key-bus isolation, positive evidence (not just by-construction).
        # Read back SW_RESET_N and prove the other sideload engines (AES/KMAC/HMAC)
        # are HELD in reset -- they physically cannot receive the key -- while OTBN
        # is released. Combined with the OTBN-only transfer dest mask and CHK-D
        # (OTBN got the exact key), this is the OSS analog of the reference suite's bus-target check.
        rst = await self.swrst.read_back()
        parked = (
            (1 << SW_RESET_N_BIT["aes"])
            | (1 << SW_RESET_N_BIT["hmac"])
            | (1 << SW_RESET_N_BIT["kmac"])
            | (1 << SW_RESET_N_BIT["abr"])
        )
        assert (rst & parked) == 0, (
            f"key-bus isolation: AES/KMAC/HMAC/ABR not parked before transfer "
            f"(SW_RESET_N=0x{rst:08x})"
        )
        assert rst & (1 << SW_RESET_N_BIT["otbn"]), (
            f"OTBN not released before transfer (SW_RESET_N=0x{rst:08x})"
        )
        self.logger.info(
            "CHK-ISO key-bus isolation PASS: only KM+OTBN released, "
            "AES/KMAC/HMAC/ABR parked (SW_RESET_N=0x%02x)",
            rst,
        )

        # CHK-B: sideload the handle's key to the OTBN wrapper.
        rc, _ = await self.km.key_transfer(handle=handle, dest=KM_DEST_OTBN)
        assert rc == 0, f"CMD_KEY_TRANSFER returned rc={rc} (expected 0)"
        self.logger.info("CHK-B CMD_KEY_TRANSFER PASS: rc=0 (key sideloaded to OTBN)")

        # CHK-C: OTBN runs the key-dump program cleanly (IDLE, no error bits).
        await self.otbn.load_program()
        await self.otbn.execute()  # wait_idle: fails on LOCKED or timeout
        errbits = await self.otbn.read_errbits()
        assert errbits == 0, f"OTBN ERR_BITS=0x{errbits:08x} after key-dump (expected 0)"
        self.logger.info("CHK-C OTBN execute PASS: reached IDLE, ERR_BITS=0")

        # Read all key-dump outputs once via the seq's named DMEM offsets (the test
        # stays scenario-level; no raw addresses).
        key, s0, s1, key_pad = await self.otbn.read_keydump_outputs()
        kat = list(KAT_KEY)

        # CHK-D/E: DMEM key == the exact known key; high-WDR padding == 0.
        assert key == kat, (
            "OTBN sideload key mismatch:\n"
            f"  got      = {[hex(w) for w in key]}\n"
            f"  expected = {[hex(w) for w in kat]}"
        )
        assert all(w == 0 for w in key_pad), (
            f"OTBN result_hi padding words [4..7] not zero: {[hex(w) for w in key_pad]}"
        )
        self.logger.info("CHK-D/E KM->OTBN sideload KAT PASS: DMEM == known 384b key, padding=0")

        # CHK-F: 2-share masking non-degeneracy (frontdoor). The keydump
        # also wrote OTBN's raw KEY_S0/S1 WSRs (the shares) to DMEM. Prove the
        # masking is real and not defeated: shares non-trivial, distinct, neither
        # equals the key, and share0 ^ share1 reconstructs the known key.
        assert [a ^ b for a, b in zip(s0, s1)] == kat, (
            "share0 ^ share1 != known key:\n"
            f"  s0^s1 = {[hex(a ^ b) for a, b in zip(s0, s1)]}\n"
            f"  key   = {[hex(w) for w in kat]}"
        )
        assert any(w != 0 for w in s0) and any(w != 0 for w in s1), (
            f"degenerate share (all-zero): s0={[hex(w) for w in s0]} s1={[hex(w) for w in s1]}"
        )
        assert s0 != kat and s1 != kat, "a share equals the raw key -> 2-share masking defeated"
        assert s0 != s1, "shares identical -> masking defeated"
        assert len(set(s0)) > 1, f"SHARE0 (mask) degenerate (constant): {[hex(w) for w in s0]}"
        self.logger.info(
            "CHK-F mask non-degeneracy PASS: shares non-trivial/distinct, neither==key, "
            "share0^share1==K"
        )

        # CHK1..CHK4 + entropy health: the whole flow ran on real DRBG entropy.
        # Stop the FIFO drain, then the strict scoreboard's report() raises on any
        # golden mismatch or under-evidence stream (CHK1..CHK4 bit-exact; CHK5_km
        # observed alive per score_km="observe" above). Also assert the CSRNG/EDN
        # error + recoverable-alert regs stayed zero across the run.
        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report()
        self.logger.info("CHK1..CHK5 alive + entropy alerts PASS (DRBG scoreboard)")
