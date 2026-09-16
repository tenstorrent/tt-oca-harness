# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CTR_DRBG (AES-256, no derivation function) golden model for the SEP OSS flow.

Implements NIST SP 800-90A Section 10.2.1 CTR_DRBG with **no derivation
function** (AES-256, no-df).

Self-contained: includes a minimal pure-Python AES (128/192/256 ECB encrypt) so
this has no dependency on pycryptodome/cryptography. Because the reference is
the published NIST construction -- not observed DUT output -- a genbits mismatch
is a real failure, not a tautology.

Determined parameters:
  * AES key size : 256 bits
  * BlkLen       : 128 bits
  * SeedLen      : 384 bits
  * CtrLen       : 32 bits; CtrLen < BlkLen so only V[31:0] increments
                              and wraps mod 2**32
  * Derivation function : NONE (RTL line 5; seed consumed directly)
  * Block output ordering : MSB-first chain. In update(), the i-th cipher block
                            is shifted into the high end of `temp`
                            (`temp = {temp, output_block}`), so the first
                            encrypted block ends up as the most-significant block
                            of the 384-bit `temp`. In generate(), each cipher
                            block is emitted as one 128-bit big-endian word
                            in the order produced.

RTL-specific behavior relative to a textbook SP800-90A description:
  * instantiate() does NOT apply a derivation function. The 384-bit entropy is
    XORed with the 384-bit additional_input and fed straight into
    ctr_drbg_update as the provided_data / seed_material. (CAVP "use df = false".)
  * generate() unconditionally runs the final update(additional_input) after the
    block loop, matching SP800-90A step 6. With additional_input == 0,
    update still mutates Key and V (it is NOT skipped) -- the all-zero seed is a
    valid provided_data, exactly as the SV does it.
  * V counter increment: only the low CtrLen (32) bits increment and wrap mod
    2**32; the high (BlkLen-CtrLen) bits of V are preserved.
"""

from __future__ import annotations

from typing import List

# ---------------------------------------------------------------------------
# CTR_DRBG parameters.
# ---------------------------------------------------------------------------
KEY_LEN = 256
BLOCK_LEN = 128
SEED_LEN = KEY_LEN + BLOCK_LEN  # 384
CTR_LEN = 32

_BLK_MASK = (1 << BLOCK_LEN) - 1
_SEED_MASK = (1 << SEED_LEN) - 1
_CTR_MASK = (1 << CTR_LEN) - 1


# ===========================================================================
# Minimal self-contained AES (ECB encrypt only), FIPS-197.
# Supports 128/192/256-bit keys; the DRBG uses AES-256.
# ===========================================================================
_SBOX = [
    0x63,
    0x7C,
    0x77,
    0x7B,
    0xF2,
    0x6B,
    0x6F,
    0xC5,
    0x30,
    0x01,
    0x67,
    0x2B,
    0xFE,
    0xD7,
    0xAB,
    0x76,
    0xCA,
    0x82,
    0xC9,
    0x7D,
    0xFA,
    0x59,
    0x47,
    0xF0,
    0xAD,
    0xD4,
    0xA2,
    0xAF,
    0x9C,
    0xA4,
    0x72,
    0xC0,
    0xB7,
    0xFD,
    0x93,
    0x26,
    0x36,
    0x3F,
    0xF7,
    0xCC,
    0x34,
    0xA5,
    0xE5,
    0xF1,
    0x71,
    0xD8,
    0x31,
    0x15,
    0x04,
    0xC7,
    0x23,
    0xC3,
    0x18,
    0x96,
    0x05,
    0x9A,
    0x07,
    0x12,
    0x80,
    0xE2,
    0xEB,
    0x27,
    0xB2,
    0x75,
    0x09,
    0x83,
    0x2C,
    0x1A,
    0x1B,
    0x6E,
    0x5A,
    0xA0,
    0x52,
    0x3B,
    0xD6,
    0xB3,
    0x29,
    0xE3,
    0x2F,
    0x84,
    0x53,
    0xD1,
    0x00,
    0xED,
    0x20,
    0xFC,
    0xB1,
    0x5B,
    0x6A,
    0xCB,
    0xBE,
    0x39,
    0x4A,
    0x4C,
    0x58,
    0xCF,
    0xD0,
    0xEF,
    0xAA,
    0xFB,
    0x43,
    0x4D,
    0x33,
    0x85,
    0x45,
    0xF9,
    0x02,
    0x7F,
    0x50,
    0x3C,
    0x9F,
    0xA8,
    0x51,
    0xA3,
    0x40,
    0x8F,
    0x92,
    0x9D,
    0x38,
    0xF5,
    0xBC,
    0xB6,
    0xDA,
    0x21,
    0x10,
    0xFF,
    0xF3,
    0xD2,
    0xCD,
    0x0C,
    0x13,
    0xEC,
    0x5F,
    0x97,
    0x44,
    0x17,
    0xC4,
    0xA7,
    0x7E,
    0x3D,
    0x64,
    0x5D,
    0x19,
    0x73,
    0x60,
    0x81,
    0x4F,
    0xDC,
    0x22,
    0x2A,
    0x90,
    0x88,
    0x46,
    0xEE,
    0xB8,
    0x14,
    0xDE,
    0x5E,
    0x0B,
    0xDB,
    0xE0,
    0x32,
    0x3A,
    0x0A,
    0x49,
    0x06,
    0x24,
    0x5C,
    0xC2,
    0xD3,
    0xAC,
    0x62,
    0x91,
    0x95,
    0xE4,
    0x79,
    0xE7,
    0xC8,
    0x37,
    0x6D,
    0x8D,
    0xD5,
    0x4E,
    0xA9,
    0x6C,
    0x56,
    0xF4,
    0xEA,
    0x65,
    0x7A,
    0xAE,
    0x08,
    0xBA,
    0x78,
    0x25,
    0x2E,
    0x1C,
    0xA6,
    0xB4,
    0xC6,
    0xE8,
    0xDD,
    0x74,
    0x1F,
    0x4B,
    0xBD,
    0x8B,
    0x8A,
    0x70,
    0x3E,
    0xB5,
    0x66,
    0x48,
    0x03,
    0xF6,
    0x0E,
    0x61,
    0x35,
    0x57,
    0xB9,
    0x86,
    0xC1,
    0x1D,
    0x9E,
    0xE1,
    0xF8,
    0x98,
    0x11,
    0x69,
    0xD9,
    0x8E,
    0x94,
    0x9B,
    0x1E,
    0x87,
    0xE9,
    0xCE,
    0x55,
    0x28,
    0xDF,
    0x8C,
    0xA1,
    0x89,
    0x0D,
    0xBF,
    0xE6,
    0x42,
    0x68,
    0x41,
    0x99,
    0x2D,
    0x0F,
    0xB0,
    0x54,
    0xBB,
    0x16,
]
_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36, 0x6C, 0xD8, 0xAB, 0x4D]


def _xtime(a: int) -> int:
    """Multiply by x (i.e. 0x02) in GF(2**8) with the AES reduction polynomial."""
    a <<= 1
    if a & 0x100:
        a ^= 0x11B
    return a & 0xFF


def _gmul(a: int, b: int) -> int:
    """GF(2**8) multiply."""
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        b >>= 1
        a = _xtime(a)
    return p


class _AES:
    """Minimal AES block cipher: key expansion + single-block ECB encrypt."""

    def __init__(self, key_bytes: bytes):
        nk = len(key_bytes) // 4
        if nk not in (4, 6, 8):
            raise ValueError("AES key must be 16, 24 or 32 bytes")
        self.nr = {4: 10, 6: 12, 8: 14}[nk]
        self._w = self._expand_key(key_bytes, nk, self.nr)

    @staticmethod
    def _expand_key(key: bytes, nk: int, nr: int):
        # Word list; each word is a 4-byte list.
        w = [list(key[4 * i : 4 * i + 4]) for i in range(nk)]
        for i in range(nk, 4 * (nr + 1)):
            temp = list(w[i - 1])
            if i % nk == 0:
                temp = temp[1:] + temp[:1]  # RotWord
                temp = [_SBOX[b] for b in temp]  # SubWord
                temp[0] ^= _RCON[i // nk - 1]
            elif nk > 6 and i % nk == 4:
                temp = [_SBOX[b] for b in temp]  # SubWord (AES-256)
            w.append([w[i - nk][j] ^ temp[j] for j in range(4)])
        return w

    def _add_round_key(self, state, rnd):
        for c in range(4):
            word = self._w[rnd * 4 + c]
            for r in range(4):
                state[r][c] ^= word[r]

    @staticmethod
    def _sub_bytes(state):
        for r in range(4):
            for c in range(4):
                state[r][c] = _SBOX[state[r][c]]

    @staticmethod
    def _shift_rows(state):
        for r in range(1, 4):
            state[r] = state[r][r:] + state[r][:r]

    @staticmethod
    def _mix_columns(state):
        for c in range(4):
            a0, a1, a2, a3 = (state[r][c] for r in range(4))
            state[0][c] = _gmul(a0, 2) ^ _gmul(a1, 3) ^ a2 ^ a3
            state[1][c] = a0 ^ _gmul(a1, 2) ^ _gmul(a2, 3) ^ a3
            state[2][c] = a0 ^ a1 ^ _gmul(a2, 2) ^ _gmul(a3, 3)
            state[3][c] = _gmul(a0, 3) ^ a1 ^ a2 ^ _gmul(a3, 2)

    def encrypt_block(self, block: bytes) -> bytes:
        # State is column-major per FIPS-197: state[row][col], input byte i -> [i%4][i//4]
        state = [[block[r + 4 * c] for c in range(4)] for r in range(4)]
        self._add_round_key(state, 0)
        for rnd in range(1, self.nr):
            self._sub_bytes(state)
            self._shift_rows(state)
            self._mix_columns(state)
            self._add_round_key(state, rnd)
        self._sub_bytes(state)
        self._shift_rows(state)
        self._add_round_key(state, self.nr)
        return bytes(state[r][c] for c in range(4) for r in range(4))


def _aes_ecb_encrypt_int(key_int: int, key_len_bits: int, block_int: int) -> int:
    """AES-ECB encrypt one 128-bit integer block with an integer key (big-endian)."""
    key_bytes = key_int.to_bytes(key_len_bits // 8, "big")
    pt = block_int.to_bytes(16, "big")
    ct = _AES(key_bytes).encrypt_block(pt)
    return int.from_bytes(ct, "big")


# ===========================================================================
# CTR_DRBG golden (AES-256, no derivation function).
# ===========================================================================
class SepCtrDrbgGolden:
    """NIST SP 800-90A CTR_DRBG, AES-256, no derivation function.

    State: ``key`` (256b int), ``v`` (128b int), ``reseed_counter`` (32b int).
    """

    def __init__(self) -> None:
        self.key = 0
        self.v = 0
        self.reseed_counter = 0
        self.instantiated = False

    # -- AES-256 ECB block encrypt (SV block_encrypt, lines 53-70) -----------
    def _block_encrypt(self, key: int, input_block: int) -> int:
        return _aes_ecb_encrypt_int(key & ((1 << KEY_LEN) - 1), KEY_LEN, input_block & _BLK_MASK)

    # -- V counter increment (CtrLen < BlkLen branch) ------------------------
    def _v_increment(self) -> None:
        low = self.v & _CTR_MASK
        inc = (low + 1) & _CTR_MASK  # wrap mod 2**CTR_LEN
        self.v = (self.v & ~_CTR_MASK) | inc  # preserve high (BlkLen-CtrLen) bits
        self.v &= _BLK_MASK

    # -- ctr_drbg_update ------------------------------------------------------
    def _update(self, provided_data: int) -> None:
        provided_data &= _SEED_MASK
        temp = 0
        for _ in range(SEED_LEN // BLOCK_LEN):  # 3 iterations
            self._v_increment()
            output_block = self._block_encrypt(self.key, self.v)
            # SV: temp = {temp, output_block}  -> MSB-first concatenation
            temp = ((temp << BLOCK_LEN) | output_block) & _SEED_MASK
        temp ^= provided_data
        self.key = (temp >> BLOCK_LEN) & ((1 << KEY_LEN) - 1)  # temp[SEED_LEN-1 : BLOCK_LEN]
        self.v = temp & _BLK_MASK  # temp[BLOCK_LEN-1 : 0]

    # -- ctr_drbg_instantiate -------------------------------------------------
    def instantiate(self, entropy_384b: int, additional_input: int = 0) -> None:
        """Instantiate with a 384-bit entropy input (no df). additional_input is
        a 384-bit value XORed into the seed material (default 0)."""
        seed_material = (entropy_384b ^ additional_input) & _SEED_MASK
        self.key = 0
        self.v = 0
        self.instantiated = True
        self._update(seed_material)
        self.reseed_counter = 1

    # -- ctr_drbg_reseed ------------------------------------------------------
    def reseed(self, entropy_384b: int, additional_input: int = 0) -> None:
        seed_material = (entropy_384b ^ additional_input) & _SEED_MASK
        self._update(seed_material)
        self.reseed_counter = 1

    # -- ctr_drbg_generate ----------------------------------------------------
    def generate(self, num_128b_blocks: int, additional_input: int = 0) -> List[int]:
        """Generate ``num_128b_blocks`` blocks of 128-bit output.

        Returns a list of 128-bit integers, in generation order (first block
        first). Mirrors SP800-90A 10.2.1.5.1 / SV ctr_drbg_generate: optional
        leading update when additional_input != 0, the V++/AES block loop, then
        the mandatory trailing update(additional_input)."""
        additional_input &= _SEED_MASK
        if additional_input != 0:
            self._update(additional_input)

        out: List[int] = [self.generate_one() for _ in range(num_128b_blocks)]

        self.generate_done(additional_input)
        return out

    # -- per-block Generate, for RTL-segmented (demand-driven) modelling ----
    #
    # A CSRNG Generate(glen) command is glen x (V++, AES) followed by exactly
    # ONE trailing Update. The block VALUES depend only on the running (key, V)
    # chain, but WHERE that trailing Update lands depends on the command
    # boundaries -- and those are set by EDN endpoint demand, which the golden
    # cannot predict on its own. So model one block at a time and take the
    # boundary from the observed gen_last strobe
    # (ctr_drbg_generate_one + gen_last -> ctr_drbg_generate_done).
    # A fixed glen desynchronises the chain as soon as a second Generate runs on
    # one seed.
    def generate_one(self) -> int:
        """One 128b Generate output block. No trailing Update -- see generate_done()."""
        self._v_increment()
        return self._block_encrypt(self.key, self.v)

    def generate_done(self, additional_input: int = 0) -> None:
        """Finalize a Generate command: the single trailing Update."""
        self._update(additional_input & _SEED_MASK)
        self.reseed_counter += 1

    def uninstantiate(self) -> None:
        self.key = 0
        self.v = 0
        self.reseed_counter = 0
        self.instantiated = False


# ===========================================================================
# Self-tests (plain python3, no simulator)
# ===========================================================================
def _selftest_aes() -> None:
    # FIPS-197 / NIST AES-256 ECB known-answer.
    key = 0x000102030405060708090A0B0C0D0E0F101112131415161718191A1B1C1D1E1F
    pt = 0x00112233445566778899AABBCCDDEEFF
    expected_ct = 0x8EA2B7CA516745BFEAFC49904B496089
    got = _aes_ecb_encrypt_int(key, 256, pt)
    assert got == expected_ct, f"AES-256 KAT FAIL: got {got:032x} expected {expected_ct:032x}"

    # FIPS-197 AES-128 KAT (exercises the 128-bit key schedule path too).
    key128 = 0x000102030405060708090A0B0C0D0E0F
    expected128 = 0x69C4E0D86A7B0430D8CDB78070B4C55A
    got128 = _aes_ecb_encrypt_int(key128, 128, pt)
    assert got128 == expected128, f"AES-128 KAT FAIL: got {got128:032x}"

    # FIPS-197 AES-192 KAT (exercises the 192-bit key schedule path).
    key192 = 0x000102030405060708090A0B0C0D0E0F1011121314151617
    expected192 = 0xDDA97CA4864CDFE06EAF70A0EC0D7191
    got192 = _aes_ecb_encrypt_int(key192, 192, pt)
    assert got192 == expected192, f"AES-192 KAT FAIL: got {got192:032x}"
    print("AES KAT PASS (AES-128/192/256 ECB FIPS-197)")


def _selftest_ctr_drbg() -> None:
    # ----------------------------------------------------------------------
    # Official NIST CAVP DRBG800-90A vector.
    # [AES-256 no df]  [PredictionResistance = False]  [no reseed]
    # [PersonalizationStringLen = 0]  [AdditionalInputLen = 0]
    # [EntropyInputLen = 384]  [ReturnedBitsLen = 512]
    # COUNT = 0
    #
    # Flow per CAVP "no reseed": Instantiate(EntropyInput);
    # Generate(ReturnedBitsLen, AdditionalInput=0)  -- discarded;
    # Generate(ReturnedBitsLen, AdditionalInput=0)  -- == ReturnedBits.
    # ----------------------------------------------------------------------
    entropy = 0xDF5D73FAA468649EDDA33B5CCA79B0B05600419CCB7A879DDFEC9DB32EE494E5531B51DE16A30F769262474C73BEC010
    expected_returned_bits = 0xD1C07CD95AF8A7F11012C84CE48BB8CB87189E99D40FCCB1771C619BDF82AB2280B1DC2F2581F39164F7AC0C510494B3A43C41B7DB17514C87B107AE793E01C5
    returned_bits_len_bits = 512
    num_blocks = returned_bits_len_bits // BLOCK_LEN  # 4 blocks of 128b

    drbg = SepCtrDrbgGolden()
    drbg.instantiate(entropy)
    drbg.generate(num_blocks)  # first generate -- discarded per CAVP
    blocks = drbg.generate(num_blocks)  # second generate -- the returned bits

    # Blocks are emitted MSB-first; concatenate into the 512-bit returned value.
    got = 0
    for blk in blocks:
        got = (got << BLOCK_LEN) | (blk & _BLK_MASK)

    assert got == expected_returned_bits, (
        f"CTR_DRBG KAT FAIL:\n  got      {got:0128x}\n  expected {expected_returned_bits:0128x}"
    )
    print("CTR_DRBG KAT PASS (NIST CAVP AES-256 use df=false, no reseed, COUNT=0)")


if __name__ == "__main__":
    _selftest_aes()
    _selftest_ctr_drbg()
    print("CTRDRBG GOLDEN SELFTEST PASS")
