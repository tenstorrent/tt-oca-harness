# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KM mailbox command set: generate, transfer, revoke-or-shred, illegal-to-error.

no_cpu / real fuse-sense / +km_rom_hex=rom_main.rom.parhex. RANDCFG.

The sideload KATs prove that a consumer can consume a key. None of them
exercises the interface that PRODUCES, MOVES and DESTROYS one. This leaf owns
that surface: the SEP-facing KM mailbox command set, driven frontdoor against
the real KM firmware, with the AES engine as the consume witness.

Every command is framed by ``SepKmMailbox`` with a correct header CRC-8, a
correct declared length and a correct payload CRC-32C, so a rejection is a
verdict on the command ID or its arguments, never on framing.

Checkers:
  CHK0        rom_main boots on real entropy -> RESP_KM_READY
  CHK-GEN     CMD_KEY_GENERATE returns rc=0 and a non-null handle, and its
              RETURN_ARG echoes the requested size and destination mask
  CHK-UNIQ    a second CMD_KEY_GENERATE returns a DIFFERENT handle: handles are
              allocated, never recycled under the caller
  CHK-XFER    CMD_KEY_TRANSFER of a known loaded key to AES returns rc=0 and
              the AES ciphertext equals the independent AES-256-ECB golden, so
              the transfer moved that exact key
  CHK-DEST    a transfer to an engine OUTSIDE the key's DEST_VALID is refused
  CHK-SHRED   CMD_ENGINE_SHRED returns rc=0 with its destination echoed, and
              the engine is still correctly re-keyable afterwards: a second,
              DISTINCT known key transferred after the shred encrypts to its
              own golden and NOT to the first key's
  CHK-REVOKE  CMD_KEY_REVOKE returns rc=0 with the handle echoed
  CHK-CLOSED  a transfer on the REVOKED handle is refused: revoke fails closed
  CHK-NULL    CMD_KEY_REVOKE of the reserved null handle is refused
  CHK-ILLEGAL every seeded undefined command ID returns RC_INVALID_CMD (-4)
  CHK-LEN     a defined command carrying the wrong payload length returns
              RC_INVALID_LEN (-5)
  CHK-FRAME   the three framing rejections, each with the value it carries: a
              corrupt header CRC-8 returns RC_HEADER_CRC with the CRC the KM
              computed, a wrong sequence number returns RC_CMD_NOSEQ with the
              number it expected, and a corrupt payload CRC-32C returns
              RC_PAYLOAD_CRC
  CHK-GONE    a shredded engine refuses to start: after a final
              CMD_ENGINE_SHRED the AES produces no output within a bounded
              window, so the shred reached the key rather than merely returning
              success. Run last, because an engine parked waiting for a key
              stays that way until its next valid key
  CHK-ALIVE   after every rejection CMD_STAT succeeds AND reports no latched
              recoverable error. The second half is what gives the refusal
              checkers their meaning: while a recoverable fault is pending the
              KM answers RC_FAILURE to every key command regardless of its
              arguments, which is the same code CHK-DEST and CHK-CLOSED
              expect, so without this a faulted KM would satisfy both

The mailbox is a TRANSPORT here, not the subject. Its register surface --
STATUS depth and full/overflow/underflow, IRQ_STATUS, and SEP_CTRL's response
modes and flush -- belongs to `sep_km_mailbox_protocol_rand_test`, which the
plan holds as a separate entry. Proving those means deliberately reading an
empty FIFO and overrunning a full one, which corrupts whatever frame is in
flight; it does not compose with a leaf whose subject is the command stream.

Accepted scope deltas (declared, not silent):
  * The card's DRBG-fault-during-command checker is NOT built here. The fault
    status it names is KMCSR IRQ_STATUS bit 6, which sits on the KM-internal
    bus and answers DECERR from the SEP fabric, and the reference suite
    provokes the fault with testbench knobs that have no open equivalent. At
    SEP level a DRBG fault is unrecoverable: the KM emits an unsolicited
    RESP_UNRECOVERABLE_FAULT and halts, so it also cannot be a return-code
    check. Building it would need a backdoor, which house rules reserve for
    explicit sign-off.
  * CHK-SHRED does not observe the shredded key material. The engine KEY_SHARE
    CSRs are write-only and read as zero, so the overwritten value has no
    frontdoor. The shred is proven by its return code plus the engine
    re-keying correctly to a different golden afterwards.
"""

from __future__ import annotations

import pyuvm
from env.sep_aes_golden import aes256_ecb_encrypt_words
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from seq_lib.sep_aes_seq import SepAes
from seq_lib.sep_km_mailbox_seq import (
    KM_CMD_KEY_GENERATE,
    KM_CMD_KEY_REVOKE,
    KM_CMD_STAT,
    KM_DEST_AES,
    KM_DEST_HMAC,
    KM_DEST_KMAC,
    KM_DEST_OTBN,
    KM_KEY_HANDLE_NULL,
    KM_RC_CMD_NOSEQ,
    KM_RC_FAILURE,
    KM_RC_HEADER_CRC,
    KM_RC_INVALID_ARG,
    KM_RC_INVALID_CMD,
    KM_RC_INVALID_LEN,
    KM_RC_PAYLOAD_CRC,
    KM_RC_SUCCESS,
    KM_VALID_CMD_IDS,
    SepKmMailbox,
)

# Two DISTINCT known 256-bit keys. Every word differs between them and within
# them, so a truncated, word-swapped or stale sideload changes the ciphertext.
KAT_KEY_A = (
    0xDEADBEEF,
    0x00112233,
    0x44556677,
    0x8899AABB,
    0xCCDDEEFF,
    0x01234567,
    0x89ABCDEF,
    0xFEDCBA98,
)
KAT_KEY_B = (
    0x0F1E2D3C,
    0x4B5A6978,
    0x8796A5B4,
    0xC3D2E1F0,
    0x13579BDF,
    0x2468ACE0,
    0xA5A5A5A5,
    0x5A5A5A5A,
)

AES_ECB_PT = (0x00112233, 0x44556677, 0x8899AABB, 0xCCDDEEFF)

# Sizes CMD_KEY_GENERATE may be asked for, as word counts.
GEN_KEY_WORDS = (8, 12)

# Number of undefined command IDs to walk per run.
N_ILLEGAL_IDS = 7

# Negative window for the shredded-engine probe. A healthy AES-ECB block
# asserts OUTPUT_VALID in one or two of these 20-cycle polls; the window is
# spent in full on every passing run, so keep it only a few times that latency.
_SHRED_REFUSE_POLLS = 50


class SepKmCommandSetCfg:
    """Single source of truth: the seeded command-set policy for one run."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        self.gen_words = rng.choice(GEN_KEY_WORDS)
        # The key is loaded for AES only, so any other engine is outside its
        # permitted set and is a legal target for the refusal check.
        self.bad_dest = rng.choice((KM_DEST_HMAC, KM_DEST_KMAC, KM_DEST_OTBN))
        self.illegal_ids = self._pick_illegal(rng)

    @staticmethod
    def _pick_illegal(rng) -> tuple[int, ...]:
        """Draw distinct command IDs that the KM does not define.

        The boundaries just outside each defined run are always included: those
        are where an off-by-one in the validity test shows up. The rest come
        from the seed.
        """
        # The four defined runs are 0x00-0x04, 0x10-0x12 and 0x22-0x28, so these
        # are the IDs immediately outside them -- 0x21 included, since a
        # boundary slip there would invent a command inside the key range.
        picked = [0x05, 0x0F, 0x13, 0x21, 0x29]
        while len(picked) < N_ILLEGAL_IDS:
            cand = rng.randrange(0x100)
            if cand not in KM_VALID_CMD_IDS and cand not in picked:
                picked.append(cand)
        return tuple(picked)

    def summary(self) -> str:
        return (
            f"seed={self.seed} gen_words={self.gen_words} "
            f"bad_dest=0x{self.bad_dest:02x} "
            f"illegal_ids={[hex(i) for i in self.illegal_ids]}"
        )


@pyuvm.test()
class sep_km_command_set_rand_test(sep_base_test):
    """Produce, move and destroy a key over the KM mailbox; reject the rest."""

    async def run_scenario(self) -> None:
        cfg = SepKmCommandSetCfg(self.random_seed())
        self.logger.info("km command set: %s", cfg.summary())

        # --- Boot the real KM firmware on real entropy ------------------------
        # The KM firmware reads OTP at boot, so stage a valid PROD image and
        # sense it for real. AES stays released as the consume witness; the
        # other three sideload targets are parked, so a key can only land where
        # this test says it lands.
        image = self.select_efuse_image(lc_raw=0x1)  # LC_PROD
        self.write_efuse_image(image)
        await self.bring_up_no_cpu(park=("otbn", "kmac", "hmac"))

        self.km = SepKmMailbox(self)
        self.aes = SepAes(self)

        await self.bring_up_entropy(strict=True, score_km="observe", score_sinks={"aes": "observe"})
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.start_fifo_drain()

        await self.swrst.release("km")
        await self.km.wait_km_ready()
        self.logger.info("CHK0 PASS: rom_main booted, RESP_KM_READY over the mailbox")

        # --- CHK-GEN: the KM produces a key ----------------------------------
        # req_size is the word count minus one, per the command's argument
        # encoding; RETURN_ARG packs handle[7:0], req_size[14:8], dest[23:16].
        req_size = cfg.gen_words - 1
        gen_seq = await self.km.send_command(KM_CMD_KEY_GENERATE, [req_size, KM_DEST_AES])
        rc, arg = await self.km.recv_resp_cmd(KM_CMD_KEY_GENERATE, gen_seq)
        assert rc == KM_RC_SUCCESS, f"CHK-GEN FAIL: CMD_KEY_GENERATE rc={rc}"
        gen_handle = arg & 0xFF
        assert gen_handle != KM_KEY_HANDLE_NULL, (
            f"CHK-GEN FAIL: CMD_KEY_GENERATE returned the reserved null handle (arg=0x{arg:08x})"
        )
        echo_size = (arg >> 8) & 0x7F
        echo_dest = (arg >> 16) & 0xFF
        assert echo_size == req_size, (
            f"CHK-GEN FAIL: RETURN_ARG echoed size {echo_size}, requested {req_size} "
            f"(arg=0x{arg:08x})"
        )
        assert echo_dest == KM_DEST_AES, (
            f"CHK-GEN FAIL: RETURN_ARG echoed dest 0x{echo_dest:02x}, requested "
            f"0x{KM_DEST_AES:02x} (arg=0x{arg:08x})"
        )
        await self.km.check_outbound_empty("POST-KEY-GENERATE")
        self.logger.info(
            "CHK-GEN PASS: handle=0x%02x, RETURN_ARG echoes size=%d dest=0x%02x",
            gen_handle,
            echo_size,
            echo_dest,
        )

        # --- CHK-UNIQ: handles are allocated, not recycled --------------------
        gen2_seq = await self.km.send_command(KM_CMD_KEY_GENERATE, [req_size, KM_DEST_AES])
        rc, arg2 = await self.km.recv_resp_cmd(KM_CMD_KEY_GENERATE, gen2_seq)
        assert rc == KM_RC_SUCCESS, f"CHK-UNIQ FAIL: second CMD_KEY_GENERATE rc={rc}"
        gen_handle2 = arg2 & 0xFF
        assert gen_handle2 not in (KM_KEY_HANDLE_NULL, gen_handle), (
            f"CHK-UNIQ FAIL: second generate returned handle 0x{gen_handle2:02x}, "
            f"first returned 0x{gen_handle:02x}"
        )
        await self.km.check_outbound_empty("POST-KEY-GENERATE-2")
        self.logger.info(
            "CHK-UNIQ PASS: distinct handles 0x%02x and 0x%02x", gen_handle, gen_handle2
        )

        # --- CHK-XFER: the KM moves a KNOWN key, and AES consumes it ----------
        golden_a = aes256_ecb_encrypt_words(list(KAT_KEY_A), list(AES_ECB_PT))
        golden_b = aes256_ecb_encrypt_words(list(KAT_KEY_B), list(AES_ECB_PT))
        assert golden_a != golden_b, (
            "test construction error: the two KAT keys encrypt the plaintext identically"
        )

        handle_a = await self.km.key_load(key_words=list(KAT_KEY_A), dest=KM_DEST_AES)
        rc, arg = await self.km.key_transfer(handle=handle_a, dest=KM_DEST_AES)
        assert rc == KM_RC_SUCCESS, f"CHK-XFER FAIL: CMD_KEY_TRANSFER rc={rc}"
        assert (arg & 0xFF) == handle_a and ((arg >> 8) & 0xFF) == KM_DEST_AES, (
            f"CHK-XFER FAIL: RETURN_ARG 0x{arg:08x} does not echo handle 0x{handle_a:02x} "
            f"and dest 0x{KM_DEST_AES:02x}"
        )
        await self.aes.configure_ecb_enc_256(sideload=True)
        await self.aes.trigger_prng_reseed()
        ct_a = await self.aes.run_ecb_block(list(AES_ECB_PT))
        assert ct_a == golden_a, (
            "CHK-XFER FAIL: AES did not consume the transferred key:\n"
            f"  ct     ={[hex(w) for w in ct_a]}\n"
            f"  golden ={[hex(w) for w in golden_a]}"
        )
        self.logger.info("CHK-XFER PASS: rc=0 and ct == AES(KAT_KEY_A, PT) golden")

        # --- CHK-DEST: the permitted destination set is enforced --------------
        # The destination is a legal engine bit, so the command passes argument
        # validation and is refused by the transfer itself: RC_FAILURE, not
        # RC_INVALID_ARG. Asserting the exact code keeps a refusal for the wrong
        # reason -- a malformed argument, say -- from reading as a pass.
        rc, _ = await self.km.key_transfer(handle=handle_a, dest=cfg.bad_dest)
        assert rc == KM_RC_FAILURE, (
            f"CHK-DEST FAIL: transfer to 0x{cfg.bad_dest:02x} returned rc={rc}, expected "
            f"{KM_RC_FAILURE} (RC_FAILURE) -- the key was loaded for "
            f"0x{KM_DEST_AES:02x} only"
        )
        self.logger.info(
            "CHK-DEST PASS: transfer to 0x%02x refused with RC_FAILURE -- outside DEST_VALID",
            cfg.bad_dest,
        )
        await self._check_alive("post-dest-refusal")

        # --- CHK-SHRED: destroy the engine's key, then re-key it --------------
        rc, arg = await self.km.engine_shred(dest=KM_DEST_AES)
        assert rc == KM_RC_SUCCESS, f"CHK-SHRED FAIL: CMD_ENGINE_SHRED rc={rc}"
        assert (arg & 0xFF) == KM_DEST_AES, (
            f"CHK-SHRED FAIL: RETURN_ARG echoed dest 0x{arg & 0xFF:02x}, requested "
            f"0x{KM_DEST_AES:02x}"
        )
        handle_b = await self.km.key_load(key_words=list(KAT_KEY_B), dest=KM_DEST_AES)
        rc, _ = await self.km.key_transfer(handle=handle_b, dest=KM_DEST_AES)
        assert rc == KM_RC_SUCCESS, f"CHK-SHRED FAIL: post-shred CMD_KEY_TRANSFER rc={rc}"
        await self.aes.configure_ecb_enc_256(sideload=True)
        await self.aes.trigger_prng_reseed()
        ct_b = await self.aes.run_ecb_block(list(AES_ECB_PT))
        assert ct_b == golden_b, (
            "CHK-SHRED FAIL: the re-keyed engine did not consume the second key:\n"
            f"  ct     ={[hex(w) for w in ct_b]}\n"
            f"  golden ={[hex(w) for w in golden_b]}"
        )
        assert ct_b != ct_a, (
            "CHK-SHRED FAIL: the engine produced the FIRST key's ciphertext after a "
            "shred and a transfer of a different key -- the old key was still in use"
        )
        self.logger.info(
            "CHK-SHRED PASS: rc=0 with dest echoed; engine re-keys to KAT_KEY_B's "
            "golden and no longer produces KAT_KEY_A's ciphertext"
        )

        # --- CHK-REVOKE / CHK-CLOSED: destroy a key, then fail closed ---------
        rc, arg = await self.km.key_revoke(handle=gen_handle)
        assert rc == KM_RC_SUCCESS, f"CHK-REVOKE FAIL: CMD_KEY_REVOKE rc={rc}"
        assert (arg & 0xFF) == gen_handle, (
            f"CHK-REVOKE FAIL: RETURN_ARG echoed handle 0x{arg & 0xFF:02x}, revoked "
            f"0x{gen_handle:02x}"
        )
        self.logger.info("CHK-REVOKE PASS: rc=0 with handle 0x%02x echoed", gen_handle)

        # The handle is still a legal value, so this too is refused by the
        # registry lookup rather than by argument validation.
        rc, _ = await self.km.key_transfer(handle=gen_handle, dest=KM_DEST_AES)
        assert rc == KM_RC_FAILURE, (
            f"CHK-CLOSED FAIL: CMD_KEY_TRANSFER on revoked handle 0x{gen_handle:02x} "
            f"returned rc={rc}, expected {KM_RC_FAILURE} (RC_FAILURE) -- revoke did "
            "not fail closed"
        )
        self.logger.info("CHK-CLOSED PASS: transfer on the revoked handle refused with RC_FAILURE")
        await self._check_alive("post-revoked-transfer")

        # --- CHK-NULL: the reserved handle is never a target ------------------
        # The null handle is rejected by argument validation, before any
        # registry work, so this one is RC_INVALID_ARG.
        rc, _ = await self.km.key_revoke(handle=KM_KEY_HANDLE_NULL)
        assert rc == KM_RC_INVALID_ARG, (
            f"CHK-NULL FAIL: CMD_KEY_REVOKE of the null handle returned rc={rc}, "
            f"expected {KM_RC_INVALID_ARG} (RC_INVALID_ARG)"
        )
        self.logger.info("CHK-NULL PASS: revoke of the null handle refused with RC_INVALID_ARG")
        await self._check_alive("post-null-revoke")

        # --- CHK-ILLEGAL: undefined command IDs -------------------------------
        for cmd_id in cfg.illegal_ids:
            rc, _ = await self.km.send_raw_expect_rc(cmd_id, [])
            assert rc == KM_RC_INVALID_CMD, (
                f"CHK-ILLEGAL FAIL: undefined command 0x{cmd_id:02x} returned rc={rc}, "
                f"expected {KM_RC_INVALID_CMD} (RC_INVALID_CMD)"
            )
            await self._check_alive(f"post-illegal-0x{cmd_id:02x}")
        self.logger.info(
            "CHK-ILLEGAL PASS: %d undefined command IDs each returned RC_INVALID_CMD "
            "and left the KM answering CMD_STAT: %s",
            len(cfg.illegal_ids),
            [hex(i) for i in cfg.illegal_ids],
        )

        # --- CHK-LEN: a defined command with the wrong payload length ---------
        # CMD_KEY_REVOKE takes exactly one payload word; two must be refused on
        # the length, not silently accepted with the surplus ignored.
        rc, _ = await self.km.send_raw_expect_rc(KM_CMD_KEY_REVOKE, [gen_handle2, 0])
        assert rc == KM_RC_INVALID_LEN, (
            f"CHK-LEN FAIL: CMD_KEY_REVOKE with a 2-word payload returned rc={rc}, "
            f"expected {KM_RC_INVALID_LEN} (RC_INVALID_LEN)"
        )
        self.logger.info("CHK-LEN PASS: over-long CMD_KEY_REVOKE payload returned RC_INVALID_LEN")
        await self._check_alive("post-bad-length")

        # --- CHK-FRAME: the three framing rejections --------------------------
        # These are the only return codes the KM produces before it looks at the
        # command at all, and each carries a value worth checking: the CRC the KM
        # itself computed, or the sequence number it was expecting. The seq
        # counter side effects differ between them and are handled in the driver.
        rc, arg = await self.km.send_bad_header_crc(KM_CMD_STAT)
        assert rc == KM_RC_HEADER_CRC, (
            f"CHK-FRAME FAIL: a corrupt header CRC-8 returned rc={rc}, expected "
            f"{KM_RC_HEADER_CRC} (RC_HEADER_CRC)"
        )
        self.logger.info(
            "CHK-FRAME PASS: corrupt header CRC-8 refused RC_HEADER_CRC, KM computed 0x%02x",
            arg & 0xFF,
        )
        await self._check_alive("post-bad-header-crc")

        expected_seq = self.km.seq_num
        rc, arg = await self.km.send_bad_seq(KM_CMD_STAT)
        assert rc == KM_RC_CMD_NOSEQ, (
            f"CHK-FRAME FAIL: a wrong sequence number returned rc={rc}, expected "
            f"{KM_RC_CMD_NOSEQ} (RC_CMD_NOSEQ)"
        )
        assert (arg & 0xFF) == expected_seq, (
            f"CHK-FRAME FAIL: RC_CMD_NOSEQ reported expected sequence 0x{arg & 0xFF:02x}, "
            f"but the host is at 0x{expected_seq:02x} -- the two counters disagree"
        )
        self.logger.info(
            "CHK-FRAME PASS: wrong sequence number refused RC_CMD_NOSEQ, KM expecting %d",
            arg & 0xFF,
        )
        await self._check_alive("post-bad-seq")

        rc, _ = await self.km.send_bad_payload_crc(KM_CMD_KEY_REVOKE, [gen_handle2])
        assert rc == KM_RC_PAYLOAD_CRC, (
            f"CHK-FRAME FAIL: a corrupt payload CRC-32C returned rc={rc}, expected "
            f"{KM_RC_PAYLOAD_CRC} (RC_PAYLOAD_CRC)"
        )
        self.logger.info("CHK-FRAME PASS: corrupt payload CRC-32C refused RC_PAYLOAD_CRC")
        await self._check_alive("post-bad-payload-crc")

        # --- CHK-GONE: a shredded engine will not run -------------------------
        # Deliberately last. The engine is left with no valid key, so it parks
        # waiting for one; nothing after this point may need it. This is the
        # direct observation of the shred: the engine key registers are
        # write-only, so refusal to start is the only frontdoor evidence that
        # the shred reached the key rather than just returning success.
        rc, _ = await self.km.engine_shred(dest=KM_DEST_AES)
        assert rc == KM_RC_SUCCESS, f"CHK-GONE FAIL: final CMD_ENGINE_SHRED rc={rc}"
        await self.aes.configure_ecb_enc_256(sideload=True)
        await self.aes.start_block_no_wait(list(AES_ECB_PT))
        assert not await self.aes.output_valid_within(_SHRED_REFUSE_POLLS), (
            "CHK-GONE FAIL: the AES produced a result with sideload selected after its "
            "key was shredded -- the shred did not reach the key"
        )
        self.logger.info(
            "CHK-GONE PASS: the shredded engine produced no output in %d polls (fail-closed START)",
            _SHRED_REFUSE_POLLS,
        )

        # --- EOT --------------------------------------------------------------
        await self.km.check_outbound_empty("EOT")
        await self.aes.check_status_clean("EOT")
        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report()
        self.logger.info("entropy alerts clear and DRBG scoreboard reports PASS")

    async def _check_alive(self, tag: str) -> None:
        """CHK-ALIVE: the KM is still in its loop and has not latched a fault.

        Both halves matter. While a recoverable fault is pending the KM rejects
        every key command with RC_FAILURE before it ever looks at the
        arguments -- the same code CHK-DEST and CHK-CLOSED assert -- so a
        refusal checker that ran against a faulted KM would pass without the
        policy it names being exercised at all. CMD_STAT stays on the
        allowlist through a fault, so its return code alone cannot see this;
        its return argument carries the recoverable-error bit that can.
        """
        rc, arg = await self.km.stat()
        assert rc == KM_RC_SUCCESS, (
            f"CHK-ALIVE FAIL [{tag}]: CMD_STAT returned rc={rc} after a rejected "
            "command -- the KM did not stay in its command loop"
        )
        assert (arg & 0x1) == 0, (
            f"CHK-ALIVE FAIL [{tag}]: CMD_STAT reports a latched recoverable error "
            f"(arg=0x{arg:08x}). Every key command is refused RC_FAILURE in that "
            "state, so the refusal checkers around here prove nothing"
        )
        self.logger.info("CHK-ALIVE PASS [%s]: CMD_STAT rc=0 and no latched recoverable error", tag)
