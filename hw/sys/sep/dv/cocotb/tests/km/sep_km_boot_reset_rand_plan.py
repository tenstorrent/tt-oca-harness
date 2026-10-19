# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Spec constants, frame builders and the seeded plan of ``sep_km_boot_reset_rand_test``.

No cocotb import: the plan is a pure function of the seed, so it can be drawn
and checked without a simulator.

Every constant comes from ``hw/ip/key_manager/doc/firmware.adoc``: the command
IDs from the command summary table of "Command Message Reference", the return
codes from the return-code table of "0x00 - RESP_CMD", the response IDs from
the headings of the response sections ("0x00 - RESP_CMD", "0x55 - RESP_KM_READY"),
and the frame layout from "Command Message Reference". The FIFO depth is the
depth of the ``km_mailbox_sep`` FIFOs (``hw/ip/key_manager/doc/km_mailbox_sep.adoc``).
The CRC goldens are ``env/sep_crc_golden.py``, pinned to published check values.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from env import sep_km_img_h as imgh
from env.sep_crc_golden import crc8_rohc, crc32c
from env.sep_seeded_rng import SepSeededRng

TEST = "sep_km_boot_reset_rand_test"
WORD_MASK = 0xFFFF_FFFF

# --- command IDs (command summary table) ----------------------------------------
CMD_SRAM_VER = 0x02
CMD_STAT = 0x03
CMD_SRAM_LOAD_EXEC = 0x11
CMD_SRAM_EXEC = 0x12

# --- response IDs and return codes ------------------------------------------------
RESP_CMD = 0x00
RESP_KM_READY = 0x55

RC_SUCCESS = 0
RC_FAILURE = -1
RC_INVALID_ARG = -7

# A RESP_CMD with a return argument: header, CMD_SEQ_NUM, COMMAND_ID, the return
# code, the argument and the payload CRC-32C. CMD_STAT returns the status word as
# its argument ("0x03 - CMD_STAT").
STAT_RESP_WORDS = 6

FIFO_DEPTH = 16  # inbound and outbound FIFO of km_mailbox_sep

# --- warm-reset points (contract, step 7) -------------------------------------------
POINT_IDLE = "i"  # idle: every response read
POINT_CMDS = "ii"  # after c CMD_STAT frames, every response read
POINT_PARTIAL = "iii"  # after a partial inbound frame that the KM consumed
POINT_UNREAD = "iv"  # with r unread responses in the outbound FIFO
DRAWN_POINTS = (POINT_IDLE, POINT_CMDS, POINT_PARTIAL)

C_RANGE = (1, 8)  # CMD_STAT frames at point (ii)
J_RANGE = (1, 15)  # partial-frame words at point (iii)
R_RANGE = (1, 3)  # unread CMD_STAT responses at point (iv)
W_RANGE = (0, 16)  # stale inbound words while the KM is held
N_RANGE = (8, 64)  # spin image size in words


def signed8(value: int) -> int:
    v = value & 0xFF
    return v - 0x100 if v & 0x80 else v


def payload_crc(words: list[int] | tuple[int, ...]) -> int:
    return crc32c(b"".join((w & WORD_MASK).to_bytes(4, "little") for w in words))


def header_crc(seq: int, ident: int, plen: int) -> int:
    return crc8_rohc(bytes([seq & 0xFF, ident & 0xFF, plen & 0xFF]))


def header(ident: int, seq: int, plen: int) -> int:
    """A frame header: SEQ [7:0], ID [15:8], PAYLOAD_LEN [23:16], HEADER_CRC8 [31:24]."""
    crc = header_crc(seq, ident, plen)
    return (crc << 24) | ((plen & 0xFF) << 16) | ((ident & 0xFF) << 8) | (seq & 0xFF)


def cmd_frame(cmd: int, seq: int, payload: list[int] | tuple[int, ...]) -> list[int]:
    """A well-formed command frame: header, payload, CRC-32C when the payload is not empty."""
    words = [header(cmd, seq, len(payload))]
    words += [w & WORD_MASK for w in payload]
    if payload:
        words.append(payload_crc(payload))
    return words


# The RESP_KM_READY frame of a boot: one header word, response sequence 0, no payload.
READY_WORD = header(RESP_KM_READY, 0, 0)


def unread_depth(r: int) -> int:
    """Outbound depth after r unread CMD_STAT responses (the FIFO holds 16 words)."""
    return min(STAT_RESP_WORDS * r, FIFO_DEPTH)


@dataclass(frozen=True)
class PointDraw:
    """One warm reset of the warm-reset leg."""

    point: str
    c: int  # point (ii)
    partial: tuple[int, ...]  # point (iii), j words
    r: int  # point (iv)
    stale: tuple[int, ...]  # w stale words written while the KM is held


def _nonzero(rng: SepSeededRng) -> int:
    return rng.randrange(1, 1 << 32)


def _words(rng: SepSeededRng, n: int) -> tuple[int, ...]:
    return tuple(_nonzero(rng) for _ in range(n))


def _in(rng: SepSeededRng, rng_range: tuple[int, int]) -> int:
    lo, hi = rng_range
    return rng.randrange(lo, hi + 1)


def _fmt(value) -> str:
    if isinstance(value, (tuple, list)):
        if len(value) > 16:
            h = hashlib.sha256(b"".join((w & WORD_MASK).to_bytes(4, "little") for w in value))
            return f"n={len(value)}:sha256={h.hexdigest()[:16]}"
        return "[" + ",".join(f"0x{w:x}" if isinstance(w, int) else str(w) for w in value) + "]"
    return str(value)


class BootResetPlan:
    """Every drawn value of one leaf, drawn once from the seed in a fixed order.

    Only the values of the implemented steps are drawn: the reset points and
    their order, c, j and its words, r, w and its words, and the spin image.
    """

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        self._draws: list[tuple[str, object]] = []

        # Three distinct points: (iv) on every seed and two of (i) to (iii).
        points = [*rng.sample(list(DRAWN_POINTS), 2), POINT_UNREAD]
        rng.shuffle(points)
        self._log("point_order", points)
        draws = []
        for k, p in enumerate(points):
            c = _in(rng, C_RANGE) if p == POINT_CMDS else 0
            partial = _words(rng, _in(rng, J_RANGE)) if p == POINT_PARTIAL else ()
            r = _in(rng, R_RANGE) if p == POINT_UNREAD else 0
            stale = _words(rng, _in(rng, W_RANGE))
            if p == POINT_CMDS:
                self._log(f"reset{k}_c", c)
            if p == POINT_PARTIAL:
                self._log(f"reset{k}_j", len(partial))
                self._log(f"reset{k}_partial_words", partial)
            if p == POINT_UNREAD:
                self._log(f"reset{k}_r", r)
            self._log(f"reset{k}_w", len(stale))
            self._log(f"reset{k}_stale_words", stale)
            draws.append(PointDraw(point=p, c=c, partial=partial, r=r, stale=stale))
        self.resets = tuple(draws)

        self.image_n = _in(rng, N_RANGE)
        self.image = tuple(imgh.spin_image(self.image_n, rng))
        self._log("image_n", self.image_n)
        self._log("image_words", self.image)

    def _log(self, name: str, value: object) -> None:
        self._draws.append((name, value))

    def draw_lines(self) -> list[str]:
        """One ``DRAW <name>=<value>`` line for every drawn value."""
        return [f"DRAW {name}={_fmt(value)}" for name, value in self._draws]
