# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AES encrypts with exactly the key the KM sideloads, matching an independent AES-256 golden.

Real DRBG entropy boots the real KM firmware (rom_main). The host (CPU-LSU
frontdoor AXI) provisions a KNOWN 256-bit key into a KPV handle via CMD_KEY_LOAD,
then CMD_KEY_TRANSFER sideloads it to the OpenTitan AES core. The host then runs
ECB-256 encryptions and proves the AES engine CONSUMED exactly that key:

  ct_side  = AES-ECB(sideload key, PT)   (CTRL_SHADOWED.SIDELOAD=1)
  ct_swref = AES-ECB(drawn software key via SW KEY_SHARE, PT)   (CTRL_SHADOWED.SIDELOAD=0,
             the sideload key still valid)
  ct_dummy = AES-ECB(unrelated dummy SW key, PT)   (negative reference)

AES KEY CSRs are write-only and AES is not programmable, so (unlike
km/sep_km_otbn_sideload_kat_test) the delivered key cannot be dumped back; the
consume-proof is the encryption cross-check. ct_side / ct_swref are
value-checked against an independent AES-256-ECB golden (env/sep_aes_golden.py,
self-tested against FIPS-197 C.3) of the known key, so a truncated, word-swapped
or share-defeated sideload fails.

Checkers:
  CHK0     boot KM on real DRBG -> RESP_KM_READY
  CHK-A    CMD_KEY_LOAD known key
  CHK-NEG  ct_dummy == AES(dummy, PT): negative reference is a real encryption
  CHK-B    CMD_KEY_TRANSFER rc=0 to AES
  CHK-ISO  SW_RESET_N read-back: only the AES bit released; OTBN/KMAC/HMAC
           parked (register state only, as in km/sep_km_otbn_sideload_kat_test)
  PUB-OBSERVATION  AES public KEY_SHARE0/1 read zero after sideload while STATUS
           reads non-zero on the same path; swaccess=wo makes the zero read alone
           unfalsifiable
  CHK-F    ct_side == AES(known_key, PT) golden: sideload delivered the exact key
  CHK-RT   DEC(ct_side) with the SIDELOAD key == original PT: the sideloaded key
           drives a full ECB-256 ENC/DEC round-trip, not just encryption
  INFO-AES-SRAM-KM-PLAN  drawn block count n (2..8), window and region bases
           in SEP SRAM, and the stream salt
  CTRL-AES-SRAM-PRE  readback of every pre-filled 64-bit SRAM word (source
           plaintext, encrypt and decrypt destination fill, guards) equals the
           written value; each value differs from 0 and from the golden of its slot
  CHK-AES-SRAM-KM  the bench master on the CPU load/store port moves n blocks
           from a source SEP SRAM region through AES (SIDELOAD=1, KM key, no
           software key written) to an encrypt destination, then decrypts that
           region to a decrypt destination. op=enc: the encrypt destination
           reads back AES-256-ECB(known_key, plaintext) (FIPS-197 golden).
           op=dec: the decrypt destination reads back the plaintext. The
           software key registers hold the dummy key, so a wrong key select
           fails op=enc
  CTRL-AES-SRAM-REGIONS  after both legs, the source region and the six 64-bit
           guard words read back unchanged (part=src, part=guard). The bench
           master is the only agent that writes SEP SRAM in this leaf, so these
           lines prove the bench addressing, not a DUT behavior
  OBS-AES-SRAM-KM-LAT  per leg, min/max/first clk_i cycles from the DATA_IN_3
           write response to the STATUS read that shows OUTPUT_VALID (includes
           the STATUS read latency). Logged, not graded: the OUTPUT_VALID wait
           has only a liveness timeout, the AES driver default poll bound
  CHK-H    with SIDELOAD=0 while the sideload key is still valid, ct_swref ==
           AES(sw_key, PT) golden, where sw_key is drawn per seed and differs from
           KAT_KEY and from the dummy key in every word: the engine takes the
           software key and not the sideloaded one (aes.hjson:764 SIDELOAD,
           hw/sys/sep/doc/aes.adoc:54-55)
  CHK1..CHK4 strict golden proof via the DRBG scoreboard; CHK5_km alive/observed
           (rom_main pull order not golden-predictable) + CHK5_aes alive/observed:
           the released AES masking PRNG reseeds from the crypto EDN leg, so a
           second real EDN consumer (besides KM) is witnessed off one DRBG.

Limitations:
  * SHARE0 mask non-degeneracy inside the AES wrapper is not observable
    frontdoor: the combined key can be correct (CHK-F) while the 2-share masking
    is degenerate.
  * Key-bus isolation is proven by SW_RESET_N read-back, not by monitoring the
    key bus; CHK-F additionally proves AES got the correct key.

Boot recipe matches km/sep_km_otbn_sideload_kat_test (real fuse-sense, valid PROD
OTP image; KM SRAM responder powers up zero+valid-parity; rom_main built with
KM_BOOT_WIPE=0).

AES stays released through entropy bring-up so its masking-PRNG reseed is served
as EDN starts; OTBN/KMAC/HMAC are parked so the KM owns the boot/seed stream and
they cannot take the key.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from env.sep_aes_golden import aes256_ecb_encrypt_words, aes_encrypt_words
from env.sep_axi_agent import SepAxiOp
from env.sep_chk_log import word_digest
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import sym
from seq_lib.sep_aes_seq import AES_STATUS_OUTPUT_VALID, SepAes
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_km_mailbox_seq import KM_DEST_AES, SepKmMailbox
from seq_lib.sep_sw_reset_seq import SW_RESET_N_BIT

# Known 256-bit KAT key: 8 DISTINCT 32-bit words so the golden compare and the
# negative reference catch a truncated / word-swapped / share-defeated sideload.
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

# Fixed ECB plaintext block (ECB keeps the focus on the key-source path, no IV).
AES_ECB_PT = (0x00112233, 0x44556677, 0x8899AABB, 0xCCDDEEFF)

# Dummy SW key for the negative reference (unrelated to KAT_KEY).
AES_DUMMY_SW_KEY = (
    0xDEADBEEF,
    0xCAFEF00D,
    0x12345678,
    0x9ABCDEF0,
    0x0F0E0D0C,
    0x0B0A0908,
    0x07060504,
    0x03020100,
)

SEP_SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
SEP_SRAM_SIZE = sym("SEP_SRAM_MEM_SIZE")

# Domain tag of the SRAM-leg draw stream. It differs from the AES driver's
# key-share stream tag, so the leg's draws do not move the key shares.
SRAM_LEG_SALT = 0x5A3C
# Domain tag of the CHK-H software-key draw stream; it differs from the two
# tags above, so the draw moves neither the key shares nor the SRAM leg.
SW_KEY_SALT = 0x5357

# Liveness timeout of one OUTPUT_VALID wait: the AES driver's default poll
# bound (polls x cycles per poll). It is a hang guard, not a graded latency.
_POLL_DEFAULTS = inspect.signature(SepAes._poll_status_bit).parameters
OUTPUT_VALID_LIVENESS_CYCLES = (
    _POLL_DEFAULTS["timeout"].default * _POLL_DEFAULTS["poll_cycles"].default
)

_WORD64 = 8
_BLOCK_BYTES = 16


def _pack64(words: list[int]) -> list[int]:
    """AES register words 2k (low half) and 2k+1 (high half) as 64-bit word k."""
    return [
        (words[i] & 0xFFFF_FFFF) | ((words[i + 1] & 0xFFFF_FFFF) << 32)
        for i in range(0, len(words), 2)
    ]


def _unpack64(dwords: list[int]) -> list[int]:
    """Inverse of ``_pack64``."""
    out: list[int] = []
    for d in dwords:
        out += [d & 0xFFFF_FFFF, (d >> 32) & 0xFFFF_FFFF]
    return out


def _hex64(dwords: list[int]) -> str:
    return "[" + ",".join(f"{d:016x}" for d in dwords) + "]"


def _draw_sw_key(seed: int) -> list[int]:
    """The CHK-H software key: 8 words, word i not 0 and not word i of KAT_KEY or the dummy key."""
    rng = SepSeededRng(seed ^ SW_KEY_SALT)
    key: list[int] = []
    for kat, dummy in zip(KAT_KEY, AES_DUMMY_SW_KEY):
        while True:
            w = rng.getrandbits(32)
            if w not in (0, kat, dummy):
                key.append(w)
                break
    return key


def _draw64(rng: SepSeededRng, avoid: set[int]) -> int:
    """A 64-bit word that is not 0 and not in ``avoid``."""
    while True:
        value = rng.getrandbits(64)
        if value != 0 and value not in avoid:
            return value


@dataclass
class _SramAesPlan:
    """SEP SRAM window ``[G][SRC][G][G][ENC][G][G][DEC][G]`` of 64-bit words.

    Each region holds ``n`` 16-byte blocks. Each guard G is one 64-bit word.
    """

    n: int
    base: int
    pt: list[int]  # 64-bit plaintext words of SRC
    enc_golden: list[int]  # 64-bit words of AES-256-ECB(KAT_KEY, pt)
    enc_fill: list[int]
    dec_fill: list[int]
    guard_vals: list[int]  # six guard words in window order

    @staticmethod
    def window_bytes(n: int) -> int:
        return 3 * n * _BLOCK_BYTES + 6 * _WORD64

    @property
    def region_bytes(self) -> int:
        return self.n * _BLOCK_BYTES

    @property
    def src(self) -> int:
        return self.base + _WORD64

    @property
    def enc(self) -> int:
        return self.src + self.region_bytes + 2 * _WORD64

    @property
    def dec(self) -> int:
        return self.enc + self.region_bytes + 2 * _WORD64

    @property
    def guard_addrs(self) -> list[int]:
        r = self.region_bytes
        return [
            self.base,
            self.src + r,
            self.enc - _WORD64,
            self.enc + r,
            self.dec - _WORD64,
            self.dec + r,
        ]

    def prefill(self) -> list[tuple[int, int]]:
        """(address, value) of every pre-filled 64-bit word."""
        words = list(zip(self.guard_addrs, self.guard_vals))
        for base, vals in (
            (self.src, self.pt),
            (self.enc, self.enc_fill),
            (self.dec, self.dec_fill),
        ):
            words += [(base + k * _WORD64, v) for k, v in enumerate(vals)]
        return words


class _ClkCounter:
    """Counts ``clk_i`` rising edges while it runs."""

    def __init__(self) -> None:
        self.n = 0
        self._task = None

    async def _run(self) -> None:
        clk = cocotb.top.clk_i
        while True:
            await RisingEdge(clk)
            self.n += 1

    def start(self) -> _ClkCounter:
        self._task = cocotb.start_soon(self._run())
        return self

    def stop(self) -> None:
        if self._task is not None and not self._task.done():
            if hasattr(self._task, "cancel"):
                self._task.cancel()
            else:
                self._task.kill()


@pyuvm.test()
class sep_km_aes_sideload_kat_test(sep_base_test):
    """The sideloaded key drives AES to the golden ciphertext and a full ENC/DEC round trip."""

    async def run_scenario(self) -> None:
        self.required_evidence = (
            "CHK-A",
            "CHK-NEG",
            "CHK-B",
            "CHK-ISO",
            "CHK-F",
            "CHK-RT",
            "CHK-AES-SRAM-KM",
            "CHK-H",
        )
        # --- Boot the real KM firmware on real entropy -------------------------
        # Real fuse-sense with a valid PROD-lifecycle image (the KM firmware reads
        # OTP at boot); stage it before bring-up so sense populates the shadow.
        image = self.select_efuse_image(lc_raw=0x1)  # LC_PROD
        self.write_efuse_image(image)
        await self.bring_up_no_cpu(park=("otbn", "kmac", "hmac"))

        self.km = SepKmMailbox(self)
        self.aes = SepAes(self)

        # OTBN/KMAC/HMAC parked in SW_RESET_N so they never sit ungranted
        # through fuse sense and cannot take the key. AES stays released so its
        # masking-PRNG reseed is served when EDN starts.

        # Strict entropy bring-up: CHK1..CHK4 bit-exact golden; CHK5_km observed
        # (rom_main pull order is firmware-driven); CHK5_aes observed proves the
        # crypto EDN leg delivers real beats to the released AES masking PRNG, not
        # only the KM leg. Fork the concurrent FIFO_RDATA drain so CHK2 is scored
        # without an ESRC FIFO overflow.
        await self.bring_up_entropy(strict=True, score_km="observe", score_sinks={"aes": "observe"})
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.start_fifo_drain()
        self.logger.info("real entropy flowing; releasing KM firmware (rom_main)")

        await self.swrst.release("km")
        await self.km.wait_km_ready()
        self.logger.info("CHK0 KM firmware boot PASS: RESP_KM_READY over the mailbox")

        # --- Frontdoor consume-proof: load known key -> transfer -> encrypt ----
        # CHK-A: provision the KNOWN key into a KPV handle over the frontdoor.
        handle = await self.km.key_load(key_words=list(KAT_KEY), dest=KM_DEST_AES)
        self.logger.info("CHK-A PASS: CMD_KEY_LOAD known key staged, handle=0x%02x", handle)

        # CHK-NEG: negative reference. Encrypt with an unrelated DUMMY SW key BEFORE
        # the transfer. A real encryption, golden-checked, so ct_side !=
        # ct_dummy later is a meaningful "a distinct key was delivered" proof.
        await self.aes.configure_ecb_enc_256(sideload=False)
        await self.aes.write_full_key(list(AES_DUMMY_SW_KEY))
        await self.aes.trigger_prng_reseed()
        ct_dummy = await self.aes.run_ecb_block(list(AES_ECB_PT))
        exp_dummy = aes256_ecb_encrypt_words(list(AES_DUMMY_SW_KEY), list(AES_ECB_PT))
        assert ct_dummy == exp_dummy, (
            "negative-ref AES(dummy) mismatch vs golden:\n"
            f"  got={[hex(w) for w in ct_dummy]} exp={[hex(w) for w in exp_dummy]}"
        )
        self.logger.info("CHK-NEG PASS: dummy-key ECB ct_dummy == AES(dummy, PT) golden")

        # CHK-B: sideload the handle's key to the AES wrapper KEY CSRs.
        rc, _ = await self.km.key_transfer(handle=handle, dest=KM_DEST_AES)
        assert rc == 0, f"CMD_KEY_TRANSFER returned rc={rc} (expected 0)"
        self.logger.info("CHK-B PASS: CMD_KEY_TRANSFER rc=0 (key sideloaded to AES)")

        # CHK-ISO: SW_RESET_N holds AES released and OTBN/KMAC/HMAC parked. This
        # grades the register; CHK-F grades the key in AES.
        rst = await self.swrst.read_back()
        parked = (
            (1 << SW_RESET_N_BIT["otbn"])
            | (1 << SW_RESET_N_BIT["kmac"])
            | (1 << SW_RESET_N_BIT["hmac"])
        )
        assert (rst & parked) == 0, (
            f"key-bus isolation: OTBN/KMAC/HMAC not parked (SW_RESET_N=0x{rst:08x})"
        )
        assert rst & (1 << SW_RESET_N_BIT["aes"]), (
            f"AES not released for the transfer (SW_RESET_N=0x{rst:08x})"
        )
        self.logger.info(
            "CHK-ISO PASS: SW_RESET_N holds AES released and "
            "OTBN/KMAC/HMAC parked (SW_RESET_N=0x%02x)",
            rst,
        )

        # PUB-OBSERVATION: the public KEY_SHARE CSRs read zero, and the read path
        # that produced those zeros is alive. Both halves are asserted:
        # KEY_SHARE0/1 are write-only with read data tied to zero in the generated
        # register block, so on its own "reads zero" is unfalsifiable -- it holds
        # whether the key is protected, mirrored elsewhere, or never delivered.
        # Pairing it with a readable register in the same window at least makes
        # the check fail if the read path dies or if these become readable.
        s0_pub, s1_pub, ctl_pub = await self.aes.read_public_key_shares()
        assert ctl_pub != 0, (
            "PUB-OBSERVATION positive control failed: AES STATUS read back 0 over the same "
            "frontdoor, so the all-zero KEY_SHARE reads prove nothing about the key"
        )
        assert all(w == 0 for w in s0_pub) and all(w == 0 for w in s1_pub), (
            "AES public KEY_SHARE0/1 CSRs not all zero after sideload (key leak): "
            f"s0 nonzero at {[i for i, w in enumerate(s0_pub) if w]}, "
            f"s1 nonzero at {[i for i, w in enumerate(s1_pub) if w]}"
        )
        self.logger.info(
            "INFO-PUB-OBSERVATION AES public KEY_SHARE0/1 frontdoor reads zero after "
            "sideload. Asserted, but aes.hjson declares them swaccess=wo, so this read "
            "alone cannot fail. Read path alive: STATUS=%#010x",
            ctl_pub,
        )

        # CHK-F: encrypt with the SIDELOAD key and value-check against the golden.
        # This proves AES consumed the exact KM-delivered key.
        golden = aes256_ecb_encrypt_words(list(KAT_KEY), list(AES_ECB_PT))
        await self.aes.configure_ecb_enc_256(sideload=True)
        await self.aes.trigger_prng_reseed()
        ct_side = await self.aes.run_ecb_block(list(AES_ECB_PT))
        assert ct_side == golden, (
            "sideload ciphertext != AES(known_key, PT) golden -- AES did not consume "
            "the exact KM-delivered key:\n"
            f"  ct_side={[hex(w) for w in ct_side]}\n"
            f"  golden ={[hex(w) for w in golden]}"
        )
        self.logger.info("CHK-F PASS: KM->AES sideload KAT ct_side == AES(known_key, PT) golden")

        # CHK-RT: decrypt ct_side with the SIDELOAD key and prove it
        # recovers the original plaintext -- the sideloaded key drives a full
        # ENC/DEC round-trip, not just one direction. The recovered PT is checked
        # against the known AES_ECB_PT (value-specific; no decrypt golden needed
        # since the round-trip target is the known input).
        await self.aes.configure_ecb_dec_256(sideload=True)
        await self.aes.trigger_prng_reseed()
        pt_side_dec = await self.aes.run_ecb_block(list(ct_side))
        assert pt_side_dec == list(AES_ECB_PT), (
            "sideload decrypt did not recover the original plaintext:\n"
            f"  pt_side_dec={[hex(w) for w in pt_side_dec]}\n"
            f"  expected PT={[hex(w) for w in AES_ECB_PT]}"
        )
        self.logger.info("CHK-RT PASS: sideload round-trip DEC(ct_side) == original PT")

        # The SRAM leg runs before CHK-H: the software key registers still hold
        # AES_DUMMY_SW_KEY, so a wrong key select gives a ciphertext other than
        # the KAT_KEY golden.
        await self._chk_aes_sram_km()

        # CHK-H: SIDELOAD=0 while the KAT_KEY sideload key is still valid (the
        # SRAM leg above used it). The software key differs from KAT_KEY and the
        # dummy key in every word, so an engine that keeps the sideload key, or a
        # lost key write that leaves the dummy key, gives another ciphertext.
        sw_key = _draw_sw_key(self.random_seed())
        exp_sw = aes256_ecb_encrypt_words(sw_key, list(AES_ECB_PT))
        assert exp_sw not in (golden, exp_dummy), (
            "test bug: the CHK-H golden equals the sideload or dummy-key golden"
        )
        await self.aes.configure_ecb_enc_256(sideload=False)
        await self.aes.write_full_key(sw_key)
        await self.aes.trigger_prng_reseed()
        ct_swref = await self.aes.run_ecb_block(list(AES_ECB_PT))
        assert ct_swref == exp_sw, (
            "CHK-H FAIL: SIDELOAD=0 ciphertext != AES-256-ECB(sw_key, PT) golden "
            f"sw_key_sha={word_digest(sw_key)} got={[hex(w) for w in ct_swref]} "
            f"exp={[hex(w) for w in exp_sw]} sideload_golden={[hex(w) for w in golden]}"
        )
        self.logger.info(
            "CHK-H PASS: SIDELOAD=0 with the sideload key valid, ct_swref == "
            "AES-256-ECB(sw_key, PT) golden sw_key_sha=%s salt=0x%04x got=%s exp=%s "
            "sideload_golden=%s",
            word_digest(sw_key),
            SW_KEY_SALT,
            [hex(w) for w in ct_swref],
            [hex(w) for w in exp_sw],
            [hex(w) for w in golden],
        )

        # --- EOT: entropy health + clean shutdown ------------------------------
        await self.km.check_outbound_empty("EOT")
        await self.aes.wait_idle("EOT")
        # AES raised no recoverable (shadowed-CTRL mismatch) or fatal alert across
        # every block of the leaf, alongside the CSRNG/EDN alert check below.
        await self.aes.check_status_clean("EOT")
        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report()
        self.logger.info("CHK1..CHK5 alive + entropy alerts PASS (DRBG scoreboard)")

    # --- SEP SRAM -> AES (KM key) -> SEP SRAM ---------------------------------
    async def _sram_write(self, addr: int, data: int) -> None:
        """One 64-bit single-beat write by the bench master on the CPU load/store port."""
        seq = SepAxiAccessSeq(
            f"aes_sram_wr_0x{addr:08x}", op=SepAxiOp.WRITE, addr=addr, wdata=data, length=_WORD64
        )
        await self.start_seq(seq)
        assert seq.resp_ok, f"SEP SRAM write @0x{addr:08x} not OKAY"

    async def _sram_read(self, addr: int, count: int = 1) -> list[int]:
        """``count`` consecutive 64-bit single-beat reads by the bench master on the
        CPU load/store port."""
        out: list[int] = []
        for k in range(count):
            a = addr + k * _WORD64
            seq = SepAxiAccessSeq(
                f"aes_sram_rd_0x{a:08x}", op=SepAxiOp.READ, addr=a, length=_WORD64
            )
            await self.start_seq(seq)
            assert seq.resp_ok, f"SEP SRAM read @0x{a:08x} not OKAY"
            out.append(seq.rdata)
        return out

    def _draw_sram_plan(self) -> _SramAesPlan:
        """Draw order: n, window offset, plaintext, encrypt fill, decrypt fill, guards."""
        rng = SepSeededRng(self.random_seed() ^ SRAM_LEG_SALT)
        n = rng.randrange(2, 9)
        slots = (SEP_SRAM_SIZE - _SramAesPlan.window_bytes(n)) // _WORD64 + 1
        base = SEP_SRAM_BASE + rng.randrange(slots) * _WORD64
        pt = [_draw64(rng, set()) for _ in range(2 * n)]
        enc_golden = _pack64(aes_encrypt_words("ecb", list(KAT_KEY), _unpack64(pt)))
        enc_fill = [_draw64(rng, {g}) for g in enc_golden]
        dec_fill = [_draw64(rng, {p}) for p in pt]
        goldens = set(pt) | set(enc_golden)
        guard_vals = [_draw64(rng, goldens) for _ in range(6)]
        return _SramAesPlan(n, base, pt, enc_golden, enc_fill, dec_fill, guard_vals)

    async def _sram_aes_pass(self, src: int, dst: int, n: int, op: str) -> list[int]:
        """Move ``n`` blocks from ``src`` through AES to ``dst``; return per-block cycles.

        The cycle count runs from the DATA_IN_3 write response to the STATUS read
        that shows OUTPUT_VALID. The wait fails the leaf only past the liveness
        timeout ``OUTPUT_VALID_LIVENESS_CYCLES``.
        """
        cycles: list[int] = []
        clk = _ClkCounter().start()
        try:
            for i in range(n):
                block = _unpack64(await self._sram_read(src + i * _BLOCK_BYTES, 2))
                await self.aes.start_block_no_wait(block)
                t0 = clk.n
                while not (await self.aes.read_status()) & (1 << AES_STATUS_OUTPUT_VALID):
                    if clk.n - t0 > OUTPUT_VALID_LIVENESS_CYCLES:
                        raise AssertionError(
                            f"AES SRAM leg op={op} block={i}: OUTPUT_VALID not set within the "
                            f"liveness timeout of {OUTPUT_VALID_LIVENESS_CYCLES} clk_i cycles"
                        )
                cycles.append(clk.n - t0)
                out = _pack64(await self.aes.read_data_out())
                for k, dword in enumerate(out):
                    await self._sram_write(dst + i * _BLOCK_BYTES + k * _WORD64, dword)
        finally:
            clk.stop()
        return cycles

    def _log_latency(self, op: str, cycles: list[int]) -> None:
        self.logger.info(
            "OBS-AES-SRAM-KM-LAT op=%s blocks=%d min=%d max=%d first=%d (clk_i cycles from the "
            "DATA_IN_3 write response to the STATUS read that shows OUTPUT_VALID, STATUS read "
            "latency included; not graded)",
            op,
            len(cycles),
            min(cycles),
            max(cycles),
            cycles[0],
        )

    async def _chk_aes_sram_km(self) -> None:
        """SEP SRAM -> AES (SIDELOAD=1, KM key) -> SEP SRAM, encrypt then decrypt.

        The bench master on the CPU load/store port does every SRAM and AES access
        with single beats. Golden: FIPS-197 AES-256-ECB under KAT_KEY
        (``env/sep_aes_golden.py``); the decrypt golden is the drawn plaintext.
        """
        plan = self._draw_sram_plan()
        self.logger.info(
            "INFO-AES-SRAM-KM-PLAN n=%d window=0x%08x src=0x%08x enc=0x%08x dec=0x%08x "
            "window_bytes=%d salt=0x%04x",
            plan.n,
            plan.base,
            plan.src,
            plan.enc,
            plan.dec,
            _SramAesPlan.window_bytes(plan.n),
            SRAM_LEG_SALT,
        )

        prefill = plan.prefill()
        for addr, value in prefill:
            await self._sram_write(addr, value)
        got = [(await self._sram_read(addr))[0] for addr, _ in prefill]
        exp = [value for _, value in prefill]
        bad = [
            f"0x{a:08x}: got={g:016x} exp={e:016x}"
            for (a, _), g, e in zip(prefill, got, exp)
            if g != e
        ]
        assert not bad, f"CTRL-AES-SRAM-PRE FAIL: pre-fill readback mismatch: {bad}"
        self.logger.info(
            "CTRL-AES-SRAM-PRE PASS: %d pre-filled 64-bit words read back as written "
            "(got=%s exp=%s)",
            len(prefill),
            _hex64(got),
            _hex64(exp),
        )

        await self.aes.configure_ecb_enc_256(sideload=True)
        await self.aes.trigger_prng_reseed()
        enc_cycles = await self._sram_aes_pass(plan.src, plan.enc, plan.n, "enc")
        enc_got = await self._sram_read(plan.enc, 2 * plan.n)
        assert enc_got == plan.enc_golden, (
            "CHK-AES-SRAM-KM FAIL op=enc: encrypt destination != AES-256-ECB(KAT_KEY, plaintext) "
            f"got={_hex64(enc_got)} exp={_hex64(plan.enc_golden)}"
        )
        self.logger.info(
            "CHK-AES-SRAM-KM PASS op=enc n=%d: encrypt destination == AES-256-ECB(KAT_KEY, "
            "plaintext) got=%s exp=%s",
            plan.n,
            _hex64(enc_got),
            _hex64(plan.enc_golden),
        )
        self._log_latency("enc", enc_cycles)

        await self.aes.configure_ecb_dec_256(sideload=True)
        await self.aes.trigger_prng_reseed()
        dec_cycles = await self._sram_aes_pass(plan.enc, plan.dec, plan.n, "dec")
        dec_got = await self._sram_read(plan.dec, 2 * plan.n)
        assert dec_got == plan.pt, (
            "CHK-AES-SRAM-KM FAIL op=dec: decrypt destination != drawn plaintext "
            f"got={_hex64(dec_got)} exp={_hex64(plan.pt)}"
        )
        self.logger.info(
            "CHK-AES-SRAM-KM PASS op=dec n=%d: decrypt destination == drawn plaintext "
            "got=%s exp=%s",
            plan.n,
            _hex64(dec_got),
            _hex64(plan.pt),
        )
        self._log_latency("dec", dec_cycles)

        src_got = await self._sram_read(plan.src, 2 * plan.n)
        assert src_got == plan.pt, (
            "CTRL-AES-SRAM-REGIONS FAIL part=src: source region changed "
            f"got={_hex64(src_got)} exp={_hex64(plan.pt)}"
        )
        guard_got = [(await self._sram_read(a))[0] for a in plan.guard_addrs]
        assert guard_got == plan.guard_vals, (
            "CTRL-AES-SRAM-REGIONS FAIL part=guard: guard word changed "
            f"addrs=[{','.join(f'0x{a:08x}' for a in plan.guard_addrs)}] "
            f"got={_hex64(guard_got)} exp={_hex64(plan.guard_vals)}"
        )
        self.logger.info(
            "CTRL-AES-SRAM-REGIONS PASS part=src,guard: source got=%s exp=%s; guards got=%s exp=%s",
            _hex64(src_got),
            _hex64(plan.pt),
            _hex64(guard_got),
            _hex64(plan.guard_vals),
        )
