# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seed plan, fault-source table and frame model of ``sep_km_fault_inject_rand_test``.

No cocotb import, so the plan draws and checks without a simulator.

Fault sources. The IRQ_STATUS bit of each KMCSR source comes from the generated
``km_csr.h`` (the RDL). The report code of each source and the dispatch order
come from ``hw/ip/key_manager/doc/firmware.adoc``, sections "0xFF -
RESP_UNRECOVERABLE_FAULT" (the code table) and "Interrupt Priority" (the
order). The code of a set of sources is the code of the first source of the set
in that order. The payload of a fault frame is the signed 8-bit code
sign-extended to 32 bits.

Destinations. DEST_VALID bit i is bank i in the order HMAC, KMAC, AES, OTBN,
ABR ML-DSA seed, ML-KEM seed D, ML-KEM seed Z, ML-KEM message
(``firmware.adoc``, "0x24 - CMD_KEY_TRANSFER"). The share width is 8 words and
12 words for OTBN (``hw/sys/sep/doc/crypto.adoc``, "Key Manager Key Delivery").

Seed plan. ``draw_plan`` turns one ``SepSeededRng`` into every value the leaf
draws, ``check_plan`` checks the draw rules of the contract, and ``draw_lines``
gives the ``DRAW`` lines that the leaf logs.
"""

from __future__ import annotations

from dataclasses import dataclass

from env import sep_km_img_h as imgh
from env.sep_seeded_rng import SepSeededRng
from sep_reg_meta import CHeaderRegBlock, ip_c_header

WORD = 0xFFFF_FFFF

# --- fault sources ------------------------------------------------------------

_KM_CSR = CHeaderRegBlock("KM_CSR", ip_c_header("key_manager").with_name("km_csr.h"))
_IRQ_FIELDS = _KM_CSR.fields("IRQ_STATUS_REG")

# firmware.adoc, "Interrupt Priority": the KMCSR fatal sources from wipe state
# to ROM access violation, highest first. OTP change is not a fatal source and
# the boot sequence does not enable it, so it is not drawn.
ORDER = (
    "wipe_state",
    "rom_parity",
    "sram_parity",
    "rom_write",
    "sram_write_lock",
    "axi_decerr",
    "drbg_err",
    "axi_slverr",
    "otp_sigint",
    "exec",
    "rom_access",
)
_FIELD = {
    "wipe_state": "WIPE_STATE",
    "rom_parity": "ROM_PARITY_ERR",
    "sram_parity": "SRAM_PARITY_ERR",
    "rom_write": "ROM_WRITE_ERR",
    "sram_write_lock": "SRAM_WRITE_LOCK_ERR",
    "axi_decerr": "AXI_DECERR",
    "drbg_err": "DRBG_ERR",
    "axi_slverr": "AXI_SLVERR",
    "otp_sigint": "OTP_SIGINT",
    "exec": "EXEC_VIOLATION",
    "rom_access": "ROM_ACCESS_VIOLATION",
}
# km_csr.h: IRQ_STATUS bit of each source (the HK-IRQSET mask bit).
IRQ_BIT = {name: int(_IRQ_FIELDS[field]["bp"]) for name, field in _FIELD.items()}
# firmware.adoc, unrecoverable-fault code table.
CODE = {
    "wipe_state": -1,
    "rom_parity": -2,
    "sram_parity": -3,
    "rom_write": -4,
    "sram_write_lock": -5,
    "axi_decerr": -6,
    "axi_slverr": -7,
    "drbg_err": -8,
    "otp_sigint": -13,
    "exec": -17,
    "rom_access": -18,
}
CODE_ILLEGAL_INSN = -9
CODE_BUS_ERROR = -10
CODE_EBREAK = -11
CODE_FW_CRC = -14
# firmware.adoc, recoverable-fault code table.
CODE_KEY_SLOT_CRC = -1

# The contract draw pools.
SINGLE_POOL = ORDER[1:]  # the 10 single-source points
WINNER_POOL = tuple(n for n in ORDER if n not in ("drbg_err", "rom_access"))  # 9 winners
FORCED_DRBG_SET = ("drbg_err", "axi_slverr")
FORCED_DECERR_SET = ("axi_decerr", "axi_slverr")
N_SINGLE = 3
N_MULTI_DRAWN = 2
N_PARITY = 3

# HK-CPUIRQ: km_cpuirq_lines_i bit 0 drives PicoRV32 line 1, bit 1 line 2.
CPU_LINE_MASK = {1: 0b01, 2: 0b10}
CPU_LINE_CODE = {1: CODE_ILLEGAL_INSN, 2: CODE_BUS_ERROR}

PAR_N_MAX = 200  # HK-PAR read index N is drawn from [1, PAR_N_MAX]

# Memories of HK-PAR (km_par_mem_i) and their IRQ_STATUS parity bit.
MEM_ROM, MEM_SRAM = 0, 1
MEM_NAME = {MEM_ROM: "rom", MEM_SRAM: "sram"}
MEM_SOURCE = {MEM_ROM: "rom_parity", MEM_SRAM: "sram_parity"}

# architecture.adoc, "Parameters": the SRAM has 8192 words. firmware.adoc,
# "Error Recovery": one Weyl pass and two xoshiro128++ passes.
SRAM_WORDS = 8192
SRAM_FULL_EXTENT = 3 * SRAM_WORDS


def fault_word(code: int) -> int:
    """The payload word of a fault frame: the code sign-extended to 32 bits."""
    return code & WORD


def set_mask(names) -> int:
    """The HK-IRQSET / IRQ_STATUS mask of a set of sources."""
    m = 0
    for n in names:
        m |= 1 << IRQ_BIT[n]
    return m


def first_source(names) -> str:
    """The source of a set that the dispatch order serves first."""
    return min(names, key=ORDER.index)


def expected_code(names) -> int:
    return CODE[first_source(names)]


# --- destinations -------------------------------------------------------------

HMAC, KMAC, AES, OTBN, MLDSA, SEED_D, SEED_Z, MSG = range(8)
BANK_NAME = ("hmac", "kmac", "aes", "otbn", "mldsa", "seed_d", "seed_z", "msg")
WIDTH = {HMAC: 8, KMAC: 8, AES: 8, OTBN: 12, MLDSA: 8, SEED_D: 8, SEED_Z: 8, MSG: 8}
ALL_BANKS = 0xFF
FORCED_V = (1 << HMAC) | (1 << AES) | (1 << MSG)
OPTIONAL_V = (KMAC, OTBN, MLDSA, SEED_D, SEED_Z)
MAX_KEY_WORDS = 128
SLOT_WORDS = 16

# The HMAC witness software key. Every drawn key differs from it in its
# leading 8 words, so the "key" and "no key" goldens differ.
HMAC_SW_KEY = (
    0x5EC0DE01,
    0x5EC0DE02,
    0x5EC0DE03,
    0x5EC0DE04,
    0x5EC0DE05,
    0x5EC0DE06,
    0x5EC0DE07,
    0x5EC0DE08,
)


def slots_of(words: int) -> int:
    return (words + SLOT_WORDS - 1) // SLOT_WORDS


def _key(rng: SepSeededRng, n: int) -> tuple[int, ...]:
    """Non-zero words; the leading 8 pairwise different and not the HMAC SW key."""
    while True:
        words = tuple(rng.randrange(1, 1 << 32) for _ in range(n))
        lead = words[:8]
        if len(set(lead)) == len(lead) and lead != HMAC_SW_KEY[: len(lead)]:
            return words


def _mask(bits) -> int:
    m = 0
    for b in bits:
        m |= 1 << b
    return m


def _bits(mask: int) -> list[int]:
    return [b for b in range(8) if (mask >> b) & 1]


# --- seed plan ----------------------------------------------------------------


@dataclass(frozen=True)
class PreKey:
    words: tuple[int, ...]
    dest: int  # DEST_VALID and the transfer mask


@dataclass(frozen=True)
class Plan:
    seed: int
    # Precondition of every fatal point with keys (RAND-REP).
    v: int
    keys: tuple[PreKey, ...]  # keys[0]: 8 words, DEST_VALID with bit 7, transferred last
    r: int
    wipe_w: int
    # HK-IRQSET points.
    singles: tuple[str, ...]
    multis: tuple[tuple[str, ...], ...]  # multis[0] is the forced {drbg_err, axi_slverr}
    # HK-PAR points: (memory, lane, N).
    parity: tuple[tuple[int, int, int], ...]
    # Key CRC leg.
    key_b: tuple[int, ...]
    key_a: tuple[int, ...]
    dest_a: int
    outside_a: int
    word_class: str
    flip_word: int
    flip_bit: int
    key_c: tuple[int, ...]
    residue_j: int
    residue_bit: int
    # CPU-line leg: the KMCSR source that shares the clock with line 2.
    cpu_src: str
    # Main-context fatal leg.
    main_image: tuple[int, ...]
    main_w: int
    main_bit: int
    # Latency leg (RANDCFG).
    lat_fixed: int
    lat_seed: int

    @property
    def max_parity_n(self) -> int:
        return max(n for _m, _l, n in self.parity)

    def transfer_order(self) -> tuple[PreKey, ...]:
        """Keys 1..k-1 first, key 0 last, so every bank of V holds key 0 at the end."""
        return (*self.keys[1:], self.keys[0])

    def main_stream(self) -> tuple[list[int], int, int]:
        """The image frame with bit ``main_bit`` of word ``main_w`` flipped.

        Returns the frame, the original word and the flipped word.
        """
        frame = imgh.stream_words(self.main_image)
        orig = frame[self.main_w]
        frame[self.main_w] = orig ^ (1 << self.main_bit)
        return frame, orig, frame[self.main_w]


def _draw_multi(rng: SepSeededRng, winner: str) -> tuple[str, ...]:
    if winner == "axi_decerr":
        return FORCED_DECERR_SET
    below = ORDER[ORDER.index(winner) + 1 :]
    k = rng.randrange(1, min(3, len(below)) + 1)
    return (winner, *rng.sample(below, k))


def draw_plan(seed: int) -> Plan:
    rng = SepSeededRng(seed)
    # Precondition.
    v = FORCED_V | _mask(b for b in OPTIONAL_V if rng.getrandbits(1))
    k = rng.randrange(1, 5)
    if v & (1 << OTBN) and k == 1:
        # Key 0 has 8 words, below the OTBN share width, so a second key
        # (12 or more words) takes the OTBN bank.
        k = 2
    keys = [PreKey(_key(rng, 8), v & ~(1 << OTBN))]
    for i in range(1, k):
        if i == 1 and v & (1 << OTBN):
            sub = (1 << OTBN) | _mask(b for b in _bits(v) if b != OTBN and rng.getrandbits(1))
            size = rng.randrange(WIDTH[OTBN], MAX_KEY_WORDS + 1)
        else:
            cand = [b for b in _bits(v) if b != OTBN]
            sub = _mask(rng.sample(cand, rng.randrange(1, len(cand) + 1)))
            size = rng.randrange(8, MAX_KEY_WORDS + 1)
        keys.append(PreKey(_key(rng, size), sub))
    r = rng.randrange(1, 4)
    wipe_w = rng.randrange(8, 201)
    # HK-IRQSET points.
    singles = tuple(rng.sample(SINGLE_POOL, N_SINGLE))
    winners = rng.sample(WINNER_POOL, N_MULTI_DRAWN)
    multis = (FORCED_DRBG_SET, *(_draw_multi(rng, w) for w in winners))
    # HK-PAR points.
    cells = rng.sample([(m, lane) for m in (MEM_ROM, MEM_SRAM) for lane in range(4)], N_PARITY)
    parity = tuple((m, lane, rng.randrange(1, PAR_N_MAX + 1)) for m, lane in cells)
    # Key CRC leg.
    key_b = _key(rng, 4)
    size_a = rng.randrange(1, MAX_KEY_WORDS + 1)
    others = [b for b in range(8) if b != AES]
    dest_a = (1 << AES) | _mask(rng.sample(others, rng.randrange(0, len(others))))
    outside_a = 1 << rng.choice([b for b in range(8) if not (dest_a >> b) & 1])
    key_a = _key(rng, size_a)
    word_class = rng.choice(("first", "middle", "last"))
    flip_word = {"first": 0, "middle": size_a // 2, "last": size_a - 1}[word_class]
    flip_bit = rng.choice((0, 31))
    while True:
        size_c = rng.randrange(1, MAX_KEY_WORDS + 1)
        if size_c % SLOT_WORDS:
            break
    key_c = _key(rng, size_c)
    residue_j = rng.randrange(size_c % SLOT_WORDS, SLOT_WORDS)
    residue_bit = rng.randrange(0, 32)
    # CPU-line leg.
    cpu_src = rng.choice(ORDER)
    # Main-context leg.
    n = rng.randrange(8, 65)
    main_image = tuple(imgh.spin_image(n, rng))
    main_w = rng.randrange(0, n + 1)  # n is the CRC-32C trailer
    main_bit = rng.randrange(0, 32)
    # Latency leg.
    lat_fixed = rng.randrange(2, 9)
    lat_seed = rng.getrandbits(32)
    return Plan(
        seed=seed,
        v=v,
        keys=tuple(keys),
        r=r,
        wipe_w=wipe_w,
        singles=singles,
        multis=multis,
        parity=parity,
        key_b=key_b,
        key_a=key_a,
        dest_a=dest_a,
        outside_a=outside_a,
        word_class=word_class,
        flip_word=flip_word,
        flip_bit=flip_bit,
        key_c=key_c,
        residue_j=residue_j,
        residue_bit=residue_bit,
        cpu_src=cpu_src,
        main_image=main_image,
        main_w=main_w,
        main_bit=main_bit,
        lat_fixed=lat_fixed,
        lat_seed=lat_seed,
    )


class LatStream:
    """The per-access latency stream of the RANDCFG leg: 1 to 8, each at least once.

    The first eight values are a seeded permutation of 1 to 8, then each value
    is drawn in [1, 8]. A pure function of the plan seed.
    """

    def __init__(self, lat_seed: int) -> None:
        self._rng = SepSeededRng(lat_seed)
        self._head = list(range(1, 9))
        self._rng.shuffle(self._head)

    def next(self) -> int:
        if self._head:
            return self._head.pop(0)
        return self._rng.randrange(1, 9)


def check_plan(p: Plan) -> None:
    """The draw rules of the contract. A violation is a test construction error."""
    errs: list[str] = []
    if p.v & FORCED_V != FORCED_V:
        errs.append("V lacks HMAC, AES or the ML-KEM message bank")
    if not 1 <= len(p.keys) <= 4:
        errs.append("k outside [1, 4]")
    k0 = p.keys[0]
    if len(k0.words) != 8 or not k0.dest & (1 << MSG):
        errs.append("key 0 is not 8 words with DEST_VALID bit 7")
    covered = 0
    for key in p.keys:
        covered |= key.dest
        if key.dest & ~p.v or not key.dest:
            errs.append(f"key mask 0x{key.dest:02x} outside V 0x{p.v:02x}")
        if any(len(key.words) < WIDTH[b] for b in _bits(key.dest)):
            errs.append(f"key of {len(key.words)} words below the width of its mask")
        if any(w == 0 for w in key.words):
            errs.append("a zero key word")
    if covered != p.v:
        errs.append("the keys do not cover V")
    if not 1 <= p.r <= 3 or not 8 <= p.wipe_w <= 200:
        errs.append("r or W outside its range")
    if len(set(p.singles)) != N_SINGLE or any(s not in SINGLE_POOL for s in p.singles):
        errs.append("single-source points")
    if p.multis[0] != FORCED_DRBG_SET:
        errs.append("the forced {drbg_err, axi_slverr} set is not the first multi point")
    winners = [m[0] for m in p.multis[1:]]
    if len(set(winners)) != N_MULTI_DRAWN or any(w not in WINNER_POOL for w in winners):
        errs.append("drawn winners")
    for m in p.multis:
        below = ORDER[ORDER.index(m[0]) + 1 :]
        if len(set(m)) != len(m) or not 2 <= len(m) <= 4 or any(x not in below for x in m[1:]):
            errs.append(f"set {m}")
        if m[0] == "axi_decerr" and m != FORCED_DECERR_SET:
            errs.append("the winner axi_decerr is not the forced set")
        if first_source(m) != m[0]:
            errs.append(f"winner of {m}")
    if len({(m, lane) for m, lane, _n in p.parity}) != N_PARITY:
        errs.append("parity points repeat")
    if any(not 1 <= n <= PAR_N_MAX for _m, _l, n in p.parity):
        errs.append("parity N outside [1, 200]")
    if len(p.key_b) != 4 or not p.dest_a & (1 << AES) or p.dest_a == ALL_BANKS:
        errs.append("key B or DEST_VALID of key A")
    if p.outside_a & p.dest_a or bin(p.outside_a).count("1") != 1:
        errs.append("the outside destination of key A")
    if not 0 <= p.flip_word < len(p.key_a) or p.flip_bit not in (0, 31):
        errs.append("the key CRC flip")
    if len(p.key_c) % SLOT_WORDS == 0 or not len(p.key_c) % SLOT_WORDS <= p.residue_j < 16:
        errs.append("the residue flip")
    if p.cpu_src not in ORDER:
        errs.append("the CPU-line KMCSR source")
    if not 8 <= len(p.main_image) <= 64 or not 0 <= p.main_w <= len(p.main_image):
        errs.append("the main-context image")
    if not 2 <= p.lat_fixed <= 8:
        errs.append("the fixed latency")
    if errs:
        raise AssertionError("plan rule broken: " + "; ".join(errs))


def draw_lines(p: Plan) -> list[str]:
    def hx(ws) -> str:
        return ",".join(f"0x{w:08x}" for w in ws)

    lines = [
        f"DRAW v=0x{p.v:02x} k={len(p.keys)} r={p.r} wipe_w={p.wipe_w}",
    ]
    for i, key in enumerate(p.keys):
        lines.append(
            f"DRAW key{i} size={len(key.words)} dest=0x{key.dest:02x} words={hx(key.words)}"
        )
    lines.append("DRAW singles=" + ",".join(p.singles))
    for i, m in enumerate(p.multis):
        lines.append(f"DRAW multi{i} set={','.join(m)} mask=0x{set_mask(m):03x}")
    for i, (m, lane, n) in enumerate(p.parity):
        lines.append(f"DRAW parity{i} mem={MEM_NAME[m]} lane={lane} n={n}")
    lines += [
        f"DRAW key_b size=4 words={hx(p.key_b)}",
        f"DRAW key_a size={len(p.key_a)} dest=0x{p.dest_a:02x} outside=0x{p.outside_a:02x} "
        f"words={hx(p.key_a)}",
        f"DRAW key_crc word_class={p.word_class} word={p.flip_word} bit={p.flip_bit}",
        f"DRAW key_c size={len(p.key_c)} residue_j={p.residue_j} bit={p.residue_bit} "
        f"words={hx(p.key_c)}",
        f"DRAW cpu_src={p.cpu_src}",
        f"DRAW main n={len(p.main_image)} w={p.main_w} bit={p.main_bit} image={hx(p.main_image)}",
        f"DRAW lat_fixed={p.lat_fixed} lat_seed=0x{p.lat_seed:08x}",
    ]
    return lines


# --- frame model of the latency leg ------------------------------------------------

RESP_CMD = 0x00
RESP_KM_READY = 0x55
CMD_STAT = 0x03
CMD_KEY_REVOKE = 0x23
CMD_KEY_TRANSFER = 0x24
CMD_ENGINE_SHRED = 0x25
CMD_KEY_LOAD = 0x26
LAT_KEY_DEST = 1 << AES
LAT_FIRST_HANDLE = 1  # firmware.adoc, "Key Management": handles 1 to 255 in order


def _signed8(v: int) -> int:
    v &= 0xFF
    return v - 256 if v >= 128 else v


def lat_frame_ok(idx: int, words: list[int]) -> bool:
    """Frame ``idx`` of the latency sequence against the stated frame fields.

    0 RESP_KM_READY (sequence 0, no payload); 1 CMD_STAT success with status 0;
    2 CMD_KEY_LOAD success with the first handle; 3 CMD_KEY_TRANSFER success with
    the handle and the AES mask; 4 CMD_KEY_REVOKE success with the handle;
    5 CMD_ENGINE_SHRED success with the AES mask. Command sequence numbers start
    at 0 after the boot, and the response sequence numbers follow the frames.
    """
    hdr = words[0]
    seq, rid, plen = hdr & 0xFF, (hdr >> 8) & 0xFF, (hdr >> 16) & 0xFF
    if seq != idx:
        return False
    if idx == 0:
        return rid == RESP_KM_READY and plen == 0 and len(words) == 1
    cmd = (CMD_STAT, CMD_KEY_LOAD, CMD_KEY_TRANSFER, CMD_KEY_REVOKE, CMD_ENGINE_SHRED)[idx - 1]
    if rid != RESP_CMD or plen != 4 or len(words) != 6:
        return False
    p = words[1:5]
    if (p[0] & 0xFF) != idx - 1 or (p[1] & 0xFF) != cmd or _signed8(p[2]) != 0:
        return False
    if p[0] >> 8 or p[1] >> 8 or p[2] >> 8:
        return False
    arg = p[3]
    if cmd == CMD_STAT:
        return arg == 0
    if cmd == CMD_KEY_LOAD:
        return (arg & 0xFF) == LAT_FIRST_HANDLE
    if cmd == CMD_KEY_TRANSFER:
        return (arg & 0xFFFF) == (LAT_FIRST_HANDLE | (LAT_KEY_DEST << 8))
    if cmd == CMD_KEY_REVOKE:
        return (arg & 0xFF) == LAT_FIRST_HANDLE
    return (arg & 0xFF) == LAT_KEY_DEST
