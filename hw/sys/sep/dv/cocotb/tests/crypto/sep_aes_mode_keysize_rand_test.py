# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Each AES mode and key size encrypts and round-trips to an independent golden.

RAND-REP. The test drives the OpenTitan AES engine directly over the CPU-LSU AXI master (no_cpu, no
firmware, SW key) across the full standalone matrix the KM->AES sideload
KAT (`sep_km_aes_sideload_kat_test`, ECB-256 via keymgr) does not reach:

    {ECB, CBC, CTR} x {128, 192, 256}  (9 cells).

The independent pure-Python golden (env/sep_aes_golden.py: FIPS-197 ECB 128/192/256 +
SP 800-38A CBC/CTR, self-tested) is the reference. Distinct from
`sep_km_aes_sideload_kat_test` (ECB-256 via sideload) -- AES mode/key-size breadth
is standalone SW-key across modes/sizes.

Entropy: OpenTitan AES masking reseeds its PRNG from the crypto-EDN leg, so the
test brings up the real ESRC->DRBG->EDN stack (+esrc_noise_force) before any AES
op or the engine stalls. OTBN/KMAC/HMAC are parked so AES is the only crypto
EDN client: CHK1..CHK4 are bit-exact, CHK5_aes is per-sink ROUTING golden
(each post-adapter beat equals the next AXIS1 word). KM is unused.

One SepAesCfg object drives both the DUT programming (CTRL, key, IV, data) and
the golden. The nine (mode, key-size) cells are walked on every seed. The seed
sets only the key, IV and plaintext content. The IV write-readback, the
write-only reads and the counter-carry cell draw from a second stream of the
seed, so the values of the nine cells do not depend on them.

IV byte order (aes programmers_guide.md:36): IV_i holds IV bytes 4i..4i+3
little-endian, and the CTR counter is the 16 IV bytes read big-endian, so its
least significant word is bytes 12..15, which is IV_3 byte-swapped.

Checkers (CHK-CELL carries the ciphertext, round-trip and no-alert checks on one log line per cell):
  CHK-CELL     per cell: engine ciphertext == independent golden (2 blocks);
               round trip recovers the plaintext (ECB/CBC via engine DECRYPT, CTR
               via re-encrypt); no AES recoverable/fatal alert across both
  CHK1..CHK4   bit-exact entropy golden (strict scoreboard report)
  CHK5_aes     post-adapter AES beats == AXIS1 in order (single live crypto sink)
  CHK-RAND-REP every discrete cell produced its own golden-matching ciphertext,
               and all ciphertexts are distinct (seed logged)
  CHK-AES-IV-RW      at IDLE after a CBC-128 encrypt CTRL write, a drawn non-zero
                     IV that differs word by word from the IV read before it reads
                     back exactly on IV_0..3 (aes.hjson:546,554)
  CHK-AES-IV-CHAIN   after the last DATA_OUT read of a CBC or CTR leg and IDLE,
                     IV_0..3 hold the chaining value: CBC encrypt and CBC decrypt
                     the last ciphertext block (the decrypt input), CTR the start
                     counter + N mod 2^128 (theory_of_operation.md:65-66,116,160;
                     programmers_guide.md:36,39-40). ECB has no IV. A count line
                     requires every CBC/CTR leg of the walk plus the carry cell.
  CHK-AES-CTR-CARRY  one CTR cell of 17 blocks, drawn key size, whose counter
                     word (bytes 12..15) starts at 0xFFFFFFF0 + a drawn offset,
                     so the counter carries into byte 11 inside the message; every
                     block equals the 128-bit big-endian counter golden
                     (SP 800-38A 6.5, B.1). Control CTRL-AES-CTR-CARRY: that
                     golden differs from a counter that wraps in bytes 12..15.
                     The cell is outside the nine-cell walk and CHK-RAND-REP.

Logged only (no stated value):
  OBS-AES-RESET-SCRUB  after the power-on reseed, with STATUS.IDLE = 1 and an AES
                       EDN beat seen (bounded wait, no raise): IV_0..3,
                       DATA_OUT_0..3, STATUS and the AES EDN request/acknowledge
                       taps. Read before the first DATA_OUT_CLEAR trigger.
  OBS-AES-WO-READ      response code and read data of KEY_SHARE0_0, DATA_IN_0 and
                       TRIGGER after a non-zero write (write-only registers).
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_aes_golden import aes_encrypt_words
from env.sep_aes_mode_golden import bytes_to_words, words_to_bytes
from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from seq_lib.sep_aes_seq import (
    AES_DATA_IN,
    AES_DATA_OUT,
    AES_IV,
    AES_KEY_LEN_128,
    AES_KEY_SHARE0,
    AES_KEYLEN_CTRL,
    AES_MODE_CBC,
    AES_MODE_CTR,
    AES_OP_DEC,
    AES_OP_ENC,
    AES_STATUS,
    AES_STATUS_IDLE,
    AES_TRIGGER,
    AES_TRIGGER_DATA_OUT_CLEAR,
    SepAes,
    SepAesCfg,
)
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq

MODES = ["ecb", "cbc", "ctr"]
KEY_SIZES = [128, 192, 256]
NUM_BLOCKS = 2  # 2 x 128-bit blocks per cell -> exercises CBC chaining / CTR increment

# Second stream of the run seed for the draws outside the nine-cell walk. The
# value is a domain tag, not a credential.
EXTRA_STREAM_TAG = 0x1F5C
# Counter-carry cell: the counter word of bytes 12..15 starts 16 increments
# below the 2^32 wrap plus a drawn offset 0..15, so 17 blocks always carry.
CARRY_BLOCKS = 17
CARRY_SPAN = 16
WORD_MOD = 1 << 32
CTR_MOD = 1 << 128
# Bounded wait of the reset-scrub probe: the poll limit and spacing of SepAes.wait_idle.
SCRUB_POLLS = 4_000
SCRUB_POLL_CYCLES = 20
# AES client index of the crypto EDN taps.
EDN_AES = 0
EDN_TAPS = (
    "crypto_edn_req_o",
    "crypto_edn_ack_o",
    "crypto_edn_sync_req_o",
    "crypto_edn_sync_ack_o",
)
# IV-reading legs: each CBC and CTR cell checks its encrypt and its round-trip
# leg, and the carry cell adds one.
IV_CHAIN_SITES = sum(2 for m in MODES if m != "ecb") * len(KEY_SIZES) + 1


def _hex_words(words: list[int]) -> str:
    return "[" + ",".join(f"0x{w:08x}" for w in words) + "]"


def ctr_after(iv_words: list[int], n_blocks: int) -> list[int]:
    """IV words after ``n_blocks`` CTR increments of the 128-bit big-endian counter."""
    ctr = (int.from_bytes(words_to_bytes(iv_words), "big") + n_blocks) % CTR_MOD
    return bytes_to_words(ctr.to_bytes(16, "big"))


def ctr_wrap32_words(key: list[int], pt: list[int], iv_words: list[int]) -> list[int]:
    """CTR output with a counter that wraps inside bytes 12..15 (bytes 0..11 fixed)."""
    iv = words_to_bytes(iv_words)
    low = int.from_bytes(iv[12:], "big")
    blocks = [iv[:12] + ((low + i) % WORD_MOD).to_bytes(4, "big") for i in range(len(pt) // 4)]
    ks = aes_encrypt_words("ecb", key, bytes_to_words(b"".join(blocks)))
    return [p ^ k for p, k in zip(pt, ks, strict=True)]


@pyuvm.test()
class sep_aes_mode_keysize_rand_test(sep_base_test):
    """AES ECB/CBC/CTR x 128/192/256 with a SW key each match the golden and round-trip."""

    required_evidence = (
        "CHK-CELL",
        "CHK-RAND-REP",
        "CHK-AES-IV-RW",
        "CHK-AES-IV-CHAIN",
        "CHK-AES-CTR-CARRY",
    )

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu(park=("otbn", "hmac", "kmac"))
        # Every other crypto-EDN client is JTAG-held across rst_ni release, then
        # parked in SW_RESET_N, so CHK5_aes golden routing is in order (one live
        # sink). AES stays released for the masking reseed.
        await self.bring_up_entropy(strict=True, score_km=False, score_sinks={"aes": "golden"})
        # The default floor is one scored beat, which is far below what the
        # per-beat routing claim needs across the whole cell walk.
        self.drbg_sb.set_min_matches(CHK5_aes=32)
        self.start_fifo_drain()
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"

        self.aes = SepAes(self)
        seed = self.random_seed()
        self.rng = SepSeededRng(seed)
        self.rng_extra = SepSeededRng(seed ^ EXTRA_STREAM_TAG)
        self.iv_chain_n = 0
        self.logger.info("AES mode x key-size breadth: seed=%d", seed)
        await self._obs_reset_scrub()
        await self.aes.trigger_prng_reseed()  # seed the masking PRNG from EDN
        await self._chk_iv_rw()
        await self._obs_wo_read()

        # Collect each cell's DUT ciphertext, so the matrix claim rests on observed
        # output. Distinct results also show the nine cells programmed nine different
        # configurations: two cells that silently ran the same mode and key size on
        # the same random inputs would collide here.
        results: dict[str, tuple[int, ...]] = {}
        for mode in MODES:
            for key_bits in KEY_SIZES:
                results[f"{mode}-{key_bits}"] = await self._run_cell(mode, key_bits)

        walked = len(results)
        expected = len(MODES) * len(KEY_SIZES)
        # Construction guard, not a DUT contract: this compares the walk against
        # the cell list that drove it, so only a table or keying mistake in this
        # file can trip it. The DUT evidence is the per-cell golden compare.
        assert walked == expected, f"walked {walked} cells != {expected}"
        assert len(set(results.values())) == expected, (
            "AES cells produced duplicate ciphertexts, so they did not all run distinct "
            "configurations: " + ", ".join(f"{k}={results[k][0]:#010x}" for k in sorted(results))
        )
        await self._run_carry_cell()
        assert self.iv_chain_n == IV_CHAIN_SITES, (
            f"CHK-AES-IV-CHAIN FAIL: {self.iv_chain_n} IV reads != {IV_CHAIN_SITES} legs"
        )
        self.logger.info(
            "CHK-AES-IV-CHAIN PASS: %d CBC/CTR legs read the chaining IV (walk + carry cell)",
            self.iv_chain_n,
        )
        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report()
        self.logger.info("CHK1..CHK4 bit-exact + CHK5_aes ROUTING (AES==AXIS1) PASS")
        self.logger.info(
            "CHK-RAND-REP PASS: walked all %d discrete cells ({ECB,CBC,CTR} x "
            "{128,192,256}) in one invocation (seed=%d); key/IV/plaintext "
            "randomized per cell; entropy alerts clean",
            walked,
            seed,
        )

    def _rand_words(self, n: int) -> list[int]:
        return [self.rng.getrandbits(32) for _ in range(n)]

    async def _read_iv(self) -> list[int]:
        return [await self.aes._rd(addr) for addr in AES_IV]

    async def _obs_reset_scrub(self) -> None:
        """Log IV, DATA_OUT and the AES EDN taps after the power-on reseed (no grade)."""
        dut = cocotb.top
        st = 0
        beats = 0
        met = False
        for _ in range(SCRUB_POLLS):
            st = await self.aes._rd(AES_STATUS)
            beats = self.drbg_sb.sink_beats("aes")
            if (st >> AES_STATUS_IDLE) & 1 and beats > 0:
                met = True
                break
            await ClockCycles(dut.clk_i, SCRUB_POLL_CYCLES)
        iv = await self._read_iv()
        out = [await self.aes._rd(addr) for addr in AES_DATA_OUT]
        st = await self.aes._rd(AES_STATUS)
        taps = " ".join(
            f"{name}[{EDN_AES}]={self.rd(getattr(dut, name), 1 << EDN_AES, allow_unknown=True)}"
            for name in EDN_TAPS
        )
        self.logger.info(
            "OBS-AES-RESET-SCRUB iv=%s data_out=%s status=0x%08x %s aes_beats=%d "
            "ack_seen=%d bound_polls=%d",
            _hex_words(iv),
            _hex_words(out),
            st,
            taps,
            beats,
            int(met),
            SCRUB_POLLS,
        )

    async def _chk_iv_rw(self) -> None:
        """At IDLE a drawn non-zero IV reads back exactly (IV_0..3 are rw)."""
        await self.aes.configure(mode=AES_MODE_CBC, key_len=AES_KEY_LEN_128, operation=AES_OP_ENC)
        pre = await self._read_iv()
        want = []
        for p in pre:
            w = self.rng_extra.randrange(1, WORD_MOD - 1)
            want.append(~w & (WORD_MOD - 1) if w == p else w)
        await self.aes.write_iv(want)
        await self.aes.wait_idle("post-iv-rw")
        got = await self._read_iv()
        assert got == want, (
            f"CHK-AES-IV-RW FAIL: IV read {_hex_words(got)} != written {_hex_words(want)} "
            f"(before write {_hex_words(pre)})"
        )
        self.logger.info(
            "CHK-AES-IV-RW PASS: IV_0..3 read back the written %s at IDLE (before write %s)",
            _hex_words(want),
            _hex_words(pre),
        )

    async def _obs_wo_read(self) -> None:
        """Log the read of each write-only register after a non-zero write (no grade)."""
        writes = (
            ("KEY_SHARE0_0", AES_KEY_SHARE0[0], self.rng_extra.randrange(1, WORD_MOD)),
            ("DATA_IN_0", AES_DATA_IN[0], self.rng_extra.randrange(1, WORD_MOD)),
            ("TRIGGER", AES_TRIGGER, AES_TRIGGER_DATA_OUT_CLEAR),
        )
        for _name, addr, value in writes:
            await self.aes._wr(addr, value)
        await self.aes.wait_idle("post-wo-write")
        for name, addr, value in writes:
            seq = SepAxiAccessSeq(
                f"aes_wo_rd_{name.lower()}",
                op=SepAxiOp.READ,
                addr=addr,
                size=2,
                allow_ungraded_read_resp=True,
            )
            await self.start_seq(seq)
            self.logger.info(
                "OBS-AES-WO-READ reg=%s addr=0x%08x wrote=0x%08x resp=%d rdata=0x%08x",
                name,
                addr,
                value,
                seq.resp_code,
                seq.rdata & (WORD_MOD - 1),
            )

    async def _chk_iv_chain(self, cell: str, leg: str, want: list[int]) -> None:
        """After the last DATA_OUT read and IDLE, IV_0..3 hold the chaining value."""
        await self.aes.wait_idle(f"{cell}-{leg}-iv")
        got = await self._read_iv()
        assert got == want, (
            f"CHK-AES-IV-CHAIN FAIL {cell} {leg}: IV {_hex_words(got)} != {_hex_words(want)}"
        )
        self.iv_chain_n += 1
        self.logger.info("CHK-AES-IV-CHAIN PASS %s %s: IV=%s", cell, leg, _hex_words(got))

    async def _run_carry_cell(self) -> None:
        """One CTR cell whose 128-bit counter carries from byte 12 into byte 11."""
        rng = self.rng_extra
        key_bits = rng.choice(KEY_SIZES)
        key = [rng.getrandbits(32) for _ in range(key_bits // 32)]
        off = rng.randrange(0, CARRY_SPAN)
        head = bytes(rng.getrandbits(8) for _ in range(12))
        low = WORD_MOD - CARRY_SPAN + off
        iv = bytes_to_words(head + low.to_bytes(4, "big"))
        pt = [rng.getrandbits(32) for _ in range(4 * CARRY_BLOCKS)]
        cell = f"AES-CTR-CARRY-{key_bits}"
        carry_block = WORD_MOD - low  # first block whose counter word wrapped
        golden = aes_encrypt_words("ctr", key, pt, iv)
        wrapped = ctr_wrap32_words(key, pt, iv)
        ctrl_ok = golden != wrapped and carry_block <= CARRY_BLOCKS - 1
        assert ctrl_ok, (
            f"CTRL-AES-CTR-CARRY FAIL: off={off} carry_block={carry_block} "
            f"golden differs from 32-bit wrap={int(golden != wrapped)}"
        )
        self.logger.info(
            "CTRL-AES-CTR-CARRY PASS: off=%d counter_word=0x%08x carry_block=%d of %d; "
            "128-bit golden differs from a 32-bit wrapping counter",
            off,
            low,
            carry_block,
            CARRY_BLOCKS,
        )
        await self.aes.configure(
            mode=AES_MODE_CTR, key_len=AES_KEYLEN_CTRL[key_bits], operation=AES_OP_ENC
        )
        await self.aes.load_key_iv(key, iv)
        ct = await self.aes.run_blocks(pt)
        bad = [b for b in range(CARRY_BLOCKS) if ct[4 * b : 4 * b + 4] != golden[4 * b : 4 * b + 4]]
        assert not bad, (
            f"CHK-AES-CTR-CARRY FAIL {cell}: blocks {bad} != golden (carry block {carry_block}, "
            f"IV={_hex_words(iv)})"
        )
        await self.aes.check_status_clean(cell)
        self.logger.info(
            "CHK-AES-CTR-CARRY PASS %s: %d blocks == 128-bit counter golden, carry at block %d, "
            "IV=%s",
            cell,
            CARRY_BLOCKS,
            carry_block,
            _hex_words(iv),
        )
        await self._chk_iv_chain(cell, "enc", ctr_after(iv, CARRY_BLOCKS))

    async def _run_cell(self, mode: str, key_bits: int) -> tuple[int, ...]:
        key = self._rand_words(key_bits // 32)
        pt = self._rand_words(4 * NUM_BLOCKS)
        iv = self._rand_words(4) if mode != "ecb" else None
        cfg = SepAesCfg(mode=mode, key_bits=key_bits, key_words=key, pt_words=pt, iv_words=iv)
        cell = f"AES-{mode.upper()}-{key_bits}"

        # --- CHK-CELL (ciphertext): encrypt and value-check against the independent golden ---
        await self.aes.configure(
            mode=cfg.mode_ctrl(), key_len=cfg.keylen_ctrl(), operation=AES_OP_ENC
        )
        await self.aes.load_key_iv(key, iv)  # spec-ordered: idle between key + IV
        ct = await self.aes.run_blocks(pt)
        golden = aes_encrypt_words(**cfg.golden_kwargs())
        assert ct == golden, (
            f"{cell} ciphertext != golden:\n  ct    ={[hex(w) for w in ct]}\n"
            f"  golden={[hex(w) for w in golden]}"
        )

        if mode == "cbc":
            await self._chk_iv_chain(cell, "enc", golden[-4:])
        elif mode == "ctr":
            await self._chk_iv_chain(cell, "enc", ctr_after(iv, NUM_BLOCKS))

        await self.aes.check_status_clean(cell + "-enc")  # CHK-CELL (no alert)

        # --- CHK-CELL (round trip): recover the plaintext --------------------
        if mode in ("ecb", "cbc"):
            await self.aes.configure(
                mode=cfg.mode_ctrl(), key_len=cfg.keylen_ctrl(), operation=AES_OP_DEC
            )
            await self.aes.load_key_iv(key, iv)  # CBC decrypt needs the original IV
            rt = await self.aes.run_blocks(ct)
            if mode == "cbc":  # the decrypt input is the verified ciphertext
                await self._chk_iv_chain(cell, "dec", golden[-4:])
        else:  # CTR is a stream cipher: re-encrypting the ciphertext yields the pt
            await self.aes.configure(
                mode=cfg.mode_ctrl(), key_len=cfg.keylen_ctrl(), operation=AES_OP_ENC
            )
            await self.aes.load_key_iv(key, iv)
            rt = await self.aes.run_blocks(ct)
            await self._chk_iv_chain(cell, "reenc", ctr_after(iv, NUM_BLOCKS))
        assert rt == pt, (
            f"{cell} round-trip != plaintext:\n  rt={[hex(w) for w in rt]}\n"
            f"  pt={[hex(w) for w in pt]}"
        )
        await self.aes.check_status_clean(cell + "-rt")

        self.logger.info(
            "CHK-CELL PASS %s: ct==golden, round-trip==pt, no alert, non-vacuous (%d blocks)",
            cell,
            NUM_BLOCKS,
        )
        return tuple(ct)
