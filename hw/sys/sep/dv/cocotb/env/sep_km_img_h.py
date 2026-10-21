# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Key Manager SRAM images for CMD_SRAM_LOAD_EXEC: IMG-H and the spin image.

IMG-H (``cocotb/tests/km_fw/km_img_h.S``, committed as
``cocotb/tests/km_img_h.parhex``) runs after the ROM handover and sends the KM
state at the jump to the host as one KM mailbox message. :func:`decode_report`
reads that message; the layout table is in the header of ``km_img_h.S``. The
image and this module grade nothing. Every golden lives in the test.

The spin image is a drawn image whose word 0 jumps to itself, for legs that
only need an image that the ROM accepts and runs.

:func:`stream_words` gives the image frame of CMD_SRAM_LOAD_EXEC
(``hw/ip/key_manager/doc/firmware.adoc``, "0x11 - CMD_SRAM_LOAD_EXEC", "Image
Frame"): the image words, then the CRC-32C of the image words in little-endian
byte order. The caller sets the separator on the last word.

No cocotb import, so unit tests load this module without a simulator.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sep_crc_golden import crc32c

WORD_MASK = 0xFFFF_FFFF

IMAGE_NAME = "km_img_h"
IMAGE_PATH = Path(__file__).resolve().parents[1] / "tests" / f"{IMAGE_NAME}.parhex"

_GEN_C = Path(__file__).resolve().parents[5] / "ip" / "key_manager" / "regs" / "gen" / "c"


def _define(header: str, name: str) -> int:
    for line in (_GEN_C / header).read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "#define" and parts[1] == name:
            return int(parts[2], 0)
    raise KeyError(f"{name} not found in {_GEN_C / header}")


KM_SRAM_BASE = _define("key_manager_addr.h", "KEY_MANAGER_SRAM_BASE_ADDR")
KM_SRAM_SIZE = _define("key_manager_addr.h", "KEY_MANAGER_SRAM_SIZE")
SRAM_REGION_BYTES = 1024  # km_csr.adoc, SRAM_LOCK: one bit per 1 KB region
KPV_SLOTS = _define("key_manager_addr.h", "KEY_MANAGER_KPV_CTRL_NUM")
KPV_SLOT_WORDS = _define("key_manager_addr.h", "KEY_MANAGER_KPV_KEY_ENTRY_WORD_NUM")
AXI_SLVERR = _define("km_csr.h", "KM_CSR__IRQ_STATUS_REG__AXI_SLVERR_bm")
AXI_DECERR = _define("km_csr.h", "KM_CSR__IRQ_STATUS_REG__AXI_DECERR_bm")
INBOUND_EMPTY = _define("km_mailbox_km.h", "KM_MAILBOX_KM__STATUS_REG__INBOUND_EMPTY_bm")
LOCK_USE = _define("km_kpv.h", "KM_KPV__CTRL_REG__LOCK_USE_bm")

# --- FW_WORDS (firmware.adoc, "0x11 - CMD_SRAM_LOAD_EXEC", payload) ----------
FW_WORDS_MAX = 0xFFFF  # the 16-bit field; the load ceiling is lower, not stated

# --- IMG-H report (km_img_h.S header) ----------------------------------------
LAYOUT_VERSION = 1
REPORT_WORDS = 263
MAGIC = 0x4B4D_4948  # "KMIH"
END_MAGIC = 0x4B4D_4945  # "KMIE"
LAYOUT = (LAYOUT_VERSION << 16) | REPORT_WORDS
CTRL_PROBE = 0x4B4D_5756  # written to word 0 of the lowest free KPV slot
NO_FREE_SLOT = WORD_MASK
BASE_REG = 15  # the store base register; its entry value is not reported
GPR_ORDER = (5, 1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12, 13, 14)  # RV32E, x15 excluded
SECRET_FIELDS = ("chiplet_uid", "sip_uid", "sys_uid", "class_key")
PUBLIC_FIELDS = ("sep_chiplet_id", "sep_sip_id", "sep_sys_id")
KEY_CTRL_ORDER = (
    "hmac",
    "kmac",
    "aes",
    "otbn",
    "abr_mldsa_seed",
    "abr_mlkem_seed_d",
    "abr_mlkem_seed_z",
    "abr_mlkem_msg",
    "abr_mlkem_shared_key",
)

W_MAGIC = 0
W_LAYOUT = 1
W_GPR = 2
W_IRQ_STATUS = W_GPR + len(GPR_ORDER)  # 16
W_IRQ_ENABLE = 17
W_KM_IRQ_ENABLE = 18
W_IRQ_ENTRY_ADDR = 19
W_IRQ_ENTRY_LOCK = 20
W_CPU_IRQ_MASK = 21
W_SRAM_EXEC_MODE = 22
W_OTP_READ_LOCK = 23
W_SECRET_VAL0 = 24
W_PUBLIC_VAL0 = W_SECRET_VAL0 + len(SECRET_FIELDS)  # 28
W_SRAM_LOCK = 31
W_KM_STATUS = 32
W_SLOTS = 33
W_FREE_SLOT = W_SLOTS + 3 * KPV_SLOTS  # 225
W_FREE_WORDS = W_FREE_SLOT + 1  # 226
W_FREE_PROBE = W_FREE_WORDS + KPV_SLOT_WORDS  # 242
W_KEY_CTRL = W_FREE_PROBE + 1  # 243
W_KMAC_SET = W_KEY_CTRL + len(KEY_CTRL_ORDER)  # 252
W_KMAC_CLR = 253
W_VIOL_CLEAR = 254
W_R31_OLD = 255
W_R31_READBACK = 256
W_R31_VIOL = 257
W_OWN_OLD = 258
W_OWN_READBACK = 259
W_OWN_VIOL = 260
W_OWN_ADDR = 261
W_END = 262
assert W_END + 1 == REPORT_WORDS


class ImgHReportError(ValueError):
    """The words are not one IMG-H report of this layout."""


@dataclass(frozen=True)
class KpvSlotReport:
    ctrl: int
    word0: int
    bus_err: int  # IRQ_STATUS & (AXI_SLVERR | AXI_DECERR) after the word-0 read

    @property
    def lock_use(self) -> bool:
        return bool(self.ctrl & LOCK_USE)

    @property
    def slv(self) -> int:
        return int(bool(self.bus_err & AXI_SLVERR))

    @property
    def dec(self) -> int:
        return int(bool(self.bus_err & AXI_DECERR))


@dataclass(frozen=True)
class ImgHReport:
    gpr: dict[int, int]  # register number -> value at entry; no x0, no x15
    irq_status: int
    irq_enable: int
    km_irq_enable: int
    irq_entry_addr: int
    irq_entry_lock: int
    cpu_irq_mask: int
    sram_exec_mode: int
    otp_read_lock: int
    secret_val0: dict[str, int]
    public_val0: dict[str, int]
    sram_lock: int
    km_status: int
    slots: tuple[KpvSlotReport, ...]
    free_slot: int | None
    free_words: tuple[int, ...]
    free_probe_readback: int
    key_ctrl: dict[str, int]
    kmac_readback_set: int
    kmac_readback_clear: int
    viol_after_clear: int
    r31_old: int
    r31_readback: int
    r31_viol: int
    own_old: int
    own_readback: int
    own_viol: int
    own_addr: int

    @property
    def inbound_empty(self) -> int:
        return int(bool(self.km_status & INBOUND_EMPTY))

    @property
    def own_region(self) -> int:
        return (self.own_addr - KM_SRAM_BASE) // SRAM_REGION_BYTES

    @property
    def r31_region(self) -> int:
        return (KM_SRAM_SIZE - 4) // SRAM_REGION_BYTES


def decode_report(words: Sequence[int]) -> ImgHReport:
    """Decode the IMG-H message (all REPORT_WORDS words, MAGIC first)."""
    w = [int(x) & WORD_MASK for x in words]
    if len(w) != REPORT_WORDS:
        raise ImgHReportError(f"IMG-H report has {len(w)} words, expected {REPORT_WORDS}")
    for idx, want, what in (
        (W_MAGIC, MAGIC, "MAGIC"),
        (W_LAYOUT, LAYOUT, "LAYOUT"),
        (W_END, END_MAGIC, "END_MAGIC"),
    ):
        if w[idx] != want:
            raise ImgHReportError(
                f"IMG-H word {idx} is 0x{w[idx]:08x}, expected {what} 0x{want:08x}"
            )
    free = w[W_FREE_SLOT]
    if free != NO_FREE_SLOT and free >= KPV_SLOTS:
        raise ImgHReportError(f"IMG-H free slot word 0x{free:08x} is not a slot")
    return ImgHReport(
        gpr={r: w[W_GPR + i] for i, r in enumerate(GPR_ORDER)},
        irq_status=w[W_IRQ_STATUS],
        irq_enable=w[W_IRQ_ENABLE],
        km_irq_enable=w[W_KM_IRQ_ENABLE],
        irq_entry_addr=w[W_IRQ_ENTRY_ADDR],
        irq_entry_lock=w[W_IRQ_ENTRY_LOCK],
        cpu_irq_mask=w[W_CPU_IRQ_MASK],
        sram_exec_mode=w[W_SRAM_EXEC_MODE],
        otp_read_lock=w[W_OTP_READ_LOCK],
        secret_val0={n: w[W_SECRET_VAL0 + i] for i, n in enumerate(SECRET_FIELDS)},
        public_val0={n: w[W_PUBLIC_VAL0 + i] for i, n in enumerate(PUBLIC_FIELDS)},
        sram_lock=w[W_SRAM_LOCK],
        km_status=w[W_KM_STATUS],
        slots=tuple(
            KpvSlotReport(*w[W_SLOTS + 3 * s : W_SLOTS + 3 * s + 3]) for s in range(KPV_SLOTS)
        ),
        free_slot=None if free == NO_FREE_SLOT else free,
        free_words=tuple(w[W_FREE_WORDS : W_FREE_WORDS + KPV_SLOT_WORDS]),
        free_probe_readback=w[W_FREE_PROBE],
        key_ctrl={n: w[W_KEY_CTRL + i] for i, n in enumerate(KEY_CTRL_ORDER)},
        kmac_readback_set=w[W_KMAC_SET],
        kmac_readback_clear=w[W_KMAC_CLR],
        viol_after_clear=w[W_VIOL_CLEAR],
        r31_old=w[W_R31_OLD],
        r31_readback=w[W_R31_READBACK],
        r31_viol=w[W_R31_VIOL],
        own_old=w[W_OWN_OLD],
        own_readback=w[W_OWN_READBACK],
        own_viol=w[W_OWN_VIOL],
        own_addr=w[W_OWN_ADDR],
    )


# --- images ------------------------------------------------------------------
def read_image(path: str | Path = IMAGE_PATH) -> list[int]:
    """The 32-bit words of a KM ``.parhex`` image from word 0, parity dropped.

    Each data line is ``{parity[3:0]}{word[31:0]}``. An SRAM image is linked
    from word 0 and has no ``@`` other than ``@00000000``.
    """
    words: list[int] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("@"):
            if int(line[1:], 16) != len(words):
                raise ValueError(f"{path}: address {line} is not contiguous")
            continue
        words.append(int(line, 16) & WORD_MASK)
    return words


def image_crc(words: Sequence[int]) -> int:
    """CRC-32C of the image words in little-endian byte order (the trailer)."""
    return crc32c(b"".join((int(x) & WORD_MASK).to_bytes(4, "little") for x in words))


def stream_words(words: Sequence[int]) -> list[int]:
    """The CMD_SRAM_LOAD_EXEC image frame: the words, then the CRC-32C trailer.

    The separator belongs on the last word (the trailer).
    """
    if not 1 <= len(words) <= FW_WORDS_MAX:
        raise ValueError(f"FW_WORDS {len(words)} outside 1..{FW_WORDS_MAX}")
    return [int(x) & WORD_MASK for x in words] + [image_crc(words)]


# jal x0, 0: opcode 0x6F (JAL), rd = x0, offset 0. The word jumps to itself.
SPIN_WORD = 0x0000_006F


def spin_image(n: int, rng) -> list[int]:
    """A spin image of ``n`` words: word 0 is ``SPIN_WORD``, words 1..n-1 drawn.

    ``rng`` is the leaf ``SepSeededRng`` (``getrandbits``), so the words are a
    pure function of the seed. The drawn words never run.
    """
    if not 1 <= n <= FW_WORDS_MAX:
        raise ValueError(f"spin image size {n} outside 1..{FW_WORDS_MAX}")
    return [SPIN_WORD] + [rng.getrandbits(32) for _ in range(n - 1)]
