# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CTR_DRBG (AES-256, no derivation function) golden model for the SEP OSS flow.

Implements NIST SP 800-90A Section 10.2.1 CTR_DRBG with **no derivation
function**. Cross-checked against the synthesizable
RTL ``vendor/lowRISC/opentitan/upstream/hw/ip/csrng/rtl/csrng_ctr_drbg.sv`` (no-df, AES-256, CtrLen < BlkLen).

Self-contained: includes a minimal pure-Python AES (128/192/256 ECB encrypt) so
this has no dependency on pycryptodome/cryptography. Because the reference is
derived from the spec/RTL -- not from observed DUT output -- a genbits mismatch
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
    0x63, 0x7c, 0x77, 0x7b, 0xf2, 0x6b, 0x6f, 0xc5, 0x30, 0x01, 0x67, 0x2b, 0xfe, 0xd7, 0xab, 0x76,
    0xca, 0x82, 0xc9, 0x7d, 0xfa, 0x59, 0x47, 0xf0, 0xad, 0xd4, 0xa2, 0xaf, 0x9c, 0xa4, 0x72, 0xc0,
    0xb7, 0xfd, 0x93, 0x26, 0x36, 0x3f, 0xf7, 0xcc, 0x34, 0xa5, 0xe5, 0xf1, 0x71, 0xd8, 0x31, 0x15,
    0x04, 0xc7, 0x23, 0xc3, 0x18, 0x96, 0x05, 0x9a, 0x07, 0x12, 0x80, 0xe2, 0xeb, 0x27, 0xb2, 0x75,
    0x09, 0x83, 0x2c, 0x1a, 0x1b, 0x6e, 0x5a, 0xa0, 0x52, 0x3b, 0xd6, 0xb3, 0x29, 0xe3, 0x2f, 0x84,
    0x53, 0xd1, 0x00, 0xed, 0x20, 0xfc, 0xb1, 0x5b, 0x6a, 0xcb, 0xbe, 0x39, 0x4a, 0x4c, 0x58, 0xcf,
    0xd0, 0xef, 0xaa, 0xfb, 0x43, 0x4d, 0x33, 0x85, 0x45, 0xf9, 0x02, 0x7f, 0x50, 0x3c, 0x9f, 0xa8,
    0x51, 0xa3, 0x40, 0x8f, 0x92, 0x9d, 0x38, 0xf5, 0xbc, 0xb6, 0xda, 0x21, 0x10, 0xff, 0xf3, 0xd2,
    0xcd, 0x0c, 0x13, 0xec, 0x5f, 0x97, 0x44, 0x17, 0xc4, 0xa7, 0x7e, 0x3d, 0x64, 0x5d, 0x19, 0x73,
    0x60, 0x81, 0x4f, 0xdc, 0x22, 0x2a, 0x90, 0x88, 0x46, 0xee, 0xb8, 0x14, 0xde, 0x5e, 0x0b, 0xdb,
    0xe0, 0x32, 0x3a, 0x0a, 0x49, 0x06, 0x24, 0x5c, 0xc2, 0xd3, 0xac, 0x62, 0x91, 0x95, 0xe4, 0x79,
    0xe7, 0xc8, 0x37, 0x6d, 0x8d, 0xd5, 0x4e, 0xa9, 0x6c, 0x56, 0xf4, 0xea, 0x65, 0x7a, 0xae, 0x08,
    0xba, 0x78, 0x25, 0x2e, 0x1c, 0xa6, 0xb4, 0xc6, 0xe8, 0xdd, 0x74, 0x1f, 0x4b, 0xbd, 0x8b, 0x8a,
    0x70, 0x3e, 0xb5, 0x66, 0x48, 0x03, 0xf6, 0x0e, 0x61, 0x35, 0x57, 0xb9, 0x86, 0xc1, 0x1d, 0x9e,
    0xe1, 0xf8, 0x98, 0x11, 0x69, 0xd9, 0x8e, 0x94, 0x9b, 0x1e, 0x87, 0xe9, 0xce, 0x55, 0x28, 0xdf,
    0x8c, 0xa1, 0x89, 0x0d, 0xbf, 0xe6, 0x42, 0x68, 0x41, 0x99, 0x2d, 0x0f, 0xb0, 0x54, 0xbb, 0x16,
]
_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36, 0x6c, 0xd8, 0xab, 0x4d]


def _xtime(a: int) -> int:
    """Multiply by x (i.e. 0x02) in GF(2**8) with the AES reduction polynomial."""
    a <<= 1
    if a & 0x100:
        a ^= 0x11b
    return a & 0xff


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
        w = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
        for i in range(nk, 4 * (nr + 1)):
            temp = list(w[i - 1])
            if i % nk == 0:
                temp = temp[1:] + temp[:1]                       # RotWord
                temp = [_SBOX[b] for b in temp]                  # SubWord
                temp[0] ^= _RCON[i // nk - 1]
            elif nk > 6 and i % nk == 4:
                temp = [_SBOX[b] for b in temp]                  # SubWord (AES-256)
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
        low = (self.v & _CTR_MASK)
        inc = (low + 1) & _CTR_MASK            # wrap mod 2**CTR_LEN
        self.v = (self.v & ~_CTR_MASK) | inc   # preserve high (BlkLen-CtrLen) bits
        self.v &= _BLK_MASK

    # -- ctr_drbg_update ------------------------------------------------------
    def _update(self, provided_data: int) -> None:
        provided_data &= _SEED_MASK
        temp = 0
        for _ in range(SEED_LEN // BLOCK_LEN):       # 3 iterations
            self._v_increment()
            output_block = self._block_encrypt(self.key, self.v)
            # SV: temp = {temp, output_block}  -> MSB-first concatenation
            temp = ((temp << BLOCK_LEN) | output_block) & _SEED_MASK
        temp ^= provided_data
        self.key = (temp >> BLOCK_LEN) & ((1 << KEY_LEN) - 1)   # temp[SEED_LEN-1 : BLOCK_LEN]
        self.v = temp & _BLK_MASK                               # temp[BLOCK_LEN-1 : 0]

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
    # boundary from the RTL's own gen_last, exactly as the upstream SV
    # scoreboard does (ctr_drbg_generate_one + gen_last -> ctr_drbg_generate_done).
    # Assuming a fixed glen instead desynchronises the whole chain the moment a
    # second Generate runs on one seed -- the normal case once every EDN
    # endpoint is live.
    def generate_one(self) -> int:
        """One 128b Generate output block. No trailing Update -- see generate_done()."""
        self._v_increment()
        return self._block_encrypt(self.key, self.v)

    def generate_done(self, additional_input: int = 0) -> None:
        """Finalize a Generate command: the single trailing Update."""
        self._update(additional_input & _SEED_MASK)
        self.reseed_counter += 1

    # Reference-model API kept for golden parity; not invoked by the OSS checkers.
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
    key = 0x000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f
    pt = 0x00112233445566778899aabbccddeeff
    expected_ct = 0x8ea2b7ca516745bfeafc49904b496089
    got = _aes_ecb_encrypt_int(key, 256, pt)
    assert got == expected_ct, f"AES-256 KAT FAIL: got {got:032x} expected {expected_ct:032x}"

    # FIPS-197 AES-128 KAT (exercises the 128-bit key schedule path too).
    key128 = 0x000102030405060708090a0b0c0d0e0f
    expected128 = 0x69c4e0d86a7b0430d8cdb78070b4c55a
    got128 = _aes_ecb_encrypt_int(key128, 128, pt)
    assert got128 == expected128, f"AES-128 KAT FAIL: got {got128:032x}"

    # FIPS-197 AES-192 KAT (exercises the 192-bit key schedule path).
    key192 = 0x000102030405060708090a0b0c0d0e0f1011121314151617
    expected192 = 0xdda97ca4864cdfe06eaf70a0ec0d7191
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
    entropy = 0xdf5d73faa468649edda33b5cca79b0b05600419ccb7a879ddfec9db32ee494e5531b51de16a30f769262474c73bec010
    expected_returned_bits = (
        0xd1c07cd95af8a7f11012c84ce48bb8cb87189e99d40fccb1771c619bdf82ab2280b1dc2f2581f39164f7ac0c510494b3a43c41b7db17514c87b107ae793e01c5
    )
    returned_bits_len_bits = 512
    num_blocks = returned_bits_len_bits // BLOCK_LEN  # 4 blocks of 128b

    drbg = SepCtrDrbgGolden()
    drbg.instantiate(entropy)
    drbg.generate(num_blocks)            # first generate -- discarded per CAVP
    blocks = drbg.generate(num_blocks)   # second generate -- the returned bits

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
