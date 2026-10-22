# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PIC source map, pending-word builder and priority model of the SEP EL2 PIC.

Written from the specification, never from the RTL or a DUT read:

* ``hw/sys/sep/doc/interrupts.adoc`` ("Sources and Routing", "SEP PIC source
  assignments", "SEP CPU Interrupt Vector Map"): bit ``i`` of the 43-bit
  aggregate vector is PIC source ``i + 1``; sources 44 to 255 are the
  boundary input; source 0 is tied to zero. The source numbers come from the
  DV-owned table ``env/sep_spec_tables.PIC``.
* ``hw/sys/sep/regs/gen/adoc/blocks/el2_pic.adoc`` (``meip``, ``meipl``,
  ``mpiccfg``): ``meip`` word ``w`` bit ``b`` is source ``32 * w + b``; the
  priority order ``priord`` 0 is standard (higher ``meipl`` wins, 0 never
  delivers) and 1 is reverse (lower wins, 15 never delivers). The number of
  priority levels is ``2 ** EL2_PIC__MEIPL__INTPRIORITY_bw`` from the generated
  C header ``hw/sys/sep/regs/gen/c/blocks/el2_pic.h``.

The six sources whose idle level the specification does not state (13, 15, 16,
37, 38 and 39) are masked in every compare that expects 0 or an exact word,
and their value is logged with :func:`idle_unstated_line`. A firmware leaf
receives :func:`meip_idle_mask_words` through its parameter block, so the host
and the firmware use one mask.

Usage::

    exp = meip_words([1, 24, 33])
    ok = meip_equal(got_words, exp)
    first = winner({8: 0, 21: 9, 1: 12}, priord=1)
"""

from __future__ import annotations

from pathlib import Path

from sep_reg_meta import CHeaderRegBlock
from sep_spec_tables import pic

NUM_VEC = 43
NUM_SOURCES = 256
MEIP_WORDS = NUM_SOURCES // 32
FIRST_BOUNDARY_SOURCE = NUM_VEC + 1
EL2_PIC = CHeaderRegBlock(
    "EL2_PIC", Path(__file__).resolve().parents[3] / "regs" / "gen" / "c" / "blocks" / "el2_pic.h"
)
NUM_LEVELS = 1 << EL2_PIC.fields("MEIPL")["INTPRIORITY"]["bw"]

EXCLUDED_IDLE_SOURCES: tuple[int, ...] = (
    pic("WDT alert"),
    pic("KM mailbox IRQ"),
    pic("Entropy source IRQ"),
    pic("Entropy pool low"),
    pic("Entropy pool fill stall"),
    pic("Entropy pool pointer fault"),
)

SRC_MAILBOX: tuple[int, ...] = tuple(pic(f"Mailbox interrupt {k}") for k in range(8))
SRC_DMA_ALERT = pic("DMA alert")
SRC_SPI = pic("SPI IRQ")
SRC_TIED = pic("External TRNG IRQ")
SRC_HMAC_FIFO_EMPTY = pic("HMAC FIFO empty")
SRC_KMAC_FIFO_EMPTY = pic("KMAC FIFO empty")
SRC_CRYPTO_ALERT = pic("Crypto alert")
SRC_DMA_REG_PATH = pic("DMA register-path bus error")
SRC_DMA_HOST_PATH = pic("DMA host-path integrity/bus fault")
SRC_PERIPH_OR = pic("Peripheral register-bridge fault")


def vec_bit(src: int) -> int:
    """Aggregate vector bit of PIC source ``src`` (1 to 43)."""
    if not 1 <= src <= NUM_VEC:
        raise ValueError(f"PIC source {src} has no vector bit (1..{NUM_VEC})")
    return src - 1


def vec_mask(sources) -> int:
    """Vector word with the bit of each source of ``sources`` set."""
    m = 0
    for s in sources:
        m |= 1 << vec_bit(s)
    return m


VEC_ALL = (1 << NUM_VEC) - 1
VEC_IDLE_MASK = vec_mask(EXCLUDED_IDLE_SOURCES)
VEC_GRADED = VEC_ALL & ~VEC_IDLE_MASK


def vec_masked(vec: int) -> int:
    """The vector with the six excluded idle bits cleared."""
    return vec & VEC_GRADED


def meip_pos(src: int) -> tuple[int, int]:
    """(word, bit) of source ``src`` in ``meip[0..7]``."""
    if not 0 <= src < NUM_SOURCES:
        raise ValueError(f"PIC source {src} is outside 0..{NUM_SOURCES - 1}")
    return src // 32, src % 32


def meip_words(sources) -> list[int]:
    """The eight ``meip`` words with the bit of each source of ``sources`` set."""
    words = [0] * MEIP_WORDS
    for s in sources:
        w, b = meip_pos(s)
        words[w] |= 1 << b
    return words


def meip_idle_mask_words() -> list[int]:
    """Per word, the bits of the six excluded idle sources."""
    return meip_words(EXCLUDED_IDLE_SOURCES)


def meip_masked(words) -> list[int]:
    """``words`` with the six excluded idle bits cleared."""
    idle = meip_idle_mask_words()
    return [w & ~m & 0xFFFF_FFFF for w, m in zip(words, idle, strict=True)]


def meip_equal(got, exp) -> bool:
    """True when ``got`` equals ``exp`` outside the six excluded idle bits."""
    return meip_masked(got) == meip_masked(exp)


def boundary_pending(words) -> list[int]:
    """The pending sources above 43 (``meip[1]`` bits 12 to 31 and ``meip[2..7]``)."""
    out = []
    for src in range(FIRST_BOUNDARY_SOURCE, NUM_SOURCES):
        w, b = meip_pos(src)
        if (words[w] >> b) & 1:
            out.append(src)
    return out


def assigned_masked(words) -> list[int]:
    """Words of sources 0 to 43 only, with the excluded idle bits cleared."""
    out = meip_masked(words)
    w, b = meip_pos(FIRST_BOUNDARY_SOURCE)
    out[w] &= (1 << b) - 1
    for i in range(w + 1, MEIP_WORDS):
        out[i] = 0
    return out


def idle_unstated_values(vec: int | None = None, words=None) -> dict[str, int | str]:
    """The value of each excluded idle source, from the vector or from ``meip``."""
    vals: dict[str, int | str] = {}
    for s in EXCLUDED_IDLE_SOURCES:
        if words is not None:
            w, b = meip_pos(s)
            vals[f"src{s}"] = (words[w] >> b) & 1
        elif vec is not None:
            vals[f"src{s}"] = (vec >> vec_bit(s)) & 1
        else:
            vals[f"src{s}"] = "na"
    return vals


def idle_unstated_line(vec: int | None = None, words=None) -> str:
    """``OBS-IDLE-UNSTATED LOG src13=a src15=f ...`` for the log."""
    vals = idle_unstated_values(vec, words)
    return "OBS-IDLE-UNSTATED LOG " + " ".join(f"{k}={v}" for k, v in vals.items())


# ---- priority model (el2_pic.adoc, meipl and mpiccfg) ----


def never_value(priord: int) -> int:
    """The ``meipl`` value that never delivers: 0 standard, 15 reverse."""
    return 0 if priord == 0 else NUM_LEVELS - 1


def effective(raw: int, priord: int) -> int:
    """Effective priority: the raw value in standard order, 15 - raw in reverse."""
    if not 0 <= raw < NUM_LEVELS:
        raise ValueError(f"meipl value {raw} is outside 0..{NUM_LEVELS - 1}")
    return raw if priord == 0 else NUM_LEVELS - 1 - raw


def raw_for_effective(eff: int, priord: int) -> int:
    """The raw ``meipl`` value that gives effective priority ``eff``."""
    return effective(eff, priord)


def mirror(raw: int) -> int:
    """15 - raw: keeps the effective priority when ``priord`` flips."""
    return NUM_LEVELS - 1 - raw


def usable(raw: int, priord: int) -> bool:
    """True when ``raw`` is not the never value of ``priord``."""
    return raw != never_value(priord)


def winner(raws: dict[int, int], priord: int) -> int:
    """The source with the highest effective priority among ``raws``.

    ``raws`` maps source to raw ``meipl``. Every source must be usable. On equal
    effective priorities the source with the lowest ID wins: the PIC selects
    "the highest-priority request with the lowest interrupt source ID" (VeeR EL2
    PRM section 8.3.3; the manual is cited at ``hw/sys/sep/doc/cpu.adoc:22-23``).
    """
    if not raws:
        raise ValueError("winner of an empty set")
    eff = {s: effective(r, priord) for s, r in raws.items()}
    for s, r in raws.items():
        if not usable(r, priord):
            raise ValueError(f"source {s} holds the never value {r} for priord={priord}")
    return min(eff, key=lambda s: (-eff[s], s))


def _selftest() -> None:
    assert vec_bit(1) == 0 and vec_bit(43) == 42
    assert VEC_IDLE_MASK == sum(1 << b for b in (12, 14, 15, 36, 37, 38))
    idle = meip_idle_mask_words()
    assert idle[0] == (1 << 13) | (1 << 15) | (1 << 16)
    assert idle[1] == (1 << 5) | (1 << 6) | (1 << 7)
    assert all(w == 0 for w in idle[2:])
    assert meip_words([24, 33]) == [1 << 24, 1 << 1, 0, 0, 0, 0, 0, 0]
    w = meip_words([24, 44, 255, 13])
    assert boundary_pending(w) == [44, 255]
    assert assigned_masked(w) == [1 << 24, 0, 0, 0, 0, 0, 0, 0]
    assert meip_equal(meip_words([1, 13]), meip_words([1]))
    assert never_value(0) == 0 and never_value(1) == 15
    assert effective(1, 0) == 1 and effective(14, 1) == 1 and effective(0, 1) == 15
    assert mirror(3) == 12 and effective(mirror(3), 1) == effective(3, 0)
    assert winner({1: 12, 8: 0, 21: 9}, priord=1) == 8
    assert winner({1: 3, 8: 15, 21: 6}, priord=0) == 8
    assert winner({21: 5, 8: 5, 30: 2}, priord=0) == 8
    assert winner({24: 9, 3: 9}, priord=1) == 3
    assert winner({7: 4, 2: 4, 5: 11}, priord=1) == 2
    for bad in ({1: 0, 2: 3}, {}):
        try:
            winner(bad, priord=0)
        except ValueError:
            continue
        raise AssertionError(f"winner accepted {bad}")
    assert SRC_CRYPTO_ALERT == 33 and SRC_DMA_ALERT == 12 and SRC_TIED == 17


if __name__ == "__main__":
    _selftest()
    print("sep_pic_map self-test PASS")
