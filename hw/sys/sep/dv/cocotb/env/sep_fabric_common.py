# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Constants and helpers shared by the SEP fabric and remap tests.

* AXI response codes (IHI 0022 A3.4.4) and their names, with -1 for a
  response that never arrived.
* ``granule8``: the 8-byte filter granule that holds an address, as a
  ``(start, end)`` pair inside the filter address field.
* ``OUTBOUND_MBX_MAGIC``: the console and verdict magic words that the bench
  outbound responder decodes, read from ``tb/sep_outbound_mbx.sv`` so the two
  cannot drift.
* ``OTHERS_SOURCE_ID``: the AxUSER value of ``OTHERS``, the whole field zero
  (``hw/sys/sep/doc/fabric.adoc``, Transaction Routing: "``OTHERS`` (AxUSER
  zero)").
* ``outbound_ns`` and ``outbound_user``: AxPROT[1] of a request as it leaves on
  the SMU, AP or STEE path, and the whole AxUSER of the AP and STEE paths
  (``hw/sys/sep/doc/fabric.adoc``, ``sep-outbound-attributes-table``).
* ``SepSrcIdGrade`` and ``draw_src_users``: the grade of the SMU-path source
  ID, and the issued AxUSER pair that makes it visible. The specification
  names the ID SEP's ID (``SepSourceId`` in ``hw/sys/sep/doc/cpu.adoc``) and gives
  no number, so no check compares it with a number. The grade reads
  AxUSER[3:0] under the "Source ID carrier" record
  (``hw/sys/sep/dv/docs/SEP_TB_ARCH.adoc``, ``sep-standin-src-id-carrier``);
  AxUSER[11:4] of these beats has no stated value and is logged.
"""

from __future__ import annotations

import re
from pathlib import Path

from sep_reg_meta import INBOUND_FILTER_CTRL_0

RESP_OKAY = 0
RESP_EXOKAY = 1
RESP_SLVERR = 2
RESP_DECERR = 3
RESP_NAME = {-1: "TIMEOUT", 0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}

# START_ADDR / END_ADDR field of a filter entry (the same in both banks).
FILTER_ADDR_MASK: int = INBOUND_FILTER_CTRL_0.field_mask("START_ADDR", "start_addr")


def resp_name(code: int) -> str:
    """Name of an AXI response code; ``none(<code>)`` for any other value."""
    return RESP_NAME.get(code, f"none({code})")


def granule8(addr: int) -> tuple[int, int]:
    """The 8-byte granule that holds ``addr``, inside the filter address field."""
    return addr & ~0x7 & FILTER_ADDR_MASK, addr | 0x7


def _outbound_mbx_magic() -> tuple[int, ...]:
    sv = Path(__file__).resolve().parents[2] / "tb" / "sep_outbound_mbx.sv"
    text = sv.read_text()
    words = []
    for name in ("Magic0", "MagicPass", "MagicFail"):
        m = re.search(
            rf"localparam\s+logic\s*\[31:0\]\s*{name}\s*=\s*32'h([0-9A-Fa-f_]+)\s*;", text
        )
        if m is None:
            raise RuntimeError(f"{sv}: localparam {name} not found")
        words.append(int(m.group(1).replace("_", ""), 16))
    return tuple(words)


OUTBOUND_MBX_MAGIC: tuple[int, ...] = _outbound_mbx_magic()


# AxUSER[3:0] carries the source ID that the filters match against src_id
# (hw/ip/axi_filter/doc/index.adoc, "Match, Then Permit", names the source ID;
# hw/sys/smc/doc/assets/smc-traffic-filters.svg names AxUSER[3:0], the
# "Source ID carrier" record in hw/sys/sep/dv/docs/SEP_TB_ARCH.adoc).
SRC_ID_MASK: int = 0xF
# OTHERS is AxUSER zero, every bit of the field (hw/sys/sep/doc/fabric.adoc,
# Transaction Routing).
OTHERS_SOURCE_ID: int = 0


def outbound_ns(path: str, addr: int) -> int:
    """AxPROT[1] of a request leaving on ``path`` ("smu", "ap" or "stee") at ``addr``.

    ``addr`` is the outgoing address, so the remapped one on the AP and STEE paths.
    """
    if path == "ap":
        return 1
    if path in ("smu", "stee"):
        return 1 - ((addr >> 55) & 1)
    raise ValueError(f"no NS rule for outbound path {path!r}")


def outbound_user(path: str) -> int:
    """The whole AxUSER of a request leaving on ``path`` ("ap" or "stee").

    Both paths set ``OTHERS``, AxUSER zero, so a check compares every AxUSER
    bit with it. The SMU path sets SEP's ID, which has no stated number: grade
    it with ``SepSrcIdGrade``.
    """
    if path in ("ap", "stee"):
        return OTHERS_SOURCE_ID
    raise ValueError(f"no stated source-ID value for outbound path {path!r}")


class SepSrcIdGrade:
    """AxUSER[3:0] of the SMU-path beats of one leaf, graded without a number.

    ``hw/sys/sep/doc/fabric.adoc`` (``sep-outbound-attributes-table``) states
    that the SMU path replaces the initiator's source ID with SEP's ID, and no
    specification or RDL gives that number. The grade is:

    * per beat (``note``): AxUSER[3:0] is known and is not OTHERS (0);
    * per leaf (``finish``): every beat carries the same AxUSER[3:0], and the
      issued AxUSER[3:0] of the beats show the replacement. A constant output
      over two distinct issued values differs from at least one of them, so it
      is a replacement and not a pass-through; at most one issued value can
      equal SEP's ID, so no draw has to avoid an unknown number. An issued
      OTHERS (0) shows the replacement on its own, because the output is not 0.

    The source ID is AxUSER[3:0] (the "Source ID carrier" record,
    ``hw/sys/sep/dv/docs/SEP_TB_ARCH.adoc``). The specification states no value
    for AxUSER[11:4] on the SMU path. The observed number and AxUSER[11:4] of
    the beats are logged by ``obs_line`` and never graded.
    """

    def __init__(self, tag: str) -> None:
        self.tag = tag
        self.observed: list[int] = []
        self.issued: set[int] = set()
        self.upper: set[int] = set()

    def note(self, user: int | None, issued: int | None = None) -> str | None:
        """Record one beat; returns the failure reason, or None when the beat passes.

        ``issued`` is the AxUSER the initiator drove, or None when the bench
        does not drive it (a CPU or firmware access).
        """
        if user is None:
            return "AxUSER is X or Z"
        sid = user & SRC_ID_MASK
        self.observed.append(sid)
        self.upper.add(user >> 4)
        if issued is not None:
            self.issued.add(issued & SRC_ID_MASK)
        if sid == OTHERS_SOURCE_ID:
            return f"AxUSER[3:0]=0x{sid:x} is OTHERS; the SMU path sets SEP's ID"
        return None

    def value(self) -> int | None:
        return self.observed[0] if self.observed else None

    def finish(self, *, min_nonzero_issued: int = 2) -> str | None:
        """Leaf-level failure reason, or None when the leaf passes.

        ``min_nonzero_issued`` is the number of distinct non-zero issued
        AxUSER[3:0] values the beats must carry (2 for a bench master that
        drives the source ID). With 0, the beats must include one issued
        OTHERS (0) instead (the secure DMA, which drives OTHERS).
        """
        if not self.observed:
            return "no SMU-path beat was graded"
        vals = sorted(set(self.observed))
        if len(vals) != 1:
            return f"AxUSER[3:0] differs between SMU-path beats: {_hexset(vals)}"
        nonzero = self.issued - {OTHERS_SOURCE_ID}
        if min_nonzero_issued == 0:
            proof = OTHERS_SOURCE_ID in self.issued
        else:
            proof = len(nonzero) >= min_nonzero_issued
        if not proof:
            return (
                f"the SMU-path beats were issued with AxUSER[3:0] {_hexset(self.issued)}; "
                "the replacement is not visible on them"
            )
        return None

    def summary(self) -> str:
        return (
            f"beats={len(self.observed)} constant={int(len(set(self.observed)) == 1)} "
            f"not_others=1 issued_src_ids={_hexset(self.issued)}"
        )

    def obs_line(self) -> str:
        v = self.value()
        return (
            f"OBS-{self.tag}-SRC-ID: smu_path_src_id={'none' if v is None else f'0x{v:x}'} "
            f"beats={len(self.observed)} user_11_4={_hexset(self.upper)} (value logged)"
        )


def draw_src_users(rng) -> tuple[int, int]:
    """Two 12-bit AxUSER values for a bench master on the SMU path.

    AxUSER[3:0] of each is non-zero (not OTHERS) and the two differ, so the
    replacement is visible to ``SepSrcIdGrade``; AxUSER[11:4] of each is
    non-zero, so a path that changes only bits [3:0] shows on the upper bits.
    """
    a = rng.randrange(1, 16)
    b = rng.choice([v for v in range(1, 16) if v != a])
    return ((rng.randrange(1, 256) << 4) | a, (rng.randrange(1, 256) << 4) | b)


def _hexset(vals) -> str:
    return "{" + ",".join(f"0x{v:x}" for v in sorted(vals)) + "}"
