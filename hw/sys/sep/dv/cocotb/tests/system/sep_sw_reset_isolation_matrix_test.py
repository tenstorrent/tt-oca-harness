# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SW_RESET_N subsets, its reserved bits, and the isolation sequence of every domain.

What the test proves.

Leg A. A ``SW_RESET_N`` field at 0 resets exactly its domain and a field at 1
releases it, for any subset, order and spacing of writes, and the engine state
of the other domains stays intact. Bits 63:7 have no field, so a write to them
changes no field and resets no domain; their read value is logged only.

Leg B. For each domain a ``SW_RESET_N`` assert first isolates the paths of the
table of paths isolated before each software reset. Accepted host transactions
drain. Host accesses that arrive after the request complete with SLVERR, and a
4-byte read returns ``0x1501A7ED``. The reset asserts only after every path of
the domain reports isolated, and a write of 1 releases reset and isolation
together. The Key Manager mailbox, the eFuse wrapper host port, the lifecycle
controller, the entropy pool and the external TRNG window have no isolate stage
and answer as in the memory map while a domain is isolated.

Sources: ``hw/sys/sep/doc/reset_controller.adoc`` (Software Reset Register,
Isolation and Reset Sequencing, the table of paths isolated before each
software reset, Resetting the TRNG); ``hw/sys/sep/doc/clk_rst.adoc`` (Reset
Architecture); ``hw/sys/sep/regs/gen/adoc/blocks/sep_reset_ctrl.adoc``
(``SW_RESET_N``, bits 63:7 with Access "-"); ``hw/sys/sep/regs/gen/adoc/memory_map.adoc``
(external TRNG window).

Stimulus. All accesses go out on the CPU-LSU master (``s_axi``). Leg A walks a
drawn partition of the six engine domains (at least one step with two or more
domains) in a drawn order, with one write per step or one write per domain at
a drawn spacing, drawn reserved bits and a drawn write shape, after a
reserved-only leg that writes bits 63:7 in the 64-bit, high-half and low-half
shapes. A subset write uses the 64-bit lane or the low half, because a
high-half write carries no field bit. Leg B releases the Key Manager with the boot write of the open Key
Manager tests and runs single-victim passes of OTBN, AES, HMAC, KMAC and Adams
Bridge, two victim pairs (one releases the first victim first, the other the
second), a Key Manager pass and a TRNG pass with the Key Manager held. In a
pass the leaf puts host transactions in flight on the path of the victim. For
OTBN and AES the first host transaction is placed from measured latencies
(``CAL-DRAIN``) so that the host isolate stage accepts it one clock before the
isolate request rises, and the master holds RREADY low until the request rises.

Probes. Approved: ``ip_rst_n[6:1]`` (``*_gated_rst_n_probe_o``). Observation
taps: ``ip_rst_n[0]`` (``km_gated_rst_n_probe_o``) and the 14-bit isolate
request and isolate-complete vectors (``crypto_isolate_req_probe_o``,
``crypto_isolated_probe_o``), read in the bench index of
``env/sep_reset_taps.py``, and the slave-side handshakes of the 14 isolate
stages (``iso_slv_{aw,ar,b,r}_hs_probe_o``, ``iso_slv_{b,r}resp_probe_o``). The handshakes of ``s_axi`` are sampled on the same
clock as the taps.

Checkers (log shape ``CHK-<ID> PASS|FAIL: ...``):
  CHK-SUBSET        each leg A step with two or more domains: the domains of S
                    read their RDL default after the release, every other
                    probe and unrelated register keeps its armed value.
                    Single-domain steps log ``CTL-SUBSET``.
  CHK-SUBSET-COVER  the partition drops every one of the six taps at least once.
  CHK-SWRST-RSVD    after each write with bits 63:7 set a response arrives and
                    the 64-bit readback answers OKAY with bits 6:0 equal to the
                    written fields (bits 63:7 are logged as ``OBS-SWRST-RSVD``).
  CHK-SWRST-SCOPE   ``ip_rst_n[6:1]`` are stable on every cycle of the
                    reserved-only leg and the unrelated registers keep their
                    value. Control: the first subset step moves a tap.
  CHK-ISO-RESP      in the isolated window every 32-bit lane that an isolated
                    read covers carries ``0x1501A7ED`` (the covered bytes for a
                    1- or 2-byte read) with SLVERR; every 64-bit port (CSRNG,
                    EDN, Adams Bridge) gets a read of its high lane on every
                    seed. For OTBN, AES, KMAC and Adams Bridge every write of
                    the size sweep also completes SLVERR (HMAC and TRNG log
                    their write answers as ``CTL-ISO-RESP``). The written value
                    is absent after the release.
  CHK-ISO-REL       the isolate-complete bits of D fall within the allowance of
                    the ``ip_rst_n[D]`` rise; the probe reads its RDL default.
  CHK-ISO-NEVER     the drawn never-isolated port answers as in the memory map
                    in the isolated window.
  CHK-ISO-PAIR      in each pair pass each victim isolates before its tap falls,
                    and its tap rises only after its own write of 1.
  CHK-ISO-ORDER     OTBN, AES, Key Manager: the tap falls at or after the cycle
                    all isolate-complete bits of D are high (HMAC, KMAC, Adams
                    Bridge and TRNG log ``CTL-ISO-ORDER``).
  CHK-ISO-DRAIN     OTBN, AES: at the slave side of the host isolate stage of
                    D a transaction is open when the isolate request rises,
                    and every transaction the stage accepted before the
                    request has its response there before ``ip_rst_n[D]``
                    falls (the others log ``CTL-ISO-DRAIN``). The ``s_axi``
                    arrival of the same responses is logged as
                    ``OBS-ISO-DRAIN-SAXI``.
  CHK-ISO-PATHS     the isolate requests that rise from the baseline equal the
                    table set of the victims written.

Environment choices (logged): the release allowance of CHK-ISO-REL
(``REL_ALLOW`` clocks) and the bound of every wait.

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense``, with the Key
Manager ROM image the open Key Manager tests stage (``km_rom``,
``+km_rom_hex=km_rom.parhex``). Four seeds, Verilator and VCS.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cocotb
import pyuvm
from cocotb.triggers import FallingEdge, NextTimeStep, ReadOnly, RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_axi_chan_mon import SepAxiChanMon, SepAxiReadyHold
from env.sep_decode_resp import sep_map_rows
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_field_compare import field_compare
from env.sep_reset_taps import (
    IP_RST_PORTS,
    ISO_BENCH,
    ISO_WIDTH,
    SepResetTaps,
    iso_name,
    iso_rtl_bit,
)
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import AES, HMAC, KMAC, OTBN, SEP_RESET_CTRL, register_fields, sym, word_reset
from seq_lib.sep_abr_keygen_seq import ABR_INTR
from seq_lib.sep_abr_mlkem_seq import MLKEM_STATUS as ABR_MLKEM_STATUS
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_km_mailbox_seq import KM_MBOX_BASE, KM_MBOX_STATUS
from seq_lib.sep_reset_mid_transfer_seq import (
    PROBES,
    ResetProbe,
    SepResetProbeDriver,
    other_value,
)
from seq_lib.sep_scratch_reset_seq import SCRATCH_COLD_0, SCRATCH_RESET_DEFAULT, SCRATCH_WARM_0
from seq_lib.sep_sw_reset_seq import SEP_RESET_CTRL_SW_RESET_N, SW_RESET_N_BIT

TEST = "sep_sw_reset_isolation_matrix_test"
RESP_OKAY, RESP_SLVERR = 0, 2
RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR", -1: "NONE"}
# reset_controller.adoc, Isolation and Reset Sequencing, step 2.
ISO_DATA = 0x1501_A7ED

DOMS = ("otbn", "aes", "hmac", "kmac", "trng", "abr")
IPRST = {"km": SW_RESET_N_BIT["km"], **{d: SW_RESET_N_BIT[d] for d in DOMS}}
SW = SEP_RESET_CTRL_SW_RESET_N
SW_FIELDS = SEP_RESET_CTRL.mask32("SW_RESET_N")  # bits 6:0
SW_DEFAULT = SEP_RESET_CTRL.reset32("SW_RESET_N")
KM_BIT = 1 << IPRST["km"]

# Bench isolate index (env/sep_reset_taps.py) of the paths each domain isolates:
# the table of paths isolated before each software reset.
X = {name: i for i, name in enumerate(ISO_BENCH)}
HOST = {
    "otbn": ("host_otbn",),
    "aes": ("host_aes",),
    "hmac": ("host_hmac",),
    "kmac": ("host_kmac",),
    "abr": ("host_abr",),
    "trng": ("trng_entropy_source", "trng_csrng", "trng_edn"),
    "km": (),
}
KEYP = {
    "otbn": ("km_otbn",),
    "aes": ("km_aes",),
    "hmac": ("km_hmac",),
    "kmac": ("km_kmac",),
    "abr": ("km_abr",),
    "trng": (),
    "km": ("km_otbn", "km_aes", "km_hmac", "km_kmac", "km_abr", "km_efuse"),
}


def _mask(names) -> int:
    return sum(1 << X[n] for n in names)


TABLE = {d: _mask(HOST[d] + KEYP[d]) for d in (*DOMS, "km")}
HOST_MASK = {d: _mask(HOST[d]) for d in (*DOMS, "km")}
KM_SET = TABLE["km"]  # bench indices 8 to 13
KM_KEY_HKA = _mask(("km_hmac", "km_kmac", "km_abr"))

_BY_NAME = {p.name: p for p in PROBES}


def _probe_at(name: str, addr: int) -> ResetProbe:
    width, fields = register_fields(addr)
    mask = sum(((1 << f.width) - 1) << f.lsb for f in fields) & 0xFFFF_FFFF
    return ResetProbe(name, addr, word_reset(addr) & 0xFFFF_FFFF, mask)


ESRC_PROBE = _probe_at("esrc", sym("ENTROPY_SOURCE_INTR_ENABLE_REG_ADDR"))
MBOX_PROBE = _probe_at("mbox_in0_wirqt", sym("AXIL_MAILBOX_INBOUND_MAILBOX_0_WIRQT_REG_ADDR"))
# WIRQT stores a value below MailboxDepth and reduces a larger one to
# MailboxDepth - 1 (hw/ip/axi_lite_mailbox_unit/regs/gen/adoc/axil_mailbox.adoc,
# WIRQT); a mailbox FIFO holds eight entries (hw/sys/sep/doc/mailbox.adoc), so the
# armed values stay in 1..7.
MBOX_DRAW_MASK = 0x7
# Leg A engine probe of each domain (TRNG: CSRNG INTR_ENABLE).
PROBE = {d: _BY_NAME["csrng" if d == "trng" else d] for d in DOMS}
# Leg B probes of each domain: TRNG arms one register each in ESRC, CSRNG and EDN.
PROBES_B = {d: (PROBE[d],) for d in DOMS}
PROBES_B["trng"] = (ESRC_PROBE, _BY_NAME["csrng"], _BY_NAME["edn"])
SCRATCH = (
    ResetProbe("scratch_cold0", SCRATCH_COLD_0, SCRATCH_RESET_DEFAULT, 0xFFFF_FFFF),
    ResetProbe("scratch_warm0", SCRATCH_WARM_0, SCRATCH_RESET_DEFAULT, 0xFFFF_FFFF),
)
UNRELATED = (_BY_NAME["spi"], _BY_NAME["dma"], MBOX_PROBE, *SCRATCH)
ALL_PROBES = (*{p.name: p for d in DOMS for p in PROBES_B[d]}.values(), *UNRELATED)

# Decoded registers of each domain for the isolated-window reads.
WINDOW_REGS = {
    "otbn": (OTBN.addr("STATUS"), OTBN.addr("LOAD_CHECKSUM"), OTBN.addr("ERR_BITS")),
    "aes": (AES.addr("STATUS"), AES.addr("CTRL_AUX_SHADOWED"), AES.addr("CTRL_AUX_REGWEN")),
    "hmac": (HMAC.addr("CFG"), HMAC.addr("INTR_ENABLE"), HMAC.addr("STATUS")),
    "kmac": (KMAC.addr("STATUS"), KMAC.addr("ENTROPY_PERIOD"), KMAC.addr("CFG_REGWEN")),
    "abr": (ABR_INTR, _BY_NAME["abr"].addr),
    "trng": tuple(p.addr for p in PROBES_B["trng"]),
}

# Never-isolated ports (memory_map.adoc): name -> (address, OKAY required).
NEVER = {
    "ext_trng": (sym("TRNG_REG_MAP_BASE_ADDR"), False),
    "km_mbox": (KM_MBOX_BASE + KM_MBOX_STATUS, True),
    "efuse": (sym("EFUSE_INTERFACE_CTRL_EFUSE_INTERFACE_CTRL_STATUS_REG_ADDR"), True),
    "lifecycle": (sym("SEP_LIFECYCLE_CTRL_FEAT_CTRL_REG_ADDR"), True),
    "pool": (sym("ENTROPY_POOL_STATUS_REG_ADDR"), True),
}

# Environment choices, clk_i cycles.
REL_ALLOW = 4  # isolate-complete fall against the ip_rst_n rise (CHK-ISO-REL)
TAP_BOUND = 4_000
DRAIN_BOUND = 4_000
KM_BOUND = 20_000
N_VALUES = 4
HOST_IDS = (1, 2, 3, 4)
SW_ID = 0

SIZES = (1, 2, 4, 8)
_SIZE_CODE = {1: 0, 2: 1, 4: 2, 8: 3}


# Reserved bits start above the last SW_RESET_N field.
RSVD_LSB = SW_FIELDS.bit_length()
RSVD_W64 = 64 - RSVD_LSB
RSVD_W32 = 32 - RSVD_LSB


def _rsvd_w64(rng) -> int:
    v = 0
    while v == 0:
        v = rng.getrandbits(RSVD_W64)
    return v


def _rsvd_w32(rng) -> int:
    v = 0
    while v == 0:
        v = rng.getrandbits(RSVD_W32)
    return v


@dataclass
class StepDraw:
    idx: int
    doms: tuple[str, ...]
    style: str  # "one" or "per"
    spacing: int
    shapes: list[str] = field(default_factory=list)  # per write: "w64" or "lo32"
    rsvd: list[int] = field(default_factory=list)  # per write: reserved bits


@dataclass
class PassDraw:
    name: str
    victims: tuple[str, ...]
    order: str  # "fwd" or "rev" for a pair, "single" otherwise
    gap: int
    n_txn: int
    ops: list[str]
    delay: int
    reads: list[tuple[int, int]]  # (size, addr)
    writes: list[tuple[int, int, int]]  # (size, addr, data)
    hold: int
    never: str


class Plan:
    """Every draw of the leaf, in the order of the contract, logged as DRAW lines."""

    def __init__(self, seed: int) -> None:
        rng = SepSeededRng(seed)
        self.lines: list[str] = []
        # Leg A: partition, order, style, spacing, reserved bits, shapes.
        while True:
            doms = list(DOMS)
            rng.shuffle(doms)
            k = rng.randrange(1, len(DOMS))  # 1..5 subsets, so one has |S| >= 2
            cuts = sorted(rng.sample(range(1, len(DOMS)), k - 1))
            parts, prev = [], 0
            for c in [*cuts, len(DOMS)]:
                parts.append(tuple(doms[prev:c]))
                prev = c
            if any(len(p) >= 2 for p in parts):
                break
        rng.shuffle(parts)
        self.steps: list[StepDraw] = []
        for i, s in enumerate(parts):
            style = rng.choice(("one", "per")) if len(s) >= 2 else "one"
            self.steps.append(StepDraw(i, s, style, rng.randrange(0, 9)))
        multi = [st for st in self.steps if len(st.doms) >= 2]
        if not any(st.style == "one" for st in multi):
            multi[0].style = "one"
        for st in self.steps:
            n_writes = 2 * (1 if st.style == "one" else len(st.doms))
            for _ in range(n_writes):
                shape = rng.choice(("w64", "lo32"))
                st.shapes.append(shape)
                st.rsvd.append(_rsvd_w64(rng) if shape == "w64" else _rsvd_w32(rng))
            self.lines.append(
                f"DRAW legA step={st.idx} S={','.join(st.doms)} style={st.style} "
                f"spacing={st.spacing} shapes={','.join(st.shapes)} "
                f"rsvd={','.join(hex(r) for r in st.rsvd)}"
            )
        self.rsvd_leg = {"w64": _rsvd_w64(rng), "hi32": 0, "lo32": _rsvd_w32(rng)}
        while self.rsvd_leg["hi32"] == 0:
            self.rsvd_leg["hi32"] = rng.getrandbits(32)
        self.lines.append(
            "DRAW legA rsvd_only " + " ".join(f"{k}=0x{v:x}" for k, v in self.rsvd_leg.items())
        )
        # Leg B: per-domain pass draws, then the pairs.
        self.passes: dict[str, PassDraw] = {}
        for d in DOMS:
            if d == "trng":
                continue
            self.passes[d] = self._pass_draw(rng, d, (d,), "single", 0)
        engines = ("otbn", "aes", "hmac", "kmac", "abr")
        first_fwd = rng.choice((True, False))
        for i in range(2):
            a, b = rng.sample(list(engines), 2)
            order = "fwd" if (i == 0) == first_fwd else "rev"
            gap = rng.randrange(0, 9)
            self.passes[f"pair{i}"] = self._pass_draw(rng, f"pair{i}", (a, b), order, gap)
        self.km_hold = rng.randrange(1, 201)
        self.lines.append(f"DRAW legB km hold={self.km_hold}")
        self.passes["trng"] = self._pass_draw(rng, "trng", ("trng",), "single", 0)
        # Armed values: non-default, each different from the one before it.
        self.values: dict[str, list[int]] = {}
        for p in ALL_PROBES:
            vals: list[int] = []
            draw_mask = MBOX_DRAW_MASK if p is MBOX_PROBE else p.mask
            for _ in range(N_VALUES):
                vals.append(other_value(rng, draw_mask, (p.reset, *vals[-1:])))
            self.values[p.name] = vals
            self.lines.append(
                f"DRAW armed {p.name} @0x{p.addr:08x} = "
                + ",".join(f"0x{x:08x}" for x in vals)
                + f" (RDL reset 0x{p.reset:08x})"
            )

    def _pass_draw(self, rng, name, victims, order, gap) -> PassDraw:
        d = victims[0]
        n_txn = rng.randrange(1 if d in ("otbn", "aes") else 0, 5)
        ops = [rng.choice(("rd", "wr")) for _ in range(n_txn)]
        if d in ("otbn", "aes") and "rd" not in ops:
            ops[0] = "rd"
        delay = rng.randrange(0, 7)
        sizes = list(SIZES)
        rng.shuffle(sizes)
        reads = []
        for i, s in enumerate(sizes):
            if d == "trng":
                addr = WINDOW_REGS[d][i % len(WINDOW_REGS[d])]
            else:
                addr = rng.choice(WINDOW_REGS[d])
            reads.append((s, addr & ~(s - 1)))
        if d == "trng":
            # One 4-byte read in each of ESRC, CSRNG and EDN.
            reads += [(4, a) for a in WINDOW_REGS[d] if (4, a) not in reads]
        probe = PROBES_B[d][0]
        writes = []
        for s in (4, rng.choice(SIZES)):
            val = other_value(rng, probe.mask, (probe.reset,))
            addr = probe.addr & ~(s - 1)
            lane = (probe.addr - addr) * 8
            writes.append((s, addr, (val << lane) & ((1 << (8 * s)) - 1)))
        hold = rng.randrange(1, 201)
        ports = ["ext_trng", "efuse", "lifecycle"] + (["pool"] if d == "trng" else ["km_mbox"])
        never = rng.choice(ports)
        pd = PassDraw(name, victims, order, gap, n_txn, ops, delay, reads, writes, hold, never)
        self.lines.append(
            f"DRAW legB pass={name} victims={','.join(victims)} order={order} gap={gap} "
            f"txn={n_txn}:{','.join(ops)} delay={delay} "
            f"reads={','.join(f'{s}@0x{a:08x}' for s, a in reads)} "
            f"writes={','.join(f'{s}@0x{a:08x}=0x{v:x}' for s, a, v in writes)} "
            f"hold={hold} never={never}"
        )
        return pd


# 64-bit isolated host ports (memory_map.adoc windows); a read covers the high lane
# when it reaches address bit 2 = 1 of the 8-byte word.
def _aperture(base: int) -> tuple[int, int]:
    """``(base, aperture size)`` of the generated memory-map row that starts at ``base``."""
    for row in sep_map_rows():
        if row.base == base:
            return base, row.end - row.base + 1
    raise KeyError(f"no sep-components memory-map row starts at 0x{base:08x}")


WIDE_PORTS = {
    "csrng": _aperture(sym("CSRNG_REG_MAP_BASE_ADDR")),
    "edn": _aperture(sym("EDN_REG_MAP_BASE_ADDR")),
    "abr": _aperture(sym("ABR_REG_MAP_BASE_ADDR")),
}
_ISO_BYTES = ISO_DATA.to_bytes(4, "little")


def iso_lanes(size: int, addr: int, rdata: int, resp: int) -> list[tuple]:
    """``(size, lane address, got, expected, ok)`` for every 32-bit lane a read covers.

    The expected bytes of a lane are those of 0x1501A7ED at the same byte offsets
    (reset_controller.adoc, Isolation and Reset Sequencing, step 2), and the read
    answers SLVERR.
    """
    raw = rdata.to_bytes(size, "little")
    out = []
    for lane in range(addr & ~3, addr + size, 4):
        lo, hi = max(addr, lane), min(addr + size, lane + 4)
        got = int.from_bytes(raw[lo - addr : hi - addr], "little")
        exp = int.from_bytes(_ISO_BYTES[lo - lane : hi - lane], "little")
        out.append((size, lane, got, exp, got == exp and resp == RESP_SLVERR))
    return out


def high_lane_ports(reads) -> dict[str, bool]:
    """For each 64-bit port a pass reads, whether one read covers its high lane."""
    out: dict[str, bool] = {}
    for size, addr in reads:
        for name, (base, span) in WIDE_PORTS.items():
            if base <= addr < base + span:
                out[name] = out.get(name, False) or ((addr + size - 1) & 4) != 0
    return out


class IsoSlvLog:
    """Per-clock record of the isolate-stage slave-side taps, in the bench index.

    Reads ``iso_slv_{aw,ar,b,r}_hs_probe_o`` and the response codes on every rising
    edge of ``clk_i`` in the read-only phase and drives nothing. A handshake is one
    clock with valid and ready high, so every high clock is recorded. ``clk`` counts
    the sampled edges from ``start``.
    """

    CH = ("aw", "ar", "b", "r")

    def __init__(self, dut) -> None:
        self.dut = dut
        self.clk = 0
        self.ev: list[tuple[int, str, int, int]] = []  # (clk, ch, bench stage, resp)
        self._task = None

    async def _run(self) -> None:
        d = self.dut
        sig = {ch: getattr(d, f"iso_slv_{ch}_hs_probe_o") for ch in self.CH}
        resp = {"b": d.iso_slv_bresp_probe_o, "r": d.iso_slv_rresp_probe_o}
        while True:
            await RisingEdge(d.clk_i)
            await ReadOnly()
            self.clk += 1
            for ch in self.CH:
                v = sig[ch].value
                if not v.is_resolvable:
                    raise AssertionError(f"iso_slv_{ch}_hs_probe_o is X/Z at clock {self.clk}")
                v = int(v)
                if not v:
                    continue
                codes = -1
                if ch in resp and resp[ch].value.is_resolvable:
                    codes = int(resp[ch].value)
                for x in range(ISO_WIDTH):
                    if (v >> iso_rtl_bit(x)) & 1:
                        code = (codes >> (2 * iso_rtl_bit(x))) & 3 if codes >= 0 else -1
                        self.ev.append((self.clk, ch, x, code))

    def start(self) -> "IsoSlvLog":
        self._task = cocotb.start_soon(self._run())
        return self

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def since(self, start: int, stages: int, off: int) -> dict[str, list]:
        """Handshake clocks (tap clock) of ``stages`` after ``start``, per channel."""
        out: dict[str, list] = {ch: [] for ch in self.CH}
        out["bresp"], out["rresp"] = [], []
        for c, ch, x, code in self.ev:
            tc = c - off
            if tc <= start or not (stages >> x) & 1:
                continue
            out[ch].append(tc)
            if ch in ("b", "r"):
                out[f"{ch}resp"].append(RESP_NAME.get(code, code))
        return out


class PassView:
    """Queries over the shared tap and channel watchers from one mark, in tap clocks.

    ``SepResetTaps`` records every edge of the isolate vectors and of
    ``ip_rst_n``; ``SepAxiChanMon`` records every ``s_axi`` handshake. Both run
    for the whole leaf. ``off`` is the constant difference between the channel
    monitor clock and the tap clock, measured once in the read-only phase.
    """

    def __init__(self, taps: SepResetTaps, chan: SepAxiChanMon, off: int) -> None:
        self.taps = taps
        self.chan = chan
        self.off = off
        self.m = taps.mark()
        self.cm = chan.mark()

    @property
    def cyc(self) -> int:
        return self.taps.iso_req.clk

    def beats(self, ch: str, ids=None) -> list[tuple[int, int, int | None]]:
        """``(tap clock, id, resp)`` of every ``ch`` handshake after the mark."""
        return [
            (b.clk - self.off, b.axi_id, b.resp)
            for b in self.chan.since(self.cm, ch)
            if ids is None or b.axi_id in ids
        ]

    def _bits(self, mask: int) -> list[int]:
        return [x for x in range(ISO_WIDTH) if (mask >> x) & 1]

    def _first_rise(self, w, mask: int, after: int) -> int | None:
        """Clock at which every bit of ``mask`` has risen after ``after`` (None if one never did)."""
        out = []
        for x in self._bits(mask):
            r = [c for c in w.rise_clks_since(self.m[w.name], iso_name(x)) if c > after]
            if not r:
                return None
            out.append(r[0])
        return max(out) if out else None

    def _first_fall(self, w, mask: int, after: int) -> int | None:
        out = []
        for x in self._bits(mask):
            f = [c for c in w.fall_clks_since(self.m[w.name], iso_name(x)) if c > after]
            if not f:
                return None
            out.append(f[0])
        return max(out) if out else None

    def req_rise(self, mask: int, after: int = 0) -> int | None:
        return self._first_rise(self.taps.iso_req, mask, after)

    def ack_rise(self, mask: int, after: int = 0) -> int | None:
        return self._first_rise(self.taps.iso_ack, mask, after)

    def ack_fall(self, mask: int, after: int) -> int | None:
        return self._first_fall(self.taps.iso_ack, mask, after)

    def req_rose(self) -> int:
        """Bits of the isolate request vector that rose after the mark."""
        w = self.taps.iso_req
        return sum(
            1 << x for x in range(ISO_WIDTH) if w.rises_since(self.m["iso_req"], iso_name(x))
        )

    def ip_fall(self, i: int) -> int | None:
        w = self.taps.ip_rst[i]
        f = w.fall_clks_since(self.m[f"ip_rst_{i}"])
        return f[0] if f else None

    def ip_rise_after(self, i: int, c: int) -> int | None:
        w = self.taps.ip_rst[i]
        r = [x for x in w.rise_clks_since(self.m[f"ip_rst_{i}"]) if x > c]
        return r[0] if r else None


@pyuvm.test()
class sep_sw_reset_isolation_matrix_test(sep_base_test):
    """SW_RESET_N subsets, reserved bits, and the isolation sequence of every domain."""

    required_evidence = (
        "CHK-SUBSET",
        "CHK-SUBSET-COVER",
        "CHK-SWRST-RSVD",
        "CHK-SWRST-SCOPE",
        "CHK-ISO-RESP",
        "CHK-ISO-REL",
        "CHK-ISO-NEVER",
        "CHK-ISO-PAIR",
        "CHK-ISO-ORDER",
        "CHK-ISO-DRAIN",
        "CHK-ISO-PATHS",
    )

    # ---- log helpers --------------------------------------------------------
    def _chk(self, chk: str, ok: bool, values: str) -> None:
        line = f"{chk} {'PASS' if ok else 'FAIL'}: {values}"
        if not ok:
            self.logger.error(line)
            raise AssertionError(line)
        self.logger.info(line)
        self.k += 1

    def _chk_late(self, chk: str, ok: bool, values: str) -> None:
        """A checker whose FAIL ends the leaf after the remaining checks have run."""
        line = f"{chk} {'PASS' if ok else 'FAIL'}: {values}"
        if not ok:
            self.logger.error(line)
            self.late_fail.append(line)
            return
        self.logger.info(line)
        self.k += 1

    async def _gate(self, on: bool) -> None:
        """Write the graded-window gate outside the read-only phase of a clock."""
        await NextTimeStep()
        if on:
            open_graded_window(TEST, self.logger)
        else:
            close_graded_window(self.logger)

    def _ctl(self, ctl: str, ok: bool, values: str) -> None:
        if not ok:
            self.logger.error("%s FAIL (control not met): %s", ctl, values)
            raise AssertionError(f"{ctl} control not met: {values}")
        self.logger.info("%s: %s", ctl, values)

    async def _cycles(self, n: int) -> None:
        for _ in range(n):
            await RisingEdge(cocotb.top.clk_i)

    # ---- register access ----------------------------------------------------
    async def _acc(self, op: SepAxiOp, addr: int, size: int, data: int = 0) -> SepAxiAccessSeq:
        """One access of ``size`` bytes whose response the leaf grades itself."""
        seq = SepAxiAccessSeq(
            f"swiso_{op.value}_0x{addr:08x}_{size}",
            op=op,
            addr=addr,
            wdata=data,
            length=size,
            size=_SIZE_CODE[size],
            allow_unverified_write_resp=op is SepAxiOp.WRITE,
            allow_ungraded_read_resp=op is SepAxiOp.READ,
        )
        await self.start_seq(seq)
        if seq.timed_out:
            raise AssertionError(f"{op.value} @0x{addr:08x} size={size} got no response")
        return seq

    async def _sw_read64(self) -> int:
        seq = await self._acc(SepAxiOp.READ, SW, 8)
        if seq.resp_code != RESP_OKAY:
            raise AssertionError(f"SW_RESET_N 64-bit read resp={RESP_NAME[seq.resp_code]}")
        return int(seq.rdata)

    async def _arm(self, p: ResetProbe, idx: int = 0) -> None:
        val = self.plan.values[p.name][idx % N_VALUES]
        await self.pd.write(p, val)
        got = await self.pd.read(p)
        fc = field_compare(got, val, p.mask)
        if not fc.ok or (val & p.mask) == (p.reset & p.mask):
            raise AssertionError(f"arm {p.name}: {fc.fields()} RDL reset 0x{p.reset:08x}")
        self.armed[p.name] = val

    async def _read(self, p: ResetProbe) -> tuple[int, int]:
        seq = await self._acc(SepAxiOp.READ, p.addr, 4)
        return seq.resp_code, int(seq.rdata) & 0xFFFF_FFFF

    async def _expect(self, p: ResetProbe, want: int) -> tuple[bool, str]:
        resp, got = await self._read(p)
        fc = field_compare(got, want, p.mask)
        return resp == RESP_OKAY and fc.ok, f"{p.name} resp={RESP_NAME[resp]} {fc.fields()}"

    def _ip(self, i: int) -> int:
        return self.rd_known(getattr(cocotb.top, IP_RST_PORTS[i]))

    async def _wait_ip(self, i: int, level: int, what: str) -> None:
        try:
            await self.taps.ip_rst[i].wait_level(level, TAP_BOUND)
        except AssertionError as exc:
            raise AssertionError(f"{what}: ip_rst_n[{i}] {exc}") from exc

    # ---- scenario -----------------------------------------------------------
    async def run_scenario(self) -> None:
        self.seed = self.random_seed()
        self.k = 0
        self.plan = Plan(self.seed)
        self.logger.info("SEED %s seed=%d", TEST, self.seed)
        for line in self.plan.lines:
            self.logger.info(line)
        self.logger.info(
            "ENV rel_allow=%d tap_bound=%d drain_bound=%d km_bound=%d (clk_i cycles)",
            REL_ALLOW,
            TAP_BOUND,
            DRAIN_BOUND,
            KM_BOUND,
        )
        await self.bring_up_no_cpu()
        dut = cocotb.top
        self.taps = SepResetTaps(dut).start()
        self.chan = SepAxiChanMon("s_axi", dut).start()
        self.isolog = IsoSlvLog(dut).start()
        self.taps.log_map(self.logger)
        self.late_fail: list[str] = []
        self.pd = SepResetProbeDriver(self)
        self.axi = self.env.axi_agent.driver.axi
        self.hold = SepAxiReadyHold(self, "s_axi")
        self.armed: dict[str, int] = {}
        try:
            sw0 = await self._sw_read64()
            self._ctl(
                "CTL-SWRST-FIRST",
                (sw0 & SW_FIELDS) == SW_DEFAULT,
                f"SW_RESET_N=0x{sw0:016x} fields=0x{sw0 & SW_FIELDS:02x}",
            )
            self.sw = sw0 & SW_FIELDS
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            self.off = self.chan.clk - self.taps.iso_req.clk
            self.iso_off = self.isolog.clk - self.taps.iso_req.clk
            self.logger.info(
                "OBS-CLOCKS: chan_mon_clk=%d tap_clk=%d offset=%d iso_stage_offset=%d",
                self.chan.clk,
                self.taps.iso_req.clk,
                self.off,
                self.iso_off,
            )
            await FallingEdge(dut.clk_i)
            await self._leg_a()
            await self._leg_b()
        finally:
            self.hold.release_all()
            await self._gate(False)
            await self.taps.stop()
            await self.chan.stop()
            await self.isolog.stop()
        if self.late_fail:
            raise AssertionError("; ".join(self.late_fail))
        self.logger.info("RESULT %s seed=%d PASS checks=%d", TEST, self.seed, self.k)

    # ---- leg A --------------------------------------------------------------
    async def _leg_a(self) -> None:
        for d in DOMS:
            await self._arm(PROBE[d])
        for p in UNRELATED:
            await self._arm(p)
        await self._gate(True)
        scope = await self._rsvd_leg()
        falls: dict[str, int] = {d: 0 for d in DOMS}
        for st in self.plan.steps:
            if len(st.doms) == 1:
                await self._gate(False)
            m = self.taps.mark()
            await self._subset_step(st)
            for d in DOMS:
                falls[d] += len(self.taps.ip_rst[IPRST[d]].fall_clks_since(m[f"ip_rst_{IPRST[d]}"]))
            if scope is not None:
                moved = [
                    (
                        d,
                        self.taps.ip_rst[IPRST[d]].fall_clks_since(m[f"ip_rst_{IPRST[d]}"]),
                        self.taps.ip_rst[IPRST[d]].rise_clks_since(m[f"ip_rst_{IPRST[d]}"]),
                    )
                    for d in st.doms
                ]
                d0, fl, rs = moved[0]
                self._chk(
                    "CHK-SWRST-SCOPE",
                    scope["ok"] and bool(fl) and bool(rs),
                    f"taps stable 0b{scope['taps']:06b} over {scope['cycles']} cycles "
                    f"(edges={scope['edges']}) unrelated_regs_unchanged="
                    f"{scope['kept']}/{scope['n']} control tap moved dom={d0} "
                    f"fall={fl[0] if fl else -1} rise={rs[0] if rs else -1}",
                )
                scope = None
            await self._gate(True)
        self._chk(
            "CHK-SUBSET-COVER",
            all(falls[d] >= 1 for d in DOMS),
            f"all six domains asserted at least once steps={len(self.plan.steps)} "
            + " ".join(f"{d}_falls={falls[d]}" for d in DOMS),
        )

    async def _rsvd_leg(self) -> dict:
        """Step 3: bits 63:7 in the three shapes; nothing moves."""
        before = await self._sw_read64()
        fields = before & SW_FIELDS
        m = self.taps.mark()
        n_resp = 0
        for shape in ("w64", "hi32", "lo32"):
            rs = self.plan.rsvd_leg[shape]
            if shape == "w64":
                seq = await self._acc(SepAxiOp.WRITE, SW, 8, (rs << RSVD_LSB) | fields)
                hi = rs
            elif shape == "hi32":
                seq = await self._acc(SepAxiOp.WRITE, SW + 4, 4, rs)
                hi = rs << RSVD_W32
            else:
                seq = await self._acc(SepAxiOp.WRITE, SW, 4, (rs << RSVD_LSB) | fields)
                hi = rs
            n_resp += 1
            rb = await self._sw_read64()
            self._chk(
                "CHK-SWRST-RSVD",
                (rb & SW_FIELDS) == fields,
                f"leg=rsvd shape={shape} n=1 writes responses=1 (resp={RESP_NAME[seq.resp_code]}) "
                f"hi=0x{hi:x} written_fields=0b{fields:07b} readback_fields=0b{rb & SW_FIELDS:07b} "
                f"readback_resp=OKAY",
            )
            self.logger.info(
                "OBS-SWRST-RSVD: leg=rsvd shape=%s bits63:7=0x%x", shape, rb >> RSVD_LSB
            )
        await RisingEdge(cocotb.top.clk_i)
        cycles = self.taps.ip_rst[1].clk - m["ip_rst_1"].clk
        edges = sum(
            self.taps.ip_rst[IPRST[d]].rises_since(m[f"ip_rst_{IPRST[d]}"])
            + len(self.taps.ip_rst[IPRST[d]].fall_clks_since(m[f"ip_rst_{IPRST[d]}"]))
            for d in DOMS
        )
        taps = sum(self._ip(IPRST[d]) << i for i, d in enumerate(DOMS))
        kept = 0
        regs = (*(PROBE[d] for d in DOMS), *UNRELATED)
        for p in regs:
            ok, _ = await self._expect(p, self.armed[p.name])
            kept += int(ok)
        return {
            "ok": edges == 0 and kept == len(regs) and taps == 0b111111,
            "taps": taps,
            "cycles": cycles,
            "edges": edges,
            "kept": kept,
            "n": len(regs),
        }

    def _sw_word(self, shape: str, rsvd: int) -> tuple[int, int, int]:
        """(address, size, data) of a field write in ``shape`` with reserved bits."""
        if shape == "w64":
            return SW, 8, (rsvd << RSVD_LSB) | self.sw
        return SW, 4, ((rsvd << RSVD_LSB) | self.sw) & 0xFFFF_FFFF

    async def _issue_writes(self, words: list[tuple[int, int, int]], spacing: int) -> list:
        evs = []
        for i, (addr, size, data) in enumerate(words):
            if i and spacing:
                await self._cycles(spacing)
            evs.append(
                self.axi.init_write(
                    address=addr,
                    data=data.to_bytes(size, "little"),
                    size=_SIZE_CODE[size],
                    awid=SW_ID,
                )
            )
        for ev in evs:
            await ev.wait()
        return evs

    async def _subset_step(self, st: StepDraw) -> None:
        wi = 0
        for phase, level in (("assert", 0), ("release", 1)):
            words = []
            fields_seq = []
            group = [st.doms] if st.style == "one" else [(d,) for d in st.doms]
            for g in group:
                for d in g:
                    if level:
                        self.sw |= 1 << IPRST[d]
                    else:
                        self.sw &= ~(1 << IPRST[d])
                words.append(self._sw_word(st.shapes[wi], st.rsvd[wi]))
                fields_seq.append(self.sw)
                wi += 1
            if st.style == "per":
                # One write per domain: read SW_RESET_N back after each write's
                # response and grade it against the fields of that write, then wait
                # the drawn spacing before the next write.
                evs = []
                for k, (word, fields_k) in enumerate(zip(words, fields_seq)):
                    if k and st.spacing:
                        await self._cycles(st.spacing)
                    ev = (await self._issue_writes([word], 0))[0]
                    evs.append(ev)
                    code = (
                        int(max(ev.data.resp))
                        if isinstance(ev.data.resp, (list, tuple))
                        else int(ev.data.resp)
                    )
                    rbk = await self._sw_read64()
                    self._chk(
                        "CHK-SWRST-RSVD",
                        (rbk & SW_FIELDS) == fields_k,
                        f"leg=subset step={st.idx} phase={phase} write={k + 1}/{len(words)} "
                        f"n=1 writes responses=1 ({RESP_NAME.get(code, str(code))}) "
                        f"hi=0x{(word[2] >> RSVD_LSB):x} written_fields=0b{fields_k:07b} "
                        f"readback_fields=0b{rbk & SW_FIELDS:07b}",
                    )
                    self.logger.info(
                        "OBS-SWRST-RSVD: leg=subset step=%d phase=%s write=%d bits63:7=0x%x",
                        st.idx,
                        phase,
                        k + 1,
                        rbk >> RSVD_LSB,
                    )
            else:
                evs = await self._issue_writes(words, st.spacing)
            codes = [
                int(max(ev.data.resp))
                if isinstance(ev.data.resp, (list, tuple))
                else int(ev.data.resp)
                for ev in evs
            ]
            rb = await self._sw_read64()
            his = ",".join(f"0x{(w[2] >> RSVD_LSB):x}" for w in words)
            self._chk(
                "CHK-SWRST-RSVD",
                (rb & SW_FIELDS) == self.sw,
                f"leg=subset step={st.idx} phase={phase} n={len(words)} writes "
                f"responses={len(codes)} ({','.join(RESP_NAME.get(c, str(c)) for c in codes)}) "
                f"hi={his} written_fields=0b{self.sw:07b} readback_fields=0b{rb & SW_FIELDS:07b}",
            )
            self.logger.info(
                "OBS-SWRST-RSVD: leg=subset step=%d phase=%s bits63:7=0x%x",
                st.idx,
                phase,
                rb >> RSVD_LSB,
            )
            for d in st.doms:
                await self._wait_ip(IPRST[d], level, f"step {st.idx} {phase} {d}")
        # Probes and unrelated registers.
        n_reset = n_kept = 0
        bad = []
        for d in DOMS:
            p = PROBE[d]
            want = p.reset if d in st.doms else self.armed[p.name]
            ok, desc = await self._expect(p, want)
            if d in st.doms:
                n_reset += int(ok)
            else:
                n_kept += int(ok)
            if not ok:
                bad.append(desc)
        for p in UNRELATED:
            ok, desc = await self._expect(p, self.armed[p.name])
            n_kept += int(ok)
            if not ok:
                bad.append(desc)
        n_other = len(DOMS) - len(st.doms) + len(UNRELATED)
        s_bits = sum(1 << IPRST[d] for d in st.doms)
        vals = (
            f"step={st.idx} S=0b{s_bits:07b} probes_reset={n_reset}/{len(st.doms)} "
            f"others_retained={n_kept}/{n_other} style={st.style} spacing={st.spacing}"
            + (f" mismatch={bad}" if bad else "")
        )
        ok = n_reset == len(st.doms) and n_kept == n_other
        if len(st.doms) >= 2:
            self._chk("CHK-SUBSET", ok, vals)
        else:
            self._ctl("CTL-SUBSET", ok, vals)
        for d in st.doms:
            await self._arm(PROBE[d], 1)

    # ---- leg B --------------------------------------------------------------
    async def _leg_b(self) -> None:
        from seq_lib.sep_km_mem_smoke_seq import SW_RESET_N_RELEASE_KM, sep_km_release_seq

        for d in DOMS:
            for p in PROBES_B[d]:
                if p.name not in self.armed:
                    await self._arm(p)
        await self.start_seq(sep_km_release_seq("km_release"))
        self.sw = SW_RESET_N_RELEASE_KM & SW_FIELDS
        await self._wait_ip(IPRST["km"], 1, "Key Manager release")
        await self._wait_ack(KM_KEY_HKA, 0, "Key Manager key paths after release")
        await self._calibrate_drain_placement()
        for name in ("otbn", "aes", "hmac", "kmac", "abr", "pair0", "pair1"):
            await self._pass(self.plan.passes[name])
        await self._km_pass()
        # TRNG baseline: the Key Manager held.
        await self._sw_write_seq(self.sw & ~KM_BIT)
        await self._wait_ack(KM_KEY_HKA, 1, "Key Manager key paths after the hold")
        await self._wait_ip(IPRST["km"], 0, "Key Manager hold")
        await self._pass(self.plan.passes["trng"], baseline=KM_SET)
        await self._sw_write_seq(self.sw | KM_BIT)
        await self._wait_ip(IPRST["km"], 1, "Key Manager release after TRNG")

    async def _calibrate_drain_placement(self) -> None:
        """Latencies that place a host transaction at the isolate stage of OTBN and AES.

        ``lat_req``: clocks from the issue of a ``SW_RESET_N`` write to the rise of
        the host isolate request it causes (measured on HMAC, released again).
        ``lat_stage[(d, op)]``: clocks from the issue of a host read or write of D
        to its handshake at the slave side of D's host isolate stage. Placement
        values only, never expected values.
        """
        dut = cocotb.top
        await self._gate(False)
        await FallingEdge(dut.clk_i)
        m = self.taps.mark()
        c0 = self.taps.iso_req.clk
        ev = self._sw_issue(self.sw & ~(1 << IPRST["hmac"]))
        rise = await self.taps.iso_req.wait_rise(
            m["iso_req"], TAP_BOUND, bit=iso_name(X["host_hmac"])
        )
        self.lat_req = rise - c0
        await ev.wait()
        await self._wait_ip(IPRST["hmac"], 0, "drain calibration")
        await self._sw_write_seq(self.sw)
        await self._wait_ip(IPRST["hmac"], 1, "drain calibration release")
        await self._arm(PROBE["hmac"], 2)
        self.lat_stage: dict[tuple[str, str], int] = {}
        for d in ("otbn", "aes"):
            probe = PROBES_B[d][0]
            for op in ("rd", "wr"):
                await FallingEdge(dut.clk_i)
                start = self.taps.iso_req.clk
                c0 = start
                if op == "rd":
                    ev = self.axi.init_read(address=probe.addr, length=4, size=2, arid=HOST_IDS[0])
                else:
                    ev = self.axi.init_write(
                        address=probe.addr,
                        data=self.armed[probe.name].to_bytes(4, "little"),
                        size=2,
                        awid=HOST_IDS[0],
                    )
                await ev.wait()
                await self._cycles(4)
                ch = "ar" if op == "rd" else "aw"
                hs = self.isolog.since(start, HOST_MASK[d], self.iso_off)[ch]
                if not hs:
                    raise AssertionError(f"drain calibration: no {ch} handshake at the {d} stage")
                self.lat_stage[(d, op)] = hs[0] - c0
        self.logger.info(
            "CAL-DRAIN: issue_to_iso_req=%d issue_to_stage=%s",
            self.lat_req,
            ",".join(f"{d}/{op}:{v}" for (d, op), v in self.lat_stage.items()),
        )
        await self._gate(True)

    async def _sw_write_seq(self, value: int) -> None:
        seq = await self._acc(SepAxiOp.WRITE, SW, 4, value)
        if seq.resp_code != RESP_OKAY:
            raise AssertionError(f"SW_RESET_N write 0x{value:02x} resp={RESP_NAME[seq.resp_code]}")
        self.sw = value & SW_FIELDS

    async def _wait_ack(self, mask: int, level: int, what: str) -> None:
        for _ in range(KM_BOUND):
            await RisingEdge(cocotb.top.clk_i)
            await ReadOnly()
            v = self.taps.iso_ack_now()
            if v is not None and ((v & mask) == (mask if level else 0)):
                await FallingEdge(cocotb.top.clk_i)
                return
        raise AssertionError(f"{what}: isolate-complete bits 0x{mask:04x} did not read {level}")

    def _sw_issue(self, value: int):
        return self.axi.init_write(
            address=SW, data=(value & 0xFFFF_FFFF).to_bytes(4, "little"), size=2, awid=SW_ID
        )

    async def _pass(self, pd: PassDraw, baseline: int = 0) -> None:
        dut = cocotb.top
        victims = pd.victims
        d = victims[0]
        # Step 6: arm and read back the probes of the victims (path live).
        for v in victims:
            for p in PROBES_B[v]:
                await self._arm(p, 2)
        req0 = self.taps.iso_req_now()
        self._ctl(
            "CTL-ISO-BASELINE",
            req0 == baseline,
            f"pass={pd.name} iso_req=0x{req0 or 0:04x} baseline=0x{baseline:04x}",
        )
        await RisingEdge(dut.clk_i)
        view = PassView(self.taps, self.chan, self.off)
        hold_r = d in ("otbn", "aes")
        if hold_r:
            self.hold.hold("r")
        # Step 7: host transactions and the SW_RESET_N write(s). For OTBN and AES the
        # first host transaction is placed from the calibration so that the
        # isolate stage accepts it one clock before the isolate request rises, and
        # the SW_RESET_N write goes out first; the other domains take the drawn
        # delay after their transactions.
        host_evs = []
        probe = PROBES_B[d][0]

        def issue_host() -> None:
            for i, op in enumerate(pd.ops):
                tid = HOST_IDS[i]
                if op == "rd":
                    ev = self.axi.init_read(address=probe.addr, length=4, size=2, arid=tid)
                else:
                    ev = self.axi.init_write(
                        address=probe.addr,
                        data=self.armed[probe.name].to_bytes(4, "little"),
                        size=2,
                        awid=tid,
                    )
                host_evs.append((op, tid, ev))

        v1 = self.sw & ~(1 << IPRST[d])
        v2 = v1 & ~(1 << IPRST[victims[1]]) if len(victims) == 2 else v1
        sw_evs: list = []
        # Falling-edge offsets of the actions, relative to the first SW_RESET_N write.
        t_host = -pd.delay
        if hold_r:
            t_host = self.lat_req - 1 - self.lat_stage[(d, pd.ops[0])]
            self.logger.info(
                "DRAIN-PLACE: pass=%s first_op=%s host_issue_after_write=%d (drawn delay %d "
                "not used)",
                pd.name,
                pd.ops[0],
                t_host,
                pd.delay,
            )
        # At an equal offset the SW_RESET_N write goes first, so a host write cannot
        # queue ahead of it on the AW channel.
        actions = [(0, "sw1"), (t_host, "host")]
        if len(victims) == 2:
            actions.append((pd.gap, "sw2"))
        base = min(t for t, _ in actions)
        await FallingEdge(dut.clk_i)
        for t in range(max(t for t, _ in actions) - base + 1):
            for at, what in actions:
                if at - base != t:
                    continue
                if what == "host":
                    issue_host()
                elif what == "sw1":
                    sw_evs.insert(0, self._sw_issue(v1))
                else:
                    sw_evs.append(self._sw_issue(v2))
            await FallingEdge(dut.clk_i)
        self.sw = v2
        if hold_r:
            # The master takes R beats again once the isolate request of D reads 1.
            for _ in range(DRAIN_BOUND):
                await RisingEdge(dut.clk_i)
                await ReadOnly()
                if all(self.taps.iso_req.level(iso_name(x)) for x in view._bits(HOST_MASK[d])):
                    break
            else:
                raise AssertionError(f"pass={pd.name}: isolate request of {d} never rose")
            self.hold.release("r")
            await FallingEdge(dut.clk_i)
        # Step 8: every accepted transaction completes; the resets assert.
        for op, tid, ev in host_evs:
            for _ in range(DRAIN_BOUND):
                if ev.is_set():
                    break
                await RisingEdge(dut.clk_i)
            else:
                raise AssertionError(f"pass={pd.name}: host {op} id={tid} never completed")
        for ev in sw_evs:
            await ev.wait()
        for v in victims:
            await self._wait_ip(IPRST[v], 0, f"pass={pd.name} {v} reset")
        fall = {v: view.ip_fall(IPRST[v]) for v in victims}
        # Step 9: the isolated window.
        win = await self._window(pd)
        # Step 10: hold, release in the order of the pass, wait for the rise.
        while view.cyc < fall[d] + pd.hold:
            await RisingEdge(dut.clk_i)
        rel_order = list(victims) if pd.order != "rev" else list(reversed(victims))
        rel_evs = []
        rel_marks = []
        # The i-th release write is the i-th ID-0 AW handshake after this count, so
        # each victim is graded against its own write, also at a gap of 0 or 1.
        rel_base = len(view.beats("aw", (SW_ID,)))
        for i, v in enumerate(rel_order):
            if i:
                await self._cycles(pd.gap)
            self.sw |= 1 << IPRST[v]
            rel_marks.append((v, rel_base + i))
            rel_evs.append(self._sw_issue(self.sw))
        for ev in rel_evs:
            await ev.wait()
        for v in victims:
            await self._wait_ip(IPRST[v], 1, f"pass={pd.name} {v} release")
        set_all = 0
        for v in victims:
            set_all |= TABLE[v]
        await self._wait_ack(set_all & ~baseline, 0, f"pass={pd.name} isolate-complete release")
        await self._cycles(REL_ALLOW + 2)
        await self._grade_pass(pd, view, host_evs, fall, rel_marks, win, baseline)

    async def _window(self, pd: PassDraw) -> dict:
        res = {"rd4": [], "slverr": 0, "n": 0, "other": [], "writes": 0, "lanes": []}
        for size, addr in pd.reads:
            seq = await self._acc(SepAxiOp.READ, addr, size)
            res["n"] += 1
            res["slverr"] += int(seq.resp_code == RESP_SLVERR)
            res["lanes"] += iso_lanes(size, addr, int(seq.rdata), seq.resp_code)
            if size == 4:
                res["rd4"].append((addr, int(seq.rdata) & 0xFFFF_FFFF, seq.resp_code))
            else:
                res["other"].append(
                    f"{size}B@0x{addr:08x}={int(seq.rdata):#x}/{RESP_NAME[seq.resp_code]}"
                )
        for size, addr, data in pd.writes:
            seq = await self._acc(SepAxiOp.WRITE, addr, size, data)
            res["n"] += 1
            res["writes"] += 1
            res["slverr"] += int(seq.resp_code == RESP_SLVERR)
        if pd.victims[0] == "abr":
            # The open owners grade the SLVERR answer of an MLKEM_STATUS read in the
            # isolated window; this leaf logs it.
            seq = await self._acc(SepAxiOp.READ, ABR_MLKEM_STATUS, 4)
            self.logger.info(
                "CTL-ISO-RESP: dom=abr reg=MLKEM_STATUS resp=%s rdata=0x%08x",
                RESP_NAME[seq.resp_code],
                int(seq.rdata) & 0xFFFF_FFFF,
            )
        # A sibling outside the victims, and the drawn never-isolated port.
        sib = next(s for s in DOMS if s not in pd.victims and s != "trng")
        ok, desc = await self._expect(PROBE[sib], self.armed[PROBE[sib].name])
        self._ctl("CTL-ISO-SIBLING", ok, f"pass={pd.name} sibling={sib} {desc}")
        res["sibling_ok"] = ok
        addr, need_okay = NEVER[pd.never]
        # The external TRNG window is adopter-defined; with no TRNG fitted the
        # reference integration answers DECERR (memory_map.adoc, note 2).
        mon = self.env.axi_monitor
        if not need_okay:
            mon.arm_expected_decerr(1)
        seq = await self._acc(SepAxiOp.READ, addr, 4)
        if not need_okay and seq.resp_code != 3:
            mon.release_expected_decerr(1)
        res["never"] = (pd.never, seq.resp_code, int(seq.rdata) & 0xFFFF_FFFF, need_okay)
        res["still_low"] = all(self._ip(IPRST[v]) == 0 for v in pd.victims)
        return res

    async def _grade_pass(
        self, pd, view: PassView, host_evs, fall, rel_marks, win, baseline
    ) -> None:
        d = pd.victims[0]
        name = pd.name
        sw_aw = view.beats("aw", (SW_ID,))
        first_write = sw_aw[0][0]
        # CHK-ISO-PATHS: requests that rise over the pass, from the baseline.
        rose = view.req_rose() & ~baseline
        want = 0
        for v in pd.victims:
            want |= TABLE[v]
        want &= ~baseline
        self._chk(
            "CHK-ISO-PATHS",
            rose == want,
            f"dom={'+'.join(pd.victims)} isolated={self._names(rose)} expected={self._names(want)} "
            f"others_low={int(rose & ~want == 0)} baseline=0x{baseline:04x}",
        )
        # CHK-ISO-DRAIN / CTL-ISO-DRAIN, from the s_axi handshakes.
        reqrise = view.req_rise(HOST_MASK[d])
        acc: dict[int, int] = {}
        for c, i, _ in view.beats("ar", HOST_IDS) + view.beats("aw", HOST_IDS):
            acc.setdefault(i, c)
        done: dict[int, tuple[int, int]] = {}
        for c, i, r in view.beats("r", HOST_IDS) + view.beats("b", HOST_IDS):
            done.setdefault(i, (c, r))
        for op, tid, _ in host_evs:
            c, r = done.get(tid, (None, None))
            self.logger.info(
                "OBS-HOST-TXN: pass=%s op=%s id=%d accept_cycle=%s resp_cycle=%s resp=%s",
                name,
                op,
                tid,
                acc.get(tid),
                c,
                RESP_NAME.get(r, r),
            )
        # s_axi view of the same transactions, for information only.
        self.logger.info(
            "OBS-ISO-DRAIN-SAXI: dom=%s pass=%s accepted=%d resp_cycles=%s iso_req_cycle=%s "
            "rst_assert_cycle=%s",
            d,
            name,
            len(acc),
            ",".join(f"{i}:{done[i][0]}" for i in sorted(done)),
            reqrise,
            fall[d],
        )
        # CHK-ISO-DRAIN at the isolate stages of D (slave side): every transaction a
        # stage accepted before the isolate request rose has its response there
        # before ip_rst_n[D] falls. AXI-Lite stages answer in order per channel, so
        # the k-th response of a channel closes its k-th accepted transaction.
        st = self.isolog.since(view.m["iso_req"].clk, HOST_MASK[d], self.iso_off)
        acc_r = [c for c in st["ar"] if c < reqrise]
        acc_w = [c for c in st["aw"] if c < reqrise]
        rsp_r = st["r"][: len(acc_r)]
        rsp_w = st["b"][: len(acc_w)]
        open_r = sum(1 for c in rsp_r if c >= reqrise) + len(acc_r) - len(rsp_r)
        open_w = sum(1 for c in rsp_w if c >= reqrise) + len(acc_w) - len(rsp_w)
        late = [c for c in rsp_r + rsp_w if c >= fall[d]]
        missing = len(acc_r) - len(rsp_r) + len(acc_w) - len(rsp_w)
        accepted = len(acc_r) + len(acc_w)
        completed = accepted - missing - len(late)
        inflight = open_r + open_w
        vals = (
            f"dom={d} pass={name} accepted={accepted} completed={completed} "
            f"inflight_at_iso_req={inflight} iso_req_cycle={reqrise} rst_assert_cycle={fall[d]} "
            f"stage_accept_cycles=r:{acc_r},w:{acc_w} stage_resp_cycles=r:{rsp_r},w:{rsp_w} "
            f"stage_resp_codes=r:{st['rresp'][: len(acc_r)]},w:{st['bresp'][: len(acc_w)]}"
        )
        if d in ("otbn", "aes"):
            if inflight == 0:
                self.logger.error("CHK-ISO-DRAIN FAIL (precondition, no read in flight): %s", vals)
                raise AssertionError(f"CHK-ISO-DRAIN precondition: {vals}")
            self._chk("CHK-ISO-DRAIN", completed == accepted, vals)
        else:
            self.logger.info("CTL-ISO-DRAIN: %s", vals)
        # CHK-ISO-ORDER / CTL-ISO-ORDER (single-victim passes).
        ack_hi = {v: view.ack_rise(TABLE[v] & ~baseline, first_write - 1) for v in pd.victims}
        host_hi = {v: view.ack_rise(HOST_MASK[v], first_write - 1) for v in pd.victims}
        if len(pd.victims) == 1:
            a, r = ack_hi[d], fall[d]
            ok = a is not None and r is not None and r >= a
            vals = f"dom={d} ack_cycle={a} rst_assert_cycle={r} r-a={(r - a) if ok else 'na'}"
            if d in ("otbn", "aes"):
                self._chk("CHK-ISO-ORDER", ok, vals)
            else:
                self._ctl("CTL-ISO-ORDER", ok, vals)
        # Release timing of every victim.
        rel = {}
        aw_all = view.beats("aw", (SW_ID,))
        for v, aw_idx in rel_marks:
            aw_c = aw_all[aw_idx][0] if aw_idx < len(aw_all) else None
            rise = view.ip_rise_after(IPRST[v], fall[v])
            afall = view.ack_fall(TABLE[v] & ~baseline, fall[v])
            rel[v] = (aw_c, rise, afall)
        # Post-release probe reads (control: the path answers again).
        post_ok: dict[str, list[tuple[bool, str]]] = {}
        for v in pd.victims:
            for p in PROBES_B[v]:
                post_ok.setdefault(v, []).append(await self._expect(p, p.reset))
        if len(pd.victims) == 1:
            aw_c, rise, afall = rel[d]
            delta = abs(afall - rise) if (afall is not None and rise is not None) else None
            probe_ok = all(ok for ok, _ in post_ok[d])
            self._chk(
                "CHK-ISO-REL",
                delta is not None and delta <= REL_ALLOW and probe_ok,
                f"dom={d} rst_rise={rise} ack_fall={afall} abs_delta={delta} allow={REL_ALLOW} "
                f"probe_default={int(probe_ok)} {'; '.join(desc for _, desc in post_ok[d])}",
            )
        else:
            both_iso = all(
                host_hi[v] is not None and fall[v] is not None and fall[v] >= host_hi[v]
                for v in pd.victims
            )
            both_rel = all(
                rel[v][0] is not None
                and rel[v][1] is not None
                and rel[v][1] > rel[v][0]
                and rel[v][2] is not None
                and abs(rel[v][2] - rel[v][1]) <= REL_ALLOW
                for v in pd.victims
            )
            probe_ok = all(ok for v in pd.victims for ok, _ in post_ok[v])
            self.logger.info(
                "OBS-ISO-PAIR-ORDER: victims=%s falls=%s rises=%s",
                ",".join(pd.victims),
                ",".join(str(fall[v]) for v in pd.victims),
                ",".join(str(rel[v][1]) for v in pd.victims),
            )
            self._chk(
                "CHK-ISO-PAIR",
                both_iso and both_rel and probe_ok and win["sibling_ok"],
                f"victims={','.join(pd.victims)} both_isolated={int(both_iso)} "
                f"both_released={int(both_rel)} write_order={pd.order} gap={pd.gap} "
                + " ".join(
                    f"{v}:host_iso={host_hi[v]},fall={fall[v]},rel_aw={rel[v][0]},"
                    f"rise={rel[v][1]},ack_fall={rel[v][2]}"
                    for v in pd.victims
                )
                + f" allow={REL_ALLOW} probes_default={int(probe_ok)} "
                f"sibling_retained={int(win['sibling_ok'])}",
            )
        # CHK-ISO-RESP / CTL-ISO-RESP.
        # Every 32-bit lane every isolated read covers carries 0x1501A7ED (the bytes
        # of the lane a 1- or 2-byte read covers carry the matching bytes).
        lanes = win["lanes"]
        bad = [ln for ln in lanes if not ln[4]]
        hi_cov = high_lane_ports(pd.reads) if d in ("trng", "abr") else {}
        hi_ok = all(hi_cov.values()) if hi_cov else True
        rd4_ok = bool(win["rd4"]) and not bad and hi_ok
        graded = d in ("otbn", "aes", "kmac", "abr")
        written_absent = all(ok for ok, _ in post_ok[d])
        if not graded:
            self.logger.info(
                "CTL-ISO-RESP: dom=%s reads=%d writes=%d slverr=%d",
                d,
                win["n"] - win["writes"],
                win["writes"],
                win["slverr"],
            )
        ok = rd4_ok and written_absent and win["still_low"]
        if graded:
            ok = ok and win["slverr"] == win["n"]
        self._chk_late(
            "CHK-ISO-RESP",
            ok,
            f"dom={d} pass={name} rd4={len(win['rd4'])} rd4_data="
            + ",".join(f"0x{data:08x}/{RESP_NAME[r]}@0x{a:08x}" for a, data, r in win["rd4"])
            + f" lanes_ok={len(lanes) - len(bad)}/{len(lanes)}"
            + (
                " bad_lanes="
                + ",".join(f"{sz}B@0x{la:08x}:got=0x{g:x}/exp=0x{e:x}" for sz, la, g, e, _ in bad)
                if bad
                else ""
            )
            + (
                " high_lane_reads=" + ",".join(f"{k}:{int(v)}" for k, v in hi_cov.items())
                if hi_cov
                else ""
            )
            + f" graded_slverr={win['slverr'] if graded else 0}"
            f"{('/' + str(win['n'])) if graded else ''} "
            f"other_size_data=[{';'.join(win['other'])}] control_okay={int(written_absent)} "
            f"written_absent={int(written_absent)} in_window={int(win['still_low'])}",
        )
        port, resp, data, need_okay = win["never"]
        isolated_answer = resp == RESP_SLVERR and data == ISO_DATA
        ok = (resp == RESP_OKAY) if need_okay else not isolated_answer
        self._chk(
            "CHK-ISO-NEVER",
            ok and not isolated_answer and win["still_low"],
            f"dom={d} port={port} resp={RESP_NAME[resp]} rdata=0x{data:08x} "
            f"not_isolated_answer={int(not isolated_answer)}",
        )
        if len(pd.victims) == 1:
            kept = 0
            others = [s for s in DOMS if s != d]
            for s in others:
                ok, _ = await self._expect(PROBE[s], self.armed[PROBE[s].name])
                kept += int(ok)
            self._ctl(
                "CTL-INDEP", kept == len(others), f"dom={d} others_retained={kept}/{len(others)}"
            )
        for v in pd.victims:
            for p in PROBES_B[v]:
                await self._arm(p, 3)

    @staticmethod
    def _names(mask: int) -> str:
        return "{" + ",".join(f"x{x}" for x in range(ISO_WIDTH) if (mask >> x) & 1) + "}"

    async def _km_pass(self) -> None:
        dut = cocotb.top
        req0 = self.taps.iso_req_now()
        self._ctl(
            "CTL-ISO-BASELINE", req0 == 0, f"pass=km iso_req=0x{req0 or 0:04x} baseline=0x0000"
        )
        await RisingEdge(dut.clk_i)
        view = PassView(self.taps, self.chan, self.off)
        ev = self._sw_issue(self.sw & ~KM_BIT)
        await ev.wait()
        self.sw &= ~KM_BIT
        await self._wait_ip(IPRST["km"], 0, "km pass reset")
        fall = view.ip_fall(IPRST["km"])
        while view.cyc < fall + self.plan.km_hold:
            await RisingEdge(dut.clk_i)
        aw_idx = len(view.beats("aw", (SW_ID,)))
        ev = self._sw_issue(self.sw | KM_BIT)
        await ev.wait()
        self.sw |= KM_BIT
        await self._wait_ip(IPRST["km"], 1, "km pass release")
        await self._wait_ack(KM_SET, 0, "km pass isolate-complete release")
        await self._cycles(REL_ALLOW + 2)
        aw = view.beats("aw", (SW_ID,))
        first_write = aw[0][0]
        rose = view.req_rose()
        self._chk(
            "CHK-ISO-PATHS",
            rose == KM_SET,
            f"dom=km isolated={self._names(rose)} expected={self._names(KM_SET)} "
            f"others_low={int(rose & ~KM_SET == 0)} baseline=0x0000",
        )
        a = view.ack_rise(KM_SET, first_write - 1)
        ok = a is not None and fall is not None and fall >= a
        self._chk(
            "CHK-ISO-ORDER",
            ok,
            f"dom=km ack_cycle={a} rst_assert_cycle={fall} r-a={(fall - a) if ok else 'na'}",
        )
        rise = view.ip_rise_after(IPRST["km"], fall)
        afall = view.ack_fall(KM_SET, fall)
        rel_aw = aw[aw_idx][0] if aw_idx < len(aw) else None
        delta = abs(afall - rise) if (afall is not None and rise is not None) else None
        self._chk(
            "CHK-ISO-REL",
            delta is not None and delta <= REL_ALLOW and a is not None and rise > rel_aw,
            f"dom=km rst_rise={rise} ack_fall={afall} abs_delta={delta} allow={REL_ALLOW} "
            f"control_ack_rise_cycle={a} before rst_assert_cycle={fall} release_aw={rel_aw}",
        )
