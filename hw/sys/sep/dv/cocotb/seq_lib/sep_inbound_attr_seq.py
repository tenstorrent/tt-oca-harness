# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded AXI4 request attributes for the SMN-inbound external master.

The inbound filter decides on four request fields only
(``hw/ip/axi_filter/doc/index.adoc``, "Match, Then Permit"): the address,
``prot[1]`` against ``allow_ns``, the source ID in ``user[3:0]`` against
``src_id`` (0 is a wildcard), and ``AxLEN`` against ``allow_burst``. Every
other request field is not a decision input. A test that opens a window with
both NS polarities, ``src_id = 0`` and the burst permission it needs can
therefore draw all the other fields freely and still expect every access to
be admitted.

``SepInboundAttrs`` draws one access's fields from ``SepSeededRng``. The
draws stay inside the AXI4 encodings (IHI 0022, A4.4 and A7.2):

* AxCACHE never uses a reserved encoding: bits [3:2] are set only with bit 1
  (modifiable) set.
* A burst longer than 16 beats is modifiable, so it never carries a device
  AxCACHE.
* ARLOCK is set only on a read that meets the exclusive-access rules: at most
  16 beats, a power-of-two byte count of at most 128, and a start address
  aligned to that byte count. AWLOCK stays 0: the SEP documents do not state
  whether a slave supports exclusive access, and an exclusive write that the
  slave refuses leaves memory unchanged, so its data result is not defined.

ID and AxUSER widths come from the testbench port, so a width change moves
the draw with it.
"""

from __future__ import annotations

import cocotb
from env.sep_seeded_rng import SepSeededRng

# AXI4 response codes (IHI 0022, A3.4.4).
RESP_OKAY = 0
RESP_EXOKAY = 1
# AXI4 AxBURST INCR.
BURST_INCR = 1
# AXI4: bursts longer than this many beats must be INCR and modifiable.
_EXCL_MAX_BEATS = 16
_EXCL_MAX_BYTES = 128
# AxCACHE[1] is the modifiable bit; [3:2] are the allocate hints.
_CACHE_MODIFIABLE = 0b0010
# AxPROT[1] is the NS bit the filter matches against allow_ns.
PROT_NS = 0b010


def _port_width(name: str) -> int:
    return len(getattr(cocotb.top, name))


def legal_cache(rng: SepSeededRng, *, modifiable: bool = False) -> int:
    """A non-reserved AxCACHE. ``modifiable`` forces bit 1 set."""
    cache = rng.getrandbits(4)
    if modifiable:
        cache |= _CACHE_MODIFIABLE
    if not cache & _CACHE_MODIFIABLE:
        cache &= 0b0011
    return cache


def exclusive_legal(addr: int, nbytes: int, beats: int) -> bool:
    """AXI4 A7.2.4: an exclusive access that the protocol permits."""
    return (
        beats <= _EXCL_MAX_BEATS
        and nbytes <= _EXCL_MAX_BYTES
        and nbytes & (nbytes - 1) == 0
        and addr % nbytes == 0
    )


class SepInboundAttrs:
    """One access's ID, AxPROT and attributes, drawn from a seeded stream."""

    def __init__(
        self,
        rng: SepSeededRng,
        *,
        write: bool,
        beats: int = 1,
        lock_ok: bool,
        lock: int | None = None,
    ) -> None:
        id_w = _port_width("m_axi_awid" if write else "m_axi_arid")
        user_w = _port_width("m_axi_awuser" if write else "m_axi_aruser")
        # Non-zero ID: the fabric keeps one ordering slot per ID, and an
        # ID-0 access can queue behind unrelated ID-0 traffic.
        self.axi_id = rng.randrange(1, 1 << id_w)
        self.prot = rng.getrandbits(3)
        self.user = rng.getrandbits(user_w)
        self.attrs: dict[str, int] = {
            "cache": legal_cache(rng, modifiable=beats > _EXCL_MAX_BEATS),
            "qos": rng.getrandbits(4),
            "region": rng.getrandbits(4),
            "lock": (rng.getrandbits(1) if lock_ok and not write else 0),
        }
        # A caller may pin ARLOCK on a read it has checked is exclusive-legal.
        if lock is not None:
            if lock and (write or not lock_ok):
                raise ValueError("ARLOCK=1 needs an exclusive-legal read")
            self.attrs["lock"] = lock
        if write:
            self.attrs["wuser"] = rng.getrandbits(_port_width("m_axi_wuser"))

    @property
    def ns(self) -> bool:
        return bool(self.prot & PROT_NS)

    @property
    def locked(self) -> bool:
        return bool(self.attrs["lock"])

    def ok_resps(self) -> tuple[int, ...]:
        """Responses that complete this access successfully. An exclusive read
        answers EXOKAY from a slave with an exclusive monitor and OKAY from one
        without (A7.2.5); either returns the data."""
        return (RESP_OKAY, RESP_EXOKAY) if self.locked else (RESP_OKAY,)

    def kwargs(self) -> dict:
        """Keyword arguments for ``SepAxiAccessSeq``."""
        return {
            "axi_id": self.axi_id,
            "prot": self.prot,
            "user": self.user,
            "attrs": dict(self.attrs),
        }

    def __str__(self) -> str:
        a = self.attrs
        s = (
            f"id=0x{self.axi_id:02x} prot=0b{self.prot:03b} user=0x{self.user:03x} "
            f"cache=0b{a['cache']:04b} qos=0x{a['qos']:x} region=0x{a['region']:x} "
            f"lock={a['lock']}"
        )
        if "wuser" in a:
            s += f" wuser=0x{a['wuser']:03x}"
        return s


class SepInboundAttrTally:
    """Which values each field took over a run, so a log line can show the
    randomized fields actually moved."""

    _FIELDS = ("prot", "cache", "qos", "region", "lock")

    def __init__(self) -> None:
        self.ids: set[int] = set()
        self.users: set[int] = set()
        self.seen: dict[str, set[int]] = {f: set() for f in self._FIELDS}
        self.ns_seen: set[bool] = set()
        # Accesses whose response code and response ID the caller graded, and
        # the codes the exclusive reads among them answered.
        self.graded = 0
        self.locked_resps: set[int] = set()

    def add(self, a: SepInboundAttrs) -> None:
        self.ids.add(a.axi_id)
        self.users.add(a.user)
        self.seen["prot"].add(a.prot)
        for f in ("cache", "qos", "region", "lock"):
            self.seen[f].add(a.attrs[f])
        self.ns_seen.add(a.ns)

    def graded_resp(self, a: SepInboundAttrs, resp: int) -> None:
        self.graded += 1
        if a.locked:
            self.locked_resps.add(resp)

    def summary(self) -> str:
        parts = [f"{f}={len(v)}" for f, v in self.seen.items()]
        return (
            f"distinct ids={len(self.ids)} users={len(self.users)} "
            + " ".join(parts)
            + f" ns={sorted(self.ns_seen)} exclusive-read resps={sorted(self.locked_resps)}"
        )
