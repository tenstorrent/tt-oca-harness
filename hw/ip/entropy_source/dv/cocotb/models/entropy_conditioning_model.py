# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2024-2026 Tenstorrent USA, Inc.
#
# Pure-Python golden model for entropy compression / conditioning
# datapath. The architecture is ``hw/ip/entropy_source/doc/architecture.adoc``:
# BIW compressor (GF(2^8) multiply-add) and SHA-256 conditioner.
#
# ----------------------------------------------------------------------------
# SHA-256 primitive
# ----------------------------------------------------------------------------
# The conditioner is FIPS 180-4 SHA-256 over a big-endian byte stream: the
# standard IV and round constants, the standard message schedule and round
# function, standard padding (0x80, zeros, 64-bit big-endian bit length) and a
# big-endian digest with state[i] MSB-first. `hashlib.sha256` over the SAME byte
# stream yields the identical digest and is the core compression function here;
# the class keeps the architecture.adoc word/byte framing, and the self-test
# re-derives the digest with a fully manual FIPS-180-4 transform.
# ----------------------------------------------------------------------------

GF_POLY = 0x1B  # AES reduction polynomial
N_LANES = 12
BIW_TRIPLES = ((0, 4, 8), (1, 5, 9), (2, 6, 10), (3, 7, 11))
BIW_OUT_SHIFTS = (24, 16, 8, 0)


class EntropyBiwModel:
    """BIW (Barak-Impagliazzo-Wigderson) extractor: 12 lane bytes -> 32-bit word.

    GF(2^8) multiply-add over the AES field with reduction value 0x1B.
    Addition in GF(2^8) is XOR.

    Lane-to-word mapping:
        out[i] = (b[i] * b[i+4]) + b[i+8], packed with out[0] as word MSB.
    """

    @staticmethod
    def gf256_mult(a, b):
        """GF(2^8) multiply a*b using shift-and-XOR."""
        a &= 0xFF
        b &= 0xFF
        p = 0
        for _ in range(8):
            if b & 1:
                p ^= a
            hi_bit = a & 0x80
            a = (a << 1) & 0xFF
            if hi_bit:
                a ^= GF_POLY
            b >>= 1
        return p & 0xFF

    @staticmethod
    def gf256_muladd(a, b, c):
        """Compute ``y = (a * b) + c``, where addition is XOR."""
        return (EntropyBiwModel.gf256_mult(a, b) ^ (c & 0xFF)) & 0xFF

    @staticmethod
    def compress_from_lanes(lanes):
        """12 lane bytes -> 32-bit BIW word.

        `lanes` is an indexable sequence of 12 ints (lane0..lane11).
        """
        if len(lanes) != N_LANES:
            raise ValueError(
                "BIW compress requires exactly %d lane bytes, got %d" % (N_LANES, len(lanes))
            )
        if len(BIW_TRIPLES) != len(BIW_OUT_SHIFTS):
            raise ValueError(
                "BIW_TRIPLES and BIW_OUT_SHIFTS length mismatch "
                f"({len(BIW_TRIPLES)} vs {len(BIW_OUT_SHIFTS)})"
            )
        word = 0
        for (a, b, c), shift in zip(BIW_TRIPLES, BIW_OUT_SHIFTS):
            word |= EntropyBiwModel.gf256_muladd(lanes[a], lanes[b], lanes[c]) << shift
        return word & 0xFFFFFFFF

    @staticmethod
    def compress_from_packed(packed_96):
        """Unpack a 96-bit packed SV vector and compress.

        Lane i lives in bits [i*8 +: 8], so lane0 occupies [7:0] and lane11
        occupies [95:88].
        `packed_96` is a Python int holding the 96-bit value.
        """
        lanes = [(packed_96 >> (i * 8)) & 0xFF for i in range(N_LANES)]
        return EntropyBiwModel.compress_from_lanes(lanes)


class EntropySha256Model:
    """SHA-256 entropy conditioner / whitener.

    Accumulates `block_words` 32-bit compressor words; when full, hashes the
    block and exposes the 256-bit digest as 8 x 32-bit words, matching
    the SHA-256 conditioner in ``hw/ip/entropy_source/doc/architecture.adoc``
    (16 words -> 512-bit block -> 8 digest words).

    Each accumulated 32-bit word is serialized BIG-ENDIAN
    (w>>24, w>>16, w>>8, w) into the SHA input stream. This matches the
    architecture.adoc conditioner framing (word MSB first).

    SHA -> output-word framing: the 32-byte digest is grouped big-endian into
    8 words; digest[0..3] form word[0]. get_digest_words() returns the same
    word[0..7] MSB-first list.
    """

    MAX_BLOCK_WORDS = 64

    def __init__(self, block_words=16):
        # Clamp to [1, MAX], defaulting to 16.
        if block_words <= 0 or block_words > self.MAX_BLOCK_WORDS:
            block_words = 16
        self.block_words = block_words
        self.buf = []
        self.count = 0
        self.digest_bytes = bytes(32)
        self.output_valid = False
        self.total_blocks = 0

    @staticmethod
    def _sha256(data):
        """FIPS-180-4 SHA-256 over a big-endian byte stream.

        Returns 32 big-endian bytes.
        """
        import hashlib

        return hashlib.sha256(data).digest()

    def reset(self):
        """Clear state while preserving block_words."""
        self.buf = []
        self.count = 0
        self.digest_bytes = bytes(32)
        self.output_valid = False
        self.total_blocks = 0

    def push_word(self, word):
        """Push one 32-bit compressor word.

        Returns True iff a digest was produced on this push.
        """
        word &= 0xFFFFFFFF
        self.output_valid = False

        if self.count < self.block_words:
            if len(self.buf) <= self.count:
                self.buf.append(word)
            else:
                self.buf[self.count] = word
            self.count += 1

        if self.count >= self.block_words:
            # Convert the word buffer to a big-endian byte array.
            data = bytearray()
            for i in range(self.block_words):
                w = self.buf[i] & 0xFFFFFFFF
                data.append((w >> 24) & 0xFF)
                data.append((w >> 16) & 0xFF)
                data.append((w >> 8) & 0xFF)
                data.append(w & 0xFF)
            self.digest_bytes = self._sha256(bytes(data))
            self.output_valid = True
            self.total_blocks += 1
            self.count = 0
            self.buf = []
        return self.output_valid

    def get_digest_bytes(self):
        """Latest 256-bit digest as 32 big-endian bytes (digest[0] is MSB)."""
        return self.digest_bytes

    def get_digest_words(self):
        """Latest digest as 8 x 32-bit words, MSB word first (word[0..7]).

        word[i] is the big-endian pack of digest_bytes[i*4 .. i*4+3].
        """
        d = self.digest_bytes
        return [
            ((d[i * 4] << 24) | (d[i * 4 + 1] << 16) | (d[i * 4 + 2] << 8) | d[i * 4 + 3])
            & 0xFFFFFFFF
            for i in range(8)
        ]

    def get_digest_int(self):
        """Latest digest as a single 256-bit int (word[0] most significant),
        matching the packed `bit [255:0]` returned by drbg_cond_get_digest."""
        words = self.get_digest_words()
        val = 0
        for w in words:  # word[0] first -> most significant
            val = (val << 32) | w
        return val

    @property
    def pending_count(self):
        return self.count


# ===========================================================================
# Self-test (plain python3, no simulator)
# ===========================================================================
def _manual_sha256(data):
    """Independent, fully-manual FIPS-180-4 SHA-256 (no hashlib).

    Used to cross-check hashlib over the same byte stream.
    """
    K = [
        0x428A2F98,
        0x71374491,
        0xB5C0FBCF,
        0xE9B5DBA5,
        0x3956C25B,
        0x59F111F1,
        0x923F82A4,
        0xAB1C5ED5,
        0xD807AA98,
        0x12835B01,
        0x243185BE,
        0x550C7DC3,
        0x72BE5D74,
        0x80DEB1FE,
        0x9BDC06A7,
        0xC19BF174,
        0xE49B69C1,
        0xEFBE4786,
        0x0FC19DC6,
        0x240CA1CC,
        0x2DE92C6F,
        0x4A7484AA,
        0x5CB0A9DC,
        0x76F988DA,
        0x983E5152,
        0xA831C66D,
        0xB00327C8,
        0xBF597FC7,
        0xC6E00BF3,
        0xD5A79147,
        0x06CA6351,
        0x14292967,
        0x27B70A85,
        0x2E1B2138,
        0x4D2C6DFC,
        0x53380D13,
        0x650A7354,
        0x766A0ABB,
        0x81C2C92E,
        0x92722C85,
        0xA2BFE8A1,
        0xA81A664B,
        0xC24B8B70,
        0xC76C51A3,
        0xD192E819,
        0xD6990624,
        0xF40E3585,
        0x106AA070,
        0x19A4C116,
        0x1E376C08,
        0x2748774C,
        0x34B0BCB5,
        0x391C0CB3,
        0x4ED8AA4A,
        0x5B9CCA4F,
        0x682E6FF3,
        0x748F82EE,
        0x78A5636F,
        0x84C87814,
        0x8CC70208,
        0x90BEFFFA,
        0xA4506CEB,
        0xBEF9A3F7,
        0xC67178F2,
    ]
    M = 0xFFFFFFFF

    def rotr(x, n):
        return ((x >> n) | (x << (32 - n))) & M

    state = [
        0x6A09E667,
        0xBB67AE85,
        0x3C6EF372,
        0xA54FF53A,
        0x510E527F,
        0x9B05688C,
        0x1F83D9AB,
        0x5BE0CD19,
    ]

    # Padding: 0x80, zeros, 64-bit big-endian bit length.
    bitlen = len(data) * 8
    msg = bytearray(data)
    msg.append(0x80)
    while len(msg) % 64 != 56:
        msg.append(0x00)
    msg += bitlen.to_bytes(8, "big")

    for off in range(0, len(msg), 64):
        block = msg[off : off + 64]
        W = [0] * 64
        for i in range(16):
            W[i] = (
                (block[i * 4] << 24)
                | (block[i * 4 + 1] << 16)
                | (block[i * 4 + 2] << 8)
                | block[i * 4 + 3]
            ) & M
        for i in range(16, 64):
            s0 = rotr(W[i - 15], 7) ^ rotr(W[i - 15], 18) ^ (W[i - 15] >> 3)
            s1 = rotr(W[i - 2], 17) ^ rotr(W[i - 2], 19) ^ (W[i - 2] >> 10)
            W[i] = (W[i - 16] + s0 + W[i - 7] + s1) & M
        a, b, c, d, e, f, g, h = state
        for i in range(64):
            ep1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)
            ch = (e & f) ^ (~e & g)
            t1 = (h + ep1 + ch + K[i] + W[i]) & M
            ep0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)
            maj = (a & b) ^ (a & c) ^ (b & c)
            t2 = (ep0 + maj) & M
            h, g, f, e, d, c, b, a = g, f, e, (d + t1) & M, c, b, a, (t1 + t2) & M
        state = [(state[i] + v) & M for i, v in enumerate((a, b, c, d, e, f, g, h))]

    out = bytearray()
    for s in state:
        out += s.to_bytes(4, "big")
    return bytes(out)


def _selftest():
    # ---------------------------------------------------------------------
    # (1) GF(2^8) multiply KAT vs known Rijndael values.
    # 0x57 * 0x13 = 0xFE, 0x57 * 0x83 = 0xC1 in GF(2^8) (AES field).
    # ---------------------------------------------------------------------
    assert EntropyBiwModel.gf256_mult(0x57, 0x13) == 0xFE, "GF 0x57*0x13 != 0xFE"
    assert EntropyBiwModel.gf256_mult(0x57, 0x83) == 0xC1, "GF 0x57*0x83 != 0xC1"
    # Commutativity + identity sanity.
    assert EntropyBiwModel.gf256_mult(0x13, 0x57) == 0xFE
    assert EntropyBiwModel.gf256_mult(0x57, 0x01) == 0x57
    assert EntropyBiwModel.gf256_mult(0x57, 0x00) == 0x00
    # 0x02 * x is the AES xtime; 0x80*0x02 = 0x1B (reduction visible).
    assert EntropyBiwModel.gf256_mult(0x80, 0x02) == 0x1B

    # ---------------------------------------------------------------------
    # (2) BIW word assembly vs an independent hand-computed oracle.
    # ---------------------------------------------------------------------
    def oracle(lanes):
        def mul(a, b):
            a &= 0xFF
            b &= 0xFF
            p = 0
            for _ in range(8):
                if b & 1:
                    p ^= a
                hi = a & 0x80
                a = (a << 1) & 0xFF
                if hi:
                    a ^= 0x1B
                b >>= 1
            return p

        o0 = mul(lanes[0], lanes[4]) ^ lanes[8]
        o1 = mul(lanes[1], lanes[5]) ^ lanes[9]
        o2 = mul(lanes[2], lanes[6]) ^ lanes[10]
        o3 = mul(lanes[3], lanes[7]) ^ lanes[11]
        return ((o0 << 24) | (o1 << 16) | (o2 << 8) | o3) & 0xFFFFFFFF

    test_lanes = [
        [0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0C],
        [0x57, 0x13, 0x83, 0xFF, 0x57, 0x83, 0x13, 0x00, 0xAB, 0xCD, 0xEF, 0x12],
        [0xFF] * 12,
        [0x00] * 12,
        list(range(0x10, 0x10 + 12)),
    ]
    for lanes in test_lanes:
        got = EntropyBiwModel.compress_from_lanes(lanes)
        exp = oracle(lanes)
        assert got == exp, "BIW mismatch lanes=%s got=%08x exp=%08x" % (lanes, got, exp)
    # Hand-checked single byte: out[0] = 0x57*0x57 + 0x00.
    # 0x57*0x57 in GF(2^8) = 0xA5 (AES field, reduction 0x1B). lanes feed
    # group0 = (b0,b4,b8), so the MSB byte of the word must be 0xA5.
    hl = [0x57, 0, 0, 0, 0x57, 0, 0, 0, 0x00, 0, 0, 0]
    assert EntropyBiwModel.gf256_mult(0x57, 0x57) == 0xA5
    assert (EntropyBiwModel.compress_from_lanes(hl) >> 24) == 0xA5

    # Packed-vector unpack must agree with the lane list (lane0 in [7:0]).
    lanes = test_lanes[1]
    packed = 0
    for i in range(12):
        packed |= lanes[i] << (i * 8)
    assert EntropyBiwModel.compress_from_packed(packed) == EntropyBiwModel.compress_from_lanes(
        lanes
    ), "packed unpack mismatch"

    # ---------------------------------------------------------------------
    # (3) SHA-256 conditioner: feed a known 16-word block and assert the
    #     digest equals an independently-computed expected value.
    # ---------------------------------------------------------------------
    cond = EntropySha256Model(16)
    block_words = [
        0x00010203,
        0x04050607,
        0x08090A0B,
        0x0C0D0E0F,
        0x10111213,
        0x14151617,
        0x18191A1B,
        0x1C1D1E1F,
        0x20212223,
        0x24252627,
        0x28292A2B,
        0x2C2D2E2F,
        0x30313233,
        0x34353637,
        0x38393A3B,
        0x3C3D3E3F,
    ]
    produced = False
    for idx, w in enumerate(block_words):
        produced = cond.push_word(w)
        if idx < 15:
            assert not produced, "digest produced early at word %d" % idx
            assert cond.pending_count == idx + 1
    assert produced, "no digest after 16th word"
    assert cond.total_blocks == 1
    assert cond.pending_count == 0

    # Independent expected: big-endian serialize the 16 words,
    # then SHA-256. This is bytes 0x00..0x3F.
    expected_stream = bytes(range(0x00, 0x40))
    # Build the same stream via the documented word->byte framing.
    framed = bytearray()
    for w in block_words:
        framed += w.to_bytes(4, "big")
    assert bytes(framed) == expected_stream, "word->byte framing wrong"

    # Prove hashlib (used inside the conditioner) == the manual FIPS-180-4 transform.
    import hashlib

    manual = _manual_sha256(expected_stream)
    lib = hashlib.sha256(expected_stream).digest()
    assert manual == lib, "manual FIPS-180-4 != hashlib (substitution unsafe)"

    # The conditioner digest must match both.
    assert cond.get_digest_bytes() == lib, "conditioner digest != expected"

    # Word framing of the output: 8 big-endian words, word[0] most significant.
    exp_words = [int.from_bytes(lib[i * 4 : i * 4 + 4], "big") for i in range(8)]
    assert cond.get_digest_words() == exp_words, "digest word framing wrong"

    # 256-bit packed int: word[0] is most significant.
    exp_int = int.from_bytes(lib, "big")
    assert cond.get_digest_int() == exp_int, "digest int packing wrong"

    # Multi-block + reset behavior.
    cond.reset()
    assert cond.total_blocks == 0 and cond.pending_count == 0
    for w in block_words:
        cond.push_word(w)
    for w in block_words:
        cond.push_word(w)
    assert cond.total_blocks == 2, "second block not counted"

    print("COMPRESS GOLDEN SELFTEST PASS")


if __name__ == "__main__":
    _selftest()
