# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seed plan, register facts and graders of ``sep_km_handover_rand_test``.

No cocotb import, so the model loads without a simulator.

Register facts. Every KM address and field mask comes from the generated
register header of the Key Manager RDL
(``hw/ip/key_manager/regs/gen/py/key_manager_reg.py`` and the generated C
headers in ``hw/ip/key_manager/regs/gen/c``). The values that the RDL cannot
give are spec values with their source next to them.

Seed plan. ``draw_plan`` turns one ``SepSeededRng`` into every value the leaf
uses and returns the ``DRAW`` lines that the leaf logs.

Graders. Each ``grade_*`` function takes the decoded IMG-H report (or the
recorded bus writes) and the expectation of the pass, and returns the verdict
and the fields of the ``CHK-<NAME>`` line. The functions read DUT values only
from their arguments, so the leaf calls them with what the DUT returned.
"""

from __future__ import annotations

import importlib.util
import re
from dataclasses import dataclass
from pathlib import Path

from env import sep_km_img_h as imgh
from env.sep_seeded_rng import SepSeededRng

TEST = "sep_km_handover_rand_test"
WORD = 0xFFFF_FFFF

_GEN = Path(__file__).resolve().parents[6] / "ip" / "key_manager" / "regs" / "gen"


def _load_km_reg():
    path = _GEN / "py" / "key_manager_reg.py"
    spec = importlib.util.spec_from_file_location("key_manager_reg", path)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


KM = _load_km_reg()


def _bm(header: str, name: str) -> int:
    """A ``#define <name> <value>`` of a generated C header."""
    for line in (_GEN / "c" / header).read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "#define" and parts[1] == name:
            return int(parts[2], 0)
    raise KeyError(f"{name} not found in {header}")


# --- KMCSR and mailbox fields (km_csr.adoc, km_mailbox_km.adoc) --------------
IRQ_STATUS_DEFINED = WORD & ~_bm("km_csr.h", "KM_CSR__IRQ_STATUS_REG__RSVD_bm")
EXEC_MODE_ENABLE = _bm("km_csr.h", "KM_CSR__SRAM_EXEC_MODE_REG__ENABLE_bm")
ENTRY_LOCK = _bm("km_csr.h", "KM_CSR__IRQ_ENTRY_LOCK_REG__LOCK_bm")
ENTRY_ADDR_RESET = _bm("km_csr.h", "KM_CSR__IRQ_ENTRY_ADDR_REG__ADDR_reset")
_OTP = "KM_CSR__OTP_READ_LOCK_REG__"
OTP_LIFE_CYCLE = _bm("km_csr.h", f"{_OTP}LIFE_CYCLE_bm")
OTP_DEMOTION = _bm("km_csr.h", f"{_OTP}DEMOTION_bm")
OTP_SECRET = (
    _bm("km_csr.h", f"{_OTP}CHIPLET_UID_bm")
    | _bm("km_csr.h", f"{_OTP}SIP_UID_bm")
    | _bm("km_csr.h", f"{_OTP}SYS_UID_bm")
    | _bm("km_csr.h", f"{_OTP}CLASS_KEY_bm")
)
OTP_PUBLIC = (
    _bm("km_csr.h", f"{_OTP}SEP_CHIPLET_ID_bm")
    | _bm("km_csr.h", f"{_OTP}SEP_SIP_ID_bm")
    | _bm("km_csr.h", f"{_OTP}SEP_SYS_ID_bm")
)
OTP_SECRET_LSB = (OTP_SECRET & -OTP_SECRET).bit_length() - 1
OTP_PUBLIC_LSB = (OTP_PUBLIC & -OTP_PUBLIC).bit_length() - 1

# The KEY_CTRL key_valid bit of each IMG-H KEY_CTRL word, in the report order
# (DEST_VALID bit order, then the ML-KEM shared key).
_KEY_VALID_BM = {
    "hmac": _bm("hmac_wrapper_key.h", "HMAC_WRAPPER_KEY__KEY_CTRL_REG__KEY_VALID_bm"),
    "kmac": _bm("kmac_wrapper_key.h", "KMAC_WRAPPER_KEY__KEY_CTRL_REG__KEY_VALID_bm"),
    "aes": _bm("aes_wrapper_key.h", "AES_WRAPPER_KEY__KEY_CTRL_REG__KEY_VALID_bm"),
    "otbn": _bm("otbn_wrapper_key.h", "OTBN_WRAPPER_KEY__KEY_CTRL_REG__KEY_VALID_bm"),
}
_ABR_SEED_VALID = _bm("abr_wrapper_key.h", "ABR_WRAPPER_KEY__SEED_CTRL_REG__KEY_VALID_bm")
for _n in imgh.KEY_CTRL_ORDER[4:8]:
    _KEY_VALID_BM[_n] = _ABR_SEED_VALID
_KEY_VALID_BM["abr_mlkem_shared_key"] = _bm(
    "abr_wrapper_key.h", "ABR_WRAPPER_KEY__SK_CTRL_REG__KEY_VALID_bm"
)
BANKS = imgh.KEY_CTRL_ORDER[:8]  # the eight engine banks, DEST_VALID bit i = BANKS[i]
SHARED = imgh.KEY_CTRL_ORDER[8]

# CPU interrupt mask. architecture.adoc, "Key Manager CPU Interrupt Processing":
# the sources that the specification numbers are CPU IRQ bits 3, 4 and 5. A set
# mask bit masks the source (PicoRV32 maskirq).
CPU_MASK_NUMBERED = 0b111 << 3

# --- KM SRAM (architecture.adoc, "Parameters"; km_csr.adoc, SRAM_LOCK) --------
SRAM_BASE = int(KM.SRAM_MEM_BASE_ADDR)
SRAM_WORDS = int(KM.SRAM_MEM_SIZE) // 4
REGION_WORDS = imgh.SRAM_REGION_BYTES // 4
N_REGIONS = SRAM_WORDS // REGION_WORDS
R31 = N_REGIONS - 1

# --- KM-BUS: every (share, word) address of the eight bank windows ------------
# The key-path port of each bank (the KM-BUS tap of the contract: port 0 OTBN,
# 1 AES, 2 HMAC, 3 KMAC, 4 ABR) and the register prefix of the bank in the
# generated KM map.
_BANK_PORT = {
    "hmac": (2, "HMAC_WRAPPER_KEY_KEY"),
    "kmac": (3, "KMAC_WRAPPER_KEY_KEY"),
    "aes": (1, "AES_WRAPPER_KEY_KEY"),
    "otbn": (0, "OTBN_WRAPPER_KEY_KEY"),
    "abr_mldsa_seed": (4, "ABR_WRAPPER_KEY_MLDSA_SEED_KEY"),
    "abr_mlkem_seed_d": (4, "ABR_WRAPPER_KEY_MLKEM_SEED_D_KEY"),
    "abr_mlkem_seed_z": (4, "ABR_WRAPPER_KEY_MLKEM_SEED_Z_KEY"),
    "abr_mlkem_msg": (4, "ABR_WRAPPER_KEY_MLKEM_MSG_KEY"),
}
# A window is 4 KiB aligned and smaller than 4 KiB, so the low 12 address bits
# name the register on its port whatever base the port carries.
WINDOW_MASK = 0xFFF
_WINDOW_BASE = {
    0: int(KM.OTBN_WRAPPER_KEY_REG_MAP_BASE_ADDR),
    1: int(KM.AES_WRAPPER_KEY_REG_MAP_BASE_ADDR),
    2: int(KM.HMAC_WRAPPER_KEY_REG_MAP_BASE_ADDR),
    3: int(KM.KMAC_WRAPPER_KEY_REG_MAP_BASE_ADDR),
    4: int(KM.ABR_WRAPPER_KEY_REG_MAP_BASE_ADDR),
}
_WINDOW_SIZE = {
    0: int(KM.OTBN_WRAPPER_KEY_REG_MAP_SIZE),
    1: int(KM.AES_WRAPPER_KEY_REG_MAP_SIZE),
    2: int(KM.HMAC_WRAPPER_KEY_REG_MAP_SIZE),
    3: int(KM.KMAC_WRAPPER_KEY_REG_MAP_SIZE),
    4: int(KM.ABR_WRAPPER_KEY_REG_MAP_SIZE),
}
for _p, _b in _WINDOW_BASE.items():
    if _b & WINDOW_MASK or _WINDOW_SIZE[_p] > WINDOW_MASK + 1:
        raise RuntimeError(f"key window of port {_p} is not one aligned 4 KiB page")


def _share_addrs(prefix: str) -> frozenset[int]:
    pat = re.compile(rf"^{prefix}_SHARE[01]_\d+__REG_ADDR$")
    addrs = frozenset(int(getattr(KM, n)) & WINDOW_MASK for n in dir(KM) if pat.match(n))
    if not addrs:
        raise RuntimeError(f"no share registers named {prefix}_SHARE*")
    return addrs


BANK_ADDRS: dict[str, tuple[int, frozenset[int]]] = {
    name: (port, _share_addrs(prefix)) for name, (port, prefix) in _BANK_PORT.items()
}

# --- RESP and command values (firmware.adoc) ----------------------------------
FW_CRC_CODE = (-14) & WORD  # "0xFF - RESP_UNRECOVERABLE_FAULT", fw_crc, sign-extended
RESP_ID_KM_READY = 0x55
JUNK_WORDS = 6

# --- plan ---------------------------------------------------------------------
N_MIN, N_MAX = 8, 256
STREAM_BUDGET = 800  # image words the leaf streams in total (a test parameter)
OVERSIZE_FIXED = (SRAM_WORDS, imgh.FW_WORDS_MAX)  # 8192 and 0xFFFF on every seed
OVERSIZE_LO, OVERSIZE_HI = SRAM_WORDS + 1, imgh.FW_WORDS_MAX - 1
MID_HI = SRAM_WORDS - 1
FLIP_KINDS = ("word0", "last", "trailer", "word")
# Pass 1 keys: 8, 20 and 3 words (1, 2 and 1 KPV slots), with the DEST_VALID
# masks that cover all eight banks between them; the 8-word key holds the
# ML-KEM message bit. Pass 2: two 8-word keys to AES and HMAC only.
DEST = {name: 1 << i for i, name in enumerate(BANKS)}
PASS1_KEYS = (
    (8, DEST["abr_mlkem_msg"] | DEST["aes"] | DEST["hmac"]),
    (20, DEST["otbn"] | DEST["kmac"] | DEST["abr_mldsa_seed"]),
    (3, DEST["abr_mlkem_seed_d"] | DEST["abr_mlkem_seed_z"]),
)
PASS2_KEYS = ((8, DEST["aes"]), (8, DEST["hmac"]))
_cover = 0
for _, _d in PASS1_KEYS:
    _cover |= _d
if _cover != (1 << len(BANKS)) - 1:
    raise RuntimeError("pass 1 DEST_VALID masks do not cover all eight banks")


def slots_of(n_words: int) -> int:
    """KPV slots of a key of ``n_words`` words (firmware.adoc, Key Management)."""
    return -(-n_words // imgh.KPV_SLOT_WORDS)


def image_lock_mask(n_words: int) -> int:
    """SRAM_LOCK after a handover of an image of ``n_words`` words at the SRAM base.

    The handover write-locks every region that holds the image and region 31
    (firmware.adoc, "SRAM Firmware Handover", "Write-lock the image").
    """
    last = (n_words * 4 - 1) // imgh.SRAM_REGION_BYTES
    mask = 0
    for r in range(last + 1):
        mask |= 1 << r
    return mask | (1 << R31)


def _nonzero(rng: SepSeededRng, taken: set[int]) -> int:
    while True:
        w = rng.getrandbits(32)
        if w and w not in taken:
            taken.add(w)
            return w


@dataclass
class Plan:
    seed: int
    n1: int
    n2: int
    good_image: list[int]
    bad_image: list[int]
    flip_kind: str
    flip_index: int  # index in the image frame; n2 is the trailer
    flip_bit: int
    oversize: int
    mid: int
    fuse: dict[str, list[int]]
    keys1: tuple[list[int], ...]
    keys2: tuple[list[int], ...]
    junk: list[int]

    def corrupt_stream(self) -> tuple[list[int], int, int]:
        """The image frame of ``bad_image`` with bit ``flip_bit`` of one word flipped.

        Returns the frame, the original word and the flipped word.
        """
        frame = imgh.stream_words(self.bad_image)
        orig = frame[self.flip_index]
        frame[self.flip_index] = orig ^ (1 << self.flip_bit)
        return frame, orig, frame[self.flip_index]

    @property
    def flip_pos(self) -> str:
        return "trailer" if self.flip_index == self.n2 else str(self.flip_index)

    def draw_lines(self) -> list[str]:
        lines = [
            f"DRAW n1={self.n1} n2={self.n2}",
            f"DRAW flip_kind={self.flip_kind} pos={self.flip_pos} bit={self.flip_bit}",
            f"DRAW oversize={self.oversize} mid={self.mid}",
            "DRAW good_image=" + ",".join(f"0x{w:08x}" for w in self.good_image),
            "DRAW bad_image=" + ",".join(f"0x{w:08x}" for w in self.bad_image),
        ]
        for name, words in self.fuse.items():
            lines.append(f"DRAW fuse {name}=" + ",".join(f"0x{w:08x}" for w in words))
        for p, keys in ((1, self.keys1), (2, self.keys2)):
            for i, k in enumerate(keys):
                lines.append(
                    f"DRAW pass{p} key{i} words={len(k)} " + ",".join(f"0x{w:08x}" for w in k)
                )
        lines.append("DRAW junk=" + ",".join(f"0x{w:08x}" for w in self.junk))
        return lines


def draw_plan(seed: int, fuse_words: dict[str, int]) -> Plan:
    """Every drawn value of the leaf, a pure function of ``seed``.

    ``fuse_words`` maps each staged OTP field to its word count.
    """
    rng = SepSeededRng(seed)
    n1 = rng.randrange(N_MIN, N_MAX + 1)
    n2 = rng.randrange(N_MIN, N_MAX + 1)
    good = imgh.spin_image(n1, rng)
    bad = imgh.spin_image(n2, rng)
    flip_kind = rng.choice(FLIP_KINDS)
    word = rng.randrange(0, n2)
    flip_index = {"word0": 0, "last": n2 - 1, "trailer": n2, "word": word}[flip_kind]
    drawn_bit = rng.randrange(0, 32)
    flip_bit = rng.choice((0, 31, drawn_bit))
    oversize = rng.randrange(OVERSIZE_LO, OVERSIZE_HI + 1)
    mid = rng.randrange(n1 + 1, MID_HI + 1)
    taken: set[int] = set()
    fuse = {name: [_nonzero(rng, taken) for _ in range(n)] for name, n in fuse_words.items()}
    keys1 = tuple([_nonzero(rng, taken) for _ in range(n)] for n, _ in PASS1_KEYS)
    keys2 = tuple([_nonzero(rng, taken) for _ in range(n)] for n, _ in PASS2_KEYS)
    junk = [rng.getrandbits(32) for _ in range(JUNK_WORDS)]
    if n1 + n2 + len(imgh.read_image()) > STREAM_BUDGET:
        raise RuntimeError("the drawn images exceed the stream budget of the leaf")
    return Plan(
        seed=seed,
        n1=n1,
        n2=n2,
        good_image=good,
        bad_image=bad,
        flip_kind=flip_kind,
        flip_index=flip_index,
        flip_bit=flip_bit,
        oversize=oversize,
        mid=mid,
        fuse=fuse,
        keys1=keys1,
        keys2=keys2,
        junk=junk,
    )


# --- pass expectation ----------------------------------------------------------
@dataclass
class PassExp:
    """The pre-state record of one handover pass, and what follows from it."""

    no: int
    registered: int  # KPV slots of the registered keys
    keyvalid_before: int  # OR of the completed-engine masks of the transfers
    shared_before: int  # KM-VALID shared-key key_valid before the handover
    sk_words_before: list[int]  # the eight shared-key KEY words before the handover
    junk: int  # inbound words posted after the trailer
    sram_lock: int  # expected SRAM_LOCK
    staged_secret_val0: dict[str, int]  # staged word 0 of each secret field
    staged_public_val0: dict[str, int]


Fields = dict[str, object]


def _h(v: int, digits: int = 8) -> str:
    return f"0x{v & WORD:0{digits}x}"


def grade_first(first_word: int, confirm_ok: bool, exp: PassExp) -> tuple[bool, Fields]:
    """CHK-HO-FIRST: the first word after the confirmation is the IMG-H MAGIC."""
    ready = int(first_word != imgh.MAGIC and ((first_word >> 8) & 0xFF) == RESP_ID_KM_READY)
    ok = confirm_ok and first_word == imgh.MAGIC
    return ok, {
        "pass": exp.no,
        "ready_between": ready,
        "first_word": _h(first_word),
        "confirm_resp_cmd": int(confirm_ok),
    }


def grade_regs(rep: imgh.ImgHReport, exp: PassExp) -> tuple[bool, Fields]:
    """CHK-HO-REGS."""
    mask_bits = (rep.cpu_irq_mask & CPU_MASK_NUMBERED) >> 3
    ok = (
        rep.irq_enable == 0
        and rep.km_irq_enable == 0
        and rep.irq_entry_addr == ENTRY_ADDR_RESET
        and (rep.irq_entry_lock & ENTRY_LOCK) == 0
        and mask_bits == 0b111
        and (rep.sram_exec_mode & EXEC_MODE_ENABLE) != 0
    )
    return ok, {
        "pass": exp.no,
        "irq_en": _h(rep.irq_enable),
        "km_irq_en": _h(rep.km_irq_enable),
        "entry": _h(rep.irq_entry_addr),
        "lock": rep.irq_entry_lock & ENTRY_LOCK,
        "cpu_mask_bits_3_5": f"0x{mask_bits:x}",
        "cpu_mask_logged": _h(rep.cpu_irq_mask),
        "exec_mode": rep.sram_exec_mode & EXEC_MODE_ENABLE,
    }


def grade_noirq(rep: imgh.ImgHReport, exp: PassExp) -> tuple[bool, Fields]:
    """CHK-HO-NOIRQ, with its control: a read-locked key read shows AXI_SLVERR."""
    sticky = rep.irq_status & IRQ_STATUS_DEFINED
    slverr_seen = any(s.lock_use and s.slv for s in rep.slots)
    return sticky == 0 and slverr_seen, {
        "pass": exp.no,
        "irq_status": f"0x{sticky:03x}",
        "irq_status_word": _h(rep.irq_status),
        "control_slverr_seen": int(slverr_seen),
    }


def grade_entry(rep: imgh.ImgHReport, exp: PassExp) -> tuple[bool, Fields]:
    """CHK-HO-ENTRY: x5 holds the entry address, every other reported GPR is 0."""
    others = {r: v for r, v in rep.gpr.items() if r != 5}
    nonzero = sorted(r for r, v in others.items() if v)
    ok = rep.gpr[5] == SRAM_BASE and not nonzero
    return ok, {
        "pass": exp.no,
        "x5": _h(rep.gpr[5]),
        "other_regs_zero": int(not nonzero),
        "nonzero_regs": "-" if not nonzero else ",".join(f"x{r}" for r in nonzero),
        "not_reported": f"x{imgh.BASE_REG}",
    }


def grade_otp(rep: imgh.ImgHReport, exp: PassExp) -> tuple[bool, Fields]:
    """CHK-HO-OTP. The VAL_0 reads are logged with control=1 and not graded."""
    lock = rep.otp_read_lock
    secret = (lock & OTP_SECRET) >> OTP_SECRET_LSB
    public = (lock & OTP_PUBLIC) >> OTP_PUBLIC_LSB
    life = int(bool(lock & OTP_LIFE_CYCLE))
    ok = (lock & OTP_SECRET) == OTP_SECRET and public == 0 and life == 0
    sv = rep.secret_val0
    fields: Fields = {
        "pass": exp.no,
        "lock_secret": f"0x{secret:x}",
        "lock_pub": f"0x{public:x}",
        "life_cycle": life,
        "demotion": int(bool(lock & OTP_DEMOTION)),
        "control_pre_val0_nonzero": sum(1 for v in exp.staged_secret_val0.values() if v),
        "control_uid_val0": int(sv["chiplet_uid"] != 0),
        "control_sip_val0": int(sv["sip_uid"] != 0),
        "control_sys_val0": int(sv["sys_uid"] != 0),
        "control_cls_val0": int(sv["class_key"] != 0),
        "control_pub_val0_nonzero": sum(1 for v in rep.public_val0.values() if v),
    }
    return ok, fields


def grade_kpv_lock(rep: imgh.ImgHReport, exp: PassExp) -> tuple[bool, Fields]:
    """CHK-HO-KPV-LOCK, with the free-slot write and readback control."""
    locked = [s for s in rep.slots if s.lock_use]
    free = [s for s in rep.slots if not s.lock_use]
    n = len(locked)
    zero = sum(1 for s in locked if s.word0 == 0)
    slv = sum(1 for s in locked if s.slv)
    free_zero = sum(1 for s in free if s.ctrl == 0)
    ctrl_ok = rep.free_slot is not None and rep.free_probe_readback == imgh.CTRL_PROBE
    ok = (
        n == exp.registered
        and zero == n
        and slv == n
        and free_zero == imgh.KPV_SLOTS - n
        and ctrl_ok
    )
    return ok, {
        "pass": exp.no,
        "reg_lock_use": n,
        "expected": exp.registered,
        "reg_read_zero": zero,
        "reg_read_slverr": slv,
        "free_ctrl_zero": free_zero,
        "free_slot": "none" if rep.free_slot is None else rep.free_slot,
        "control_free_rd": _h(rep.free_probe_readback),
    }


def report_keyvalid(rep: imgh.ImgHReport) -> int:
    """The eight bank key_valid bits of the report, in DEST_VALID bit order."""
    return sum((1 << i) for i, n in enumerate(BANKS) if rep.key_ctrl[n] & _KEY_VALID_BM[n])


def grade_sideload(rep: imgh.ImgHReport, exp: PassExp) -> tuple[bool, Fields]:
    """CHK-HO-SIDELOAD, with the KMAC KEY_CTRL write and readback control."""
    kv = report_keyvalid(rep)
    sk = int(bool(rep.key_ctrl[SHARED] & _KEY_VALID_BM[SHARED]))
    kmac_bm = _KEY_VALID_BM["kmac"]
    rd_set = int(bool(rep.kmac_readback_set & kmac_bm))
    rd_clr = int(bool(rep.kmac_readback_clear & kmac_bm))
    ok = kv == 0 and sk == 0 and exp.keyvalid_before != 0 and rd_set == 1 and rd_clr == 0
    return ok, {
        "pass": exp.no,
        "keyvalid_before": f"0x{exp.keyvalid_before:02x}",
        "keyvalid": f"0x{kv:02x}",
        "shared_before": exp.shared_before,
        "shared_valid": sk,
        "control_kmac_rd": f"{rd_set},{rd_clr}",
    }


def grade_sk_words(words: list[int], exp: PassExp) -> tuple[bool, Fields]:
    """CHK-HO-SK-WORDS: the eight shared-key KEY words read 0 at the jump.

    Graded in the pass that hands over with the shared key pending, so the
    words hold the key before the handover.
    """
    ok = all(w == 0 for w in words)
    return ok, {
        "pass": exp.no,
        "words_before_nonzero": sum(1 for w in exp.sk_words_before if w),
        "words_nonzero": sum(1 for w in words if w),
        "words": ",".join(_h(w) for w in words),
    }


def grade_sideload_bus(writes: set[tuple[int, int]], exp: PassExp) -> tuple[bool, Fields]:
    """CHK-HO-SIDELOAD-BUS: every (share, word) address of every bank is written.

    ``writes`` is the set of (port, low address bits) of the completed AW
    handshakes on the key-path ports from the handover command on.
    """
    full = 0
    missed: list[str] = []
    for name, (port, addrs) in BANK_ADDRS.items():
        miss = sorted(a for a in addrs if (port, a) not in writes)
        if not miss:
            full += 1
        missed += [f"{name}:0x{a:03x}" for a in miss]
    ok = full == len(BANK_ADDRS) and not missed
    return ok, {
        "pass": exp.no,
        "banks_written": full,
        "addrs_missed": len(missed),
        "keyvalid_before": f"0x{exp.keyvalid_before:02x}",
        "first_missed": missed[0] if missed else "-",
    }


def grade_sram(
    rep: imgh.ImgHReport, exp: PassExp, writes_delta: int, wmap: list[int]
) -> tuple[bool, Fields]:
    """CHK-HO-SRAM. The store and violation readbacks are logged with control=1.

    ``wmap`` is KM-WMAP: the distinct words written in each write-lock region
    over the handover. The scramble writes every word of every unlocked region,
    so each unlocked region reads REGION_WORDS. Locked regions are logged only.
    """
    locked_regions = bin(exp.sram_lock).count("1")
    min_unlocked = SRAM_WORDS - REGION_WORDS * locked_regions
    unlocked = [r for r in range(N_REGIONS) if not (exp.sram_lock >> r) & 1]
    short = [r for r in unlocked if wmap[r] != REGION_WORDS]
    words_unlocked = sum(wmap[r] for r in unlocked)
    ok = rep.sram_lock == exp.sram_lock and not short
    own_bit = 1 << rep.own_region
    r31_bit = 1 << rep.r31_region
    return ok, {
        "pass": exp.no,
        "sram_lock": _h(rep.sram_lock),
        "expected": _h(exp.sram_lock),
        "control_viol_clear": _h(rep.viol_after_clear),
        "control_r31_dropped": int(rep.r31_readback == rep.r31_old),
        "control_viol31": int(rep.r31_viol == r31_bit),
        "control_image_dropped": int(rep.own_readback == rep.own_old),
        "control_viol_img": int(rep.own_viol == own_bit),
        "own_region": rep.own_region,
        "writes_delta": writes_delta,
        "min_unlocked": min_unlocked,
        "words_unlocked": words_unlocked,
        "regions_short": len(short),
        "first_short": f"{short[0]}:{wmap[short[0]]}" if short else "-",
        "locked_regions": locked_regions,
    }


def grade_mbox(rep: imgh.ImgHReport, exp: PassExp) -> tuple[bool, Fields]:
    """CHK-HO-MBOX: no junk inbound word survives the handover."""
    return rep.inbound_empty == 1, {
        "pass": exp.no,
        "inbound_empty": rep.inbound_empty,
        "km_status": _h(rep.km_status),
        "junk": exp.junk,
    }
