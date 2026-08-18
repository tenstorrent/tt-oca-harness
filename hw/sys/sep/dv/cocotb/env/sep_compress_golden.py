# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: (c) 2024-2026 Tenstorrent Inc. All Rights Reserved.
#
# sep_compress_golden.py
#
# Pure-Python golden model for the SEP DRBG entropy compression / conditioning
# datapath. Ported bit-exactly from the reference C DPI ground-truth models:
#
#   * BIW compressor (GF(2^8) multiply-add extractor):
#       dv/sep/tb/tb_uvm/common/dpi/drbg_compress_dpi.c
#       dv/sep/tb/tb_uvm/common/dpi/drbg_compress_dpi_pkg.sv
#     RTL cross-check: hw/ip/entropy_source/rtl/entropy_generator_complex.sv
#                      (g_biw generate loop, gf_muladd.sv)
#
#   * SHA-256 conditioner / whitener:
#       dv/sep/tb/tb_uvm/common/dpi/drbg_sha256_cond_dpi.c
#       dv/sep/tb/tb_uvm/common/dpi/drbg_sha256_cond_dpi_pkg.sv
#       dv/sep/tb/tb_uvm/common/dpi/sha256_dpi.c (the SHA-256 primitive)
#     RTL cross-check: hw/ip/entropy_source/rtl/entropy_sha256_whitener.sv
#
# The C is GROUND TRUTH. All ordering decisions below cite C line numbers.
#
# ----------------------------------------------------------------------------
# SHA-256 primitive: hashlib substituted (justification)
# ----------------------------------------------------------------------------
# sha256_dpi.c / the embedded transform in drbg_sha256_cond_dpi.c implement the
# textbook FIPS-180-4 SHA-256:
#   - identical IV (drbg_sha256_cond_dpi.c:99-102) and round constants K
#     (drbg_sha256_cond_dpi.c:35-52), which are the standard SHA-256 values;
#   - standard message schedule and round function (lines 68-93);
#   - standard padding: append 0x80, then zeros, then the 64-bit big-endian bit
#     length (lines 113-128);
#   - digest emitted big-endian, state[i] MSB-first (lines 130-136).
# This is byte-for-byte the FIPS-180-4 algorithm operating on a big-endian byte
# stream, so Python's stdlib `hashlib.sha256` over the SAME big-endian byte
# stream yields an identical digest. We therefore substitute hashlib for the
# core compression function. The Python class still performs the C's exact
# word->byte framing (drbg_sha256_cond_dpi.c:185-192) and digest->word framing
# (drbg_sha256_cond_dpi.c:131-136 / get_digest lines 217-222) so the boundaries
# remain bit-exact. The self-test additionally re-derives the digest with a
# fully manual FIPS-180-4 transform to prove hashlib == the C primitive.
# ----------------------------------------------------------------------------

GF_POLY = 0x1B  # AES reduction polynomial; drbg_compress_dpi.c:29
N_LANES = 12    # drbg_compress_dpi.c:30


class SepBiwCompress:
    """BIW (Barak-Impagliazzo-Wigderson) extractor: 12 lane bytes -> 32-bit word.

    GF(2^8) multiply-add over the AES field, reduction value 0x1B
    (drbg_compress_dpi.c:29). Addition in GF(2^8) is XOR.

    Lane -> word mapping (drbg_compress_dpi.c:90-98, RTL
    entropy_generator_complex.sv:230-245):
        out[0] = (b[0] * b[4]) + b[8]   -> word[31:24]  (MSB)
        out[1] = (b[1] * b[5]) + b[9]   -> word[23:16]
        out[2] = (b[2] * b[6]) + b[10]  -> word[15:8]
        out[3] = (b[3] * b[7]) + b[11]  -> word[7:0]   (LSB)
    RTL packs {biw[0],biw[1],biw[2],biw[3]} with biw[0] as MSB (line 245),
    matching the C shift pattern out[0]<<24 ... out[3]<<0.
    """

    @staticmethod
    def gf256_mult(a, b):
        """GF(2^8) multiply a*b, shift-and-XOR. drbg_compress_dpi.c:37-52."""
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
        """y = (a*b) + c, addition = XOR. drbg_compress_dpi.c:58-60."""
        return (SepBiwCompress.gf256_mult(a, b) ^ (c & 0xFF)) & 0xFF

    @staticmethod
    def compress_from_lanes(lanes):
        """12 lane bytes -> 32-bit BIW word.

        `lanes` is an indexable sequence of 12 ints (lane0..lane11), matching
        drbg_compress_from_lanes (drbg_compress_dpi_pkg.sv:54-62) and
        drbg_compress_biw_bytes (drbg_compress_dpi.c:109-128).
        """
        if len(lanes) != N_LANES:
            raise ValueError("BIW compress requires exactly %d lane bytes, got %d"
                             % (N_LANES, len(lanes)))
        out0 = SepBiwCompress.gf256_muladd(lanes[0], lanes[4], lanes[8])
        out1 = SepBiwCompress.gf256_muladd(lanes[1], lanes[5], lanes[9])
        out2 = SepBiwCompress.gf256_muladd(lanes[2], lanes[6], lanes[10])
        out3 = SepBiwCompress.gf256_muladd(lanes[3], lanes[7], lanes[11])
        # Pack: out[0] is MSB. drbg_compress_dpi.c:122-125.
        return ((out0 << 24) | (out1 << 16) | (out2 << 8) | out3) & 0xFFFFFFFF

    @staticmethod
    def compress_from_packed(packed_96):
        """Unpack a 96-bit packed SV vector and compress.

        Matches drbg_compress_biw (drbg_compress_dpi.c:75-101): lane i lives in
        bits [i*8 +: 8], i.e. lane0 in [7:0] ... lane11 in [95:88] (lines 82-86).
        `packed_96` is a Python int holding the 96-bit value.
        """
        lanes = [(packed_96 >> (i * 8)) & 0xFF for i in range(N_LANES)]
        return SepBiwCompress.compress_from_lanes(lanes)


class SepSha256Conditioner:
    """SHA-256 entropy conditioner / whitener.

    Accumulates `block_words` 32-bit compressor words; when full, hashes the
    block and exposes the 256-bit digest as 8 x 32-bit words. Mirrors
    drbg_sha256_cond_dpi.c and RTL entropy_sha256_whitener.sv (16 words ->
    512-bit block -> 8 digest words).

    Word -> byte framing (drbg_sha256_cond_dpi.c:185-192): each accumulated
    32-bit word is serialized BIG-ENDIAN (w>>24, w>>16, w>>8, w) into the SHA
    input stream. This matches the RTL feeding word[31:24] first.

    SHA -> output-word framing: the 32-byte digest is grouped big-endian into
    8 words; digest[0..3] form word[0] (drbg_sha256_cond_dpi.c:131-136). The
    DPI get_digest packs word[0] into the MSB lane of the 256-bit vector
    (digest_out[7-i], lines 217-222); get_digest_words() below returns the
    same word[0..7] MSB-first list.
    """

    MAX_BLOCK_WORDS = 64  # drbg_sha256_cond_dpi.c:142

    def __init__(self, block_words=16):
        # drbg_cond_init: clamp to [1, MAX], default 16. lines 160-165.
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

        hashlib substituted for the C primitive (see module header). Returns
        32 bytes, big-endian, exactly as drbg_sha256_cond_dpi.c sha256_compute.
        """
        import hashlib
        return hashlib.sha256(data).digest()

    def reset(self):
        """drbg_cond_reset: clears state, keeps block_words. lines 238-242."""
        self.buf = []
        self.count = 0
        self.digest_bytes = bytes(32)
        self.output_valid = False
        self.total_blocks = 0

    def push_word(self, word):
        """Push one 32-bit compressor word. drbg_cond_push_word lines 173-201.

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
            # Word buffer -> big-endian byte array. lines 185-192.
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

        word[i] = big-endian pack of digest_bytes[i*4 .. i*4+3]
        (drbg_sha256_cond_dpi.c:131-136). The DPI get_digest stores word[0] in
        the most-significant 32-bit lane of the 256-bit SV vector (line 218,
        digest_out[7-i]); this list is in that same word[0]-first order.
        """
        d = self.digest_bytes
        return [((d[i * 4] << 24) | (d[i * 4 + 1] << 16) |
                 (d[i * 4 + 2] << 8) | d[i * 4 + 3]) & 0xFFFFFFFF
                for i in range(8)]

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

    Re-implements drbg_sha256_cond_dpi.c sha256_transform/sha256_compute in
    Python to PROVE hashlib == the C primitive over the same byte stream.
    """
    K = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5,
        0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
        0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
        0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
        0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
        0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
        0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
        0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
        0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
        0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
        0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
        0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5,
        0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
        0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
    ]
    M = 0xFFFFFFFF

    def rotr(x, n):
        return ((x >> n) | (x << (32 - n))) & M

    state = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
             0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]

    # Padding: 0x80, zeros, 64-bit big-endian bit length.
    bitlen = len(data) * 8
    msg = bytearray(data)
    msg.append(0x80)
    while len(msg) % 64 != 56:
        msg.append(0x00)
    msg += bitlen.to_bytes(8, "big")

    for off in range(0, len(msg), 64):
        block = msg[off:off + 64]
        W = [0] * 64
        for i in range(16):
            W[i] = ((block[i * 4] << 24) | (block[i * 4 + 1] << 16) |
                    (block[i * 4 + 2] << 8) | block[i * 4 + 3]) & M
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
    assert SepBiwCompress.gf256_mult(0x57, 0x13) == 0xFE, "GF 0x57*0x13 != 0xFE"
    assert SepBiwCompress.gf256_mult(0x57, 0x83) == 0xC1, "GF 0x57*0x83 != 0xC1"
    # Commutativity + identity sanity.
    assert SepBiwCompress.gf256_mult(0x13, 0x57) == 0xFE
    assert SepBiwCompress.gf256_mult(0x57, 0x01) == 0x57
    assert SepBiwCompress.gf256_mult(0x57, 0x00) == 0x00
    # 0x02 * x is the AES xtime; 0x80*0x02 = 0x1B (reduction visible).
    assert SepBiwCompress.gf256_mult(0x80, 0x02) == 0x1B

    # ---------------------------------------------------------------------
    # (2) BIW word assembly vs a hand-computed oracle re-implementing the C
    #     inline (drbg_compress_dpi.c:117-125).
    # ---------------------------------------------------------------------
    def oracle(lanes):
        def mul(a, b):
            a &= 0xFF; b &= 0xFF; p = 0
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
        got = SepBiwCompress.compress_from_lanes(lanes)
        exp = oracle(lanes)
        assert got == exp, ("BIW mismatch lanes=%s got=%08x exp=%08x"
                            % (lanes, got, exp))
    # Hand-checked single byte: out[0] = 0x57*0x57 + 0x00.
    # 0x57*0x57 in GF(2^8) = 0xA5 (AES field, reduction 0x1B). lanes feed
    # group0 = (b0,b4,b8), so the MSB byte of the word must be 0xA5.
    hl = [0x57, 0, 0, 0, 0x57, 0, 0, 0, 0x00, 0, 0, 0]
    assert SepBiwCompress.gf256_mult(0x57, 0x57) == 0xA5
    assert (SepBiwCompress.compress_from_lanes(hl) >> 24) == 0xA5

    # Packed-vector unpack must agree with the lane list (lane0 in [7:0]).
    lanes = test_lanes[1]
    packed = 0
    for i in range(12):
        packed |= lanes[i] << (i * 8)
    assert SepBiwCompress.compress_from_packed(packed) == \
        SepBiwCompress.compress_from_lanes(lanes), "packed unpack mismatch"

    # ---------------------------------------------------------------------
    # (3) SHA-256 conditioner: feed a known 16-word block and assert the
    #     digest equals an independently-computed expected value.
    # ---------------------------------------------------------------------
    cond = SepSha256Conditioner(16)
    block_words = [0x00010203, 0x04050607, 0x08090A0B, 0x0C0D0E0F,
                   0x10111213, 0x14151617, 0x18191A1B, 0x1C1D1E1F,
                   0x20212223, 0x24252627, 0x28292A2B, 0x2C2D2E2F,
                   0x30313233, 0x34353637, 0x38393A3B, 0x3C3D3E3F]
    produced = False
    for idx, w in enumerate(block_words):
        produced = cond.push_word(w)
        if idx < 15:
            assert not produced, "digest produced early at word %d" % idx
            assert cond.pending_count == idx + 1
    assert produced, "no digest after 16th word"
    assert cond.total_blocks == 1
    assert cond.pending_count == 0

    # Independent expected: big-endian serialize the 16 words (cond.c:185-192),
    # then SHA-256. This is bytes 0x00..0x3F.
    expected_stream = bytes(range(0x00, 0x40))
    # Build the same stream via the documented word->byte framing.
    framed = bytearray()
    for w in block_words:
        framed += w.to_bytes(4, "big")
    assert bytes(framed) == expected_stream, "word->byte framing wrong"

    # Prove hashlib (used inside the conditioner) == the manual C primitive.
    import hashlib
    manual = _manual_sha256(expected_stream)
    lib = hashlib.sha256(expected_stream).digest()
    assert manual == lib, "manual FIPS-180-4 != hashlib (substitution unsafe)"

    # The conditioner digest must match both.
    assert cond.get_digest_bytes() == lib, "conditioner digest != expected"

    # Word framing of the output (cond.c:131-136 / get_digest:217-222).
    exp_words = [int.from_bytes(lib[i * 4:i * 4 + 4], "big") for i in range(8)]
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
