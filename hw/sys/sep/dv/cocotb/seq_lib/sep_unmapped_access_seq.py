# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unmapped-access policy points for sep_unmapped_access_policy_test.

The SEP components table of the generated memory map
(``hw/sys/sep/regs/gen/adoc/memory_map.adoc``, read through
``env/sep_decode_resp.py``) states, per unit, its Decoded Extent and how a
32-bit access that no register backs answers: one cell for a hole inside the
extent, one for the rest of the aperture, and one for a reserved row between
apertures. Each cell gives the read response, the read data and the write
response.

This module builds the address sets that sit next to live registers but own
none, and that no other leaf probes:

* system-CSR holes: the gaps between the remap, filter and SEP CPU control
  blocks, and the space past the SEP CPU control extent;
* the reserved row above SEP CPU control, walked one 64 KiB page at a time;
* the upper half of the mailbox page, past the mailbox extent;
* the space past each eFuse sibling block (interface control, token MMR);
* the space past the SPI host extent, to the end of its aperture;
* the tail of every remap and filter array slot, where the slot stride is
  wider than the slot's registers, and the first word past each array.

An array's extent is ``SEP_TOP_<ARRAY>_TOTAL_SIZE`` from the generated
``hw/sys/sep/regs/gen/c/sep_addr.h``: the RDL allocates the whole stride to
every slot, the last one included, so every slot tail is inside the extent and
reads zero with OKAY. The array's aperture in the map must equal that size.

``sep.rdl`` sets ``ocah_full_stride_extent`` on these arrays, so the map's
Decoded Extent is the full allocation and the map states OKAY with zero for
every tail. Where the map and the RDL allocation disagree on a tail word, the
word is graded by the extent rule only and is listed in
``SepUnmappedCfg.map_disagree``.

Every other probe and tail access carries the response the map states for it
(``SepUnmappedCfg.expect``). The config refuses to build if a refusal-group
probe is not a refusal in the map, so each refusal checker grades a contract the
map states.

Every base, size and offset comes from the generated SystemRDL export
(``hw/sys/sep/regs/gen/py/sep_reg.py`` through ``sep_reg_meta``). A dead
address is a neighbouring RDL base plus a size or offset from the same export.
Alias candidates are a live register's address plus the next power of two at
or above its block's extent: that is where a decoder that drops the upper
address bits would land. RTL decode tables are never read.

The live words this module programs are the positive control: a write that
lands and reads back proves the bus reaches that block, and a distinct value
in each word is what makes a write alias or a read alias visible.

A live word is read before its write, so the closing restore can write the
pre-test value back. A word with a field that has no RDL reset (the eFuse token
input words, ``hw/ip/efuse/regs/efuse_mmr.rdl`` RMA_TOKEN_I and
SEC_DISABLE_TOKEN_I) has no value before its first write, so it is written
first and is not restored. The generated IP-XACT states which fields carry a
reset (``sep_reg_meta.word_has_unreset_field``); the generated ``_REG_DEFAULT``
reads 0 for a field without one and is not used for this.
"""

from __future__ import annotations

from dataclasses import dataclass

from env.sep_axi_agent import SepAxiOp
from env.sep_decode_resp import Expected, expected_unbacked, sep_map_row
from env.sep_spec_tables import mailbox_depth
from sep_reg_meta import (
    EFUSE_INTERFACE_CTRL,
    EFUSE_MMR,
    INBOUND_FILTER_CTRL_0,
    SEP_CPU_CTRL,
    RegBlock,
    block_names,
    block_size,
    indexed_block_count,
    sep_addr_define,
    sym,
    word_has_unreset_field,
)

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_fabric_csr_bank_seq import (
    ALIAS_BASE,
    ALIAS_END,
    ALIAS_END_MASK,
    ALIAS_REGIONS,
    AP_BASE,
    FILTER_START_ADDR,
    INFILT_BASE,
    INFILT_ENTRIES,
    OUTFILT_BASE,
    OUTFILT_ENTRIES,
    REMAP_ATTRS,
    REMAP_OFFSET_LO_MASK,
    REMAP_REGIONS,
    STEE_BASE,
)

# AMBA AXI4 (IHI 0022) response codes.
RESP_OKAY = 0
RESP_SLVERR = 2
RESP_DECERR = 3
RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}

# Data every probe write carries. Bit 31 is clear so an aliased write cannot set
# a filter FILTER_CONFIG.locked or a remap REGION_ATTRS.valid (both bit 31 of a
# hi word); bits 27 and 28 are clear so it cannot set the eFuse program or read
# enable; bit 4 is clear so it cannot set a filter entry_enabled. The value
# still differs from every programmed live word under that word's mask, which
# the config checks, so an aliased write is visible.
PROBE_WDATA = 0x4141_4140

# Reserved-row walk granularity. A DV stimulus spacing, not a register value.
PAGE = 0x1_0000


def _pow2_ceil(n: int) -> int:
    return 1 << (n - 1).bit_length()


def _slot_base(prefix: str, i: int) -> int:
    return sym(f"{prefix}_{i}__REG_MAP_BASE_ADDR")


def _slot_size(prefix: str, i: int) -> int:
    return block_size(f"{prefix}_{i}_")


@dataclass(frozen=True)
class LiveWord:
    """A live 32-bit word. ``value`` None means snapshot-only (read-only)."""

    name: str
    addr: int
    value: int | None = None


@dataclass(frozen=True)
class Probe:
    group: str
    addr: int
    op: str  # "r" | "w"
    note: str


@dataclass(frozen=True)
class TailWord:
    """One word of an array slot tail (past the slot's registers, before the next
    slot), or the first word past the array aperture."""

    array: str
    slot: int
    addr: int
    in_extent: bool
    # Live words the no-alias compare re-reads after a write to this tail:
    # this slot and the next one.
    neighbours: tuple[int, ...]
    label: str


# Refusal groups, in walk order. The names appear in the log.
GROUP_SYSCSR = "system_csr_hole"
GROUP_RESERVED = "sys_reserved_row"
GROUP_MBOX = "mailbox_upper_half"
GROUP_EFUSE_CTRL = "efuse_ctrl_past_extent"
GROUP_EFUSE_MMR = "efuse_mmr_past_extent"
GROUP_SPI = "spi_host_past_extent"
REFUSE_GROUPS = (
    GROUP_SYSCSR,
    GROUP_RESERVED,
    GROUP_MBOX,
    GROUP_EFUSE_CTRL,
    GROUP_EFUSE_MMR,
    GROUP_SPI,
)
# Groups whose probes reach the system-CSR AXI-Lite port when the system CSR is
# the point that refuses. The Lite handshake is logged for these.
LITE_WATCHED = (GROUP_SYSCSR, GROUP_RESERVED)

# TOKEN_MATCH_FAULT, the last RDL register of the eFuse token MMR.
TOKEN_MATCH_FAULT = EFUSE_MMR.addr("TOKEN_MATCH_FAULT")
TOKEN_MATCH_FAULT_MASK = EFUSE_MMR.mask32("TOKEN_MATCH_FAULT")
TOKEN_MATCH_FAULT_RESET = EFUSE_MMR.reset32("TOKEN_MATCH_FAULT")

_ARRAYS = (
    ("local_master_alias_remap_ctrl", "LOCAL_MASTER_ALIAS_REMAP_CTRL", ALIAS_REGIONS),
    ("outbound_filter_ctrl", "OUTBOUND_FILTER_CTRL", OUTFILT_ENTRIES),
    ("inbound_filter_ctrl", "INBOUND_FILTER_CTRL", INFILT_ENTRIES),
)


def _rdl_owner(addr: int) -> str | None:
    """The RDL block (other than the top map) whose extent holds ``addr``."""
    for b in block_names():
        if b.rstrip("_") == "SEP_TOP":
            continue
        base = sym(f"{b}_REG_MAP_BASE_ADDR")
        if base <= addr < base + sym(f"{b}_REG_MAP_SIZE"):
            return b
    return None


class SepUnmappedCfg:
    """Directed probe set and live-word set. Built from the register export only."""

    def __init__(self) -> None:
        self.live: list[LiveWord] = []
        self.probes: list[Probe] = []
        self.tails: list[TailWord] = []
        # array name -> (base, TOTAL_SIZE) from sep_addr.h
        self.array_extent: dict[str, tuple[int, int]] = {}
        # tail word -> the map cell that disagrees with the RDL allocation
        self.map_disagree: dict[int, str] = {}
        # (addr, op) -> the response the map states
        self.expect: dict[tuple[int, str], Expected] = {}
        # Live words with a field that has no RDL reset: written before the
        # first read, never pre-read or restored.
        self.unreset: frozenset[int] = frozenset()
        self._build_arrays()
        self._build_syscsr()
        self._build_reserved_row()
        self._build_mailbox()
        self._build_efuse()
        self._build_spi()
        self._self_check()

    # --- remap / filter arrays --------------------------------------------
    def _build_arrays(self) -> None:
        start_mask = INBOUND_FILTER_CTRL_0.mask32("START_ADDR")
        for name, prefix, count in _ARRAYS:
            bases = [_slot_base(prefix, i) for i in range(count)]
            sizes = [_slot_size(prefix, i) for i in range(count)]
            stride = bases[1] - bases[0]
            if any(b2 - b1 != stride for b1, b2 in zip(bases, bases[1:])):
                raise RuntimeError(f"{name}: slot stride is not uniform in the export")
            for suffix, want in (("NUM", count), ("STRIDE", stride)):
                got = sep_addr_define(f"SEP_TOP_{prefix}_{suffix}")
                if got != want:
                    raise RuntimeError(
                        f"{name}: sep_addr.h {suffix}=0x{got:x} but the Python export "
                        f"gives 0x{want:x}"
                    )
            total = sep_addr_define(f"SEP_TOP_{prefix}_TOTAL_SIZE")
            if bases[-1] + stride > bases[0] + total:
                raise RuntimeError(f"{name}: the last slot stride ends past TOTAL_SIZE 0x{total:x}")
            row = sep_map_row(bases[0])
            if row.base != bases[0] or row.end - row.base + 1 != total:
                raise RuntimeError(
                    f"{name}: map row {row.unit} 0x{row.base:08x}-0x{row.end:08x} is not the "
                    f"array aperture base 0x{bases[0]:08x} + TOTAL_SIZE 0x{total:x}"
                )
            extent_end = bases[0] + total
            self.array_extent[name] = (bases[0], total)
            slot_words = [tuple(range(b, b + s, 4)) for b, s in zip(bases, sizes)]
            for i, base in enumerate(bases):
                # One distinct, non-zero programmed word per slot. The alias
                # remap uses REGION_END (4 KB-aligned, valid stays clear); the
                # filters use START_ADDR (entry_enabled stays clear).
                if prefix == "LOCAL_MASTER_ALIAS_REMAP_CTRL":
                    addr = base + ALIAS_END
                    value = ((0x40 + i) << 12) & ALIAS_END_MASK
                else:
                    addr = base + FILTER_START_ADDR
                    tag = 0x0080_0000 if prefix == "OUTBOUND_FILTER_CTRL" else 0x0090_0000
                    value = (tag | (i << 12)) & start_mask
                self.live.append(LiveWord(f"{name}[{i}]", addr, value))
                for w in slot_words[i]:
                    if w != addr:
                        self.live.append(LiveWord(f"{name}[{i}]+0x{w - base:x}", w))
                neigh = slot_words[i] + (slot_words[i + 1] if i + 1 < count else ())
                for t in range(base + sizes[i], base + stride, 4):
                    self.tails.append(
                        TailWord(name, i, t, t < extent_end, neigh, f"{name}[{i}] tail")
                    )
            # The first word past the array aperture. It is a refusal point only
            # where no other RDL block owns it: the word past the alias-remap
            # array is AP_OUTPUT_REMAP_CTRL[0], a live word.
            ap_end = bases[0] + total
            if _rdl_owner(ap_end) is None:
                self.tails.append(
                    TailWord(
                        name,
                        count,
                        ap_end,
                        False,
                        slot_words[-1],
                        f"{name} first word past base + TOTAL_SIZE",
                    )
                )

    # --- system-CSR holes ---------------------------------------------------
    def _build_syscsr(self) -> None:
        g = GROUP_SYSCSR
        ap_last = REMAP_REGIONS - 1
        ap_end = _slot_base("AP_OUTPUT_REMAP_CTRL", ap_last) + _slot_size(
            "AP_OUTPUT_REMAP_CTRL", ap_last
        )
        stee_end = _slot_base("STEE_OUTPUT_REMAP_CTRL", ap_last) + _slot_size(
            "STEE_OUTPUT_REMAP_CTRL", ap_last
        )
        remap_img = ALIAS_BASE + _pow2_ceil(stee_end - ALIAS_BASE)
        out_last = OUTFILT_ENTRIES - 1
        out_img = OUTFILT_BASE + _pow2_ceil(
            _slot_base("OUTBOUND_FILTER_CTRL", out_last)
            + _slot_size("OUTBOUND_FILTER_CTRL", out_last)
            - OUTFILT_BASE
        )
        in_last = INFILT_ENTRIES - 1
        in_img = INFILT_BASE + _pow2_ceil(
            _slot_base("INBOUND_FILTER_CTRL", in_last)
            + _slot_size("INBOUND_FILTER_CTRL", in_last)
            - INFILT_BASE
        )
        cpu_base = sym("SEP_CPU_CTRL_REG_MAP_BASE_ADDR")
        cpu_size = block_size("SEP_CPU_CTRL")
        nmi_off = SEP_CPU_CTRL.offset("SEP_NMI_VEC")
        self.cpu_img = cpu_base + _pow2_ceil(cpu_size)

        # Live words next to these holes: the first and last AP / STEE entry
        # and SEP_NMI_VEC. The alias-remap and filter slot words come from
        # _build_arrays.
        for label, base, value in (
            ("ap_output_remap[0]", AP_BASE, 0x00A5_A000),
            (
                f"ap_output_remap[{ap_last}]",
                _slot_base("AP_OUTPUT_REMAP_CTRL", ap_last),
                0x00C7_C000,
            ),
            ("stee_output_remap[0]", STEE_BASE, 0x00B6_B000),
            (
                f"stee_output_remap[{ap_last}]",
                _slot_base("STEE_OUTPUT_REMAP_CTRL", ap_last),
                0x00D8_D000,
            ),
        ):
            self.live.append(LiveWord(label, base + REMAP_ATTRS, value & REMAP_OFFSET_LO_MASK))
        self.live.append(
            LiveWord(
                "sep_cpu_ctrl.SEP_NMI_VEC",
                cpu_base + nmi_off,
                0x1357_9BDE & SEP_CPU_CTRL.mask32("SEP_NMI_VEC"),
            )
        )

        for addr, note in (
            (ap_end, "first word past the AP output-remap array"),
            (STEE_BASE - 4, "last word before the STEE output-remap array"),
            (stee_end, "first word past the STEE output-remap array"),
            (remap_img + ALIAS_END, "alias-remap slot 0 REGION_END, one remap-group image up"),
            (OUTFILT_BASE - 4, "last word before the outbound filter array"),
            (out_img + FILTER_START_ADDR, "outbound filter slot 0 START_ADDR, one array image up"),
            (INFILT_BASE - 4, "last word before the inbound filter array"),
            (in_img + FILTER_START_ADDR, "inbound filter slot 0 START_ADDR, one array image up"),
            (cpu_base - 4, "last word before SEP CPU control"),
            (cpu_base + cpu_size, "first word past the SEP CPU control extent"),
            (self.cpu_img + nmi_off, "SEP_NMI_VEC, one SEP CPU control image up"),
        ):
            for op in ("r", "w"):
                self.probes.append(Probe(g, addr, op, note))

    # --- reserved row above SEP CPU control --------------------------------
    def _build_reserved_row(self) -> None:
        # The generated memory map (hw/sys/sep/regs/gen/adoc/memory_map.adoc)
        # marks everything from the end of the SEP CPU control aperture up to
        # the external IO bridge as one reserved row. Walk it one 64 KiB page at
        # a time, first and last word of each page.
        g = GROUP_RESERVED
        row_end = sym("SPI_CONTROLLER_REG_MAP_BASE_ADDR")
        page = (self.cpu_img + PAGE - 1) & ~(PAGE - 1)
        while page < row_end:
            for addr in (page, page + PAGE - 4):
                for op in ("r", "w"):
                    self.probes.append(Probe(g, addr, op, f"reserved page 0x{page:08x}"))
            page += PAGE

    # --- mailbox upper half ------------------------------------------------
    def _build_mailbox(self) -> None:
        g = GROUP_MBOX
        mb_base = sym("AXIL_MAILBOX_REG_MAP_BASE_ADDR")
        upper = mb_base + _pow2_ceil(block_size("AXIL_MAILBOX"))
        upper_end = ALIAS_BASE  # next RDL block after the mailbox page
        n_in = indexed_block_count("AXIL_MAILBOX_INBOUND_MAILBOX")
        out0 = RegBlock("AXIL_MAILBOX_OUTBOUND_MAILBOX_0")
        in_last = RegBlock(f"AXIL_MAILBOX_INBOUND_MAILBOX_{n_in - 1}")
        in_last_off = sym(f"AXIL_MAILBOX_INBOUND_MAILBOX_{n_in - 1}_REG_MAP_BASE_ADDR") - mb_base
        wirqt = out0.offset("WIRQT")
        rirqt = out0.offset("RIRQT")
        status = out0.offset("STATUS")
        # A threshold at or above MailboxDepth reads back as MailboxDepth - 1
        # (axil_mailbox.rdl WIRQT / RIRQT), so each value stays below the depth
        # and reads back as written.
        thresholds = (5, 3, 6)
        assert all(0 < t < mailbox_depth() - 1 for t in thresholds)
        self.live.extend(
            (
                LiveWord("outbound_mailbox[0].WIRQT", out0.addr("WIRQT"), thresholds[0]),
                LiveWord("outbound_mailbox[0].RIRQT", out0.addr("RIRQT"), thresholds[1]),
                LiveWord(
                    f"inbound_mailbox[{n_in - 1}].WIRQT",
                    in_last.addr("WIRQT"),
                    thresholds[2],
                ),
            )
        )
        # Every mailbox STATUS, snapshot only: a write that aliases onto any
        # WRITE_DATA pushes that FIFO and moves its STATUS.
        n_out = indexed_block_count("AXIL_MAILBOX_OUTBOUND_MAILBOX")
        for kind, n in (("OUTBOUND", n_out), ("INBOUND", n_in)):
            for i in range(n):
                blk = RegBlock(f"AXIL_MAILBOX_{kind}_MAILBOX_{i}")
                self.live.append(
                    LiveWord(f"{kind.lower()}_mailbox[{i}].STATUS", blk.addr("STATUS"))
                )
        for addr, ops, note in (
            (upper, ("r", "w"), "outbound mailbox 0 WRITE_DATA, one mailbox image up"),
            (upper + wirqt, ("r", "w"), "outbound mailbox 0 WIRQT, one mailbox image up"),
            (upper + rirqt, ("r", "w"), "outbound mailbox 0 RIRQT, one mailbox image up"),
            (upper + status, ("r",), "outbound mailbox 0 STATUS, one mailbox image up"),
            (
                upper + in_last_off + wirqt,
                ("r", "w"),
                f"inbound mailbox {n_in - 1} WIRQT, one mailbox image up",
            ),
            (upper + (upper_end - upper) // 2, ("r", "w"), "middle of the upper half"),
            (upper_end - 4, ("r", "w"), "last word of the mailbox page"),
        ):
            for op in ops:
                self.probes.append(Probe(g, addr, op, note))

    # --- eFuse siblings ----------------------------------------------------
    def _build_efuse(self) -> None:
        ctrl_base = sym("EFUSE_INTERFACE_CTRL_REG_MAP_BASE_ADDR")
        ctrl_end = ctrl_base + block_size("EFUSE_INTERFACE_CTRL")
        mmr_base = sym("EFUSE_MMR_REG_MAP_BASE_ADDR")
        mmr_end = mmr_base + block_size("EFUSE_MMR")
        # The two siblings sit in equal windows in the generated map, so the
        # spacing of their bases is the window size of each.
        window = mmr_base - ctrl_base
        rto = EFUSE_INTERFACE_CTRL.offset("EFUSE_READ_REQ_TIMEOUT")
        tok0 = EFUSE_MMR.offset("RMA_SIP_TOKEN_I_0_")
        tok_last = EFUSE_MMR.offset("SEC_DISABLE_TOKEN_I_7_")
        self.live.extend(
            (
                LiveWord(
                    "efuse_interface_ctrl.EFUSE_READ_REQ_TIMEOUT",
                    EFUSE_INTERFACE_CTRL.addr("EFUSE_READ_REQ_TIMEOUT"),
                    0x0246_8ACE & EFUSE_INTERFACE_CTRL.mask32("EFUSE_READ_REQ_TIMEOUT"),
                ),
                LiveWord(
                    "efuse_interface_ctrl.EFUSE_PROGRAM_REQ_TIMEOUT",
                    EFUSE_INTERFACE_CTRL.addr("EFUSE_PROGRAM_REQ_TIMEOUT"),
                    0x0135_79BC & EFUSE_INTERFACE_CTRL.mask32("EFUSE_PROGRAM_REQ_TIMEOUT"),
                ),
                LiveWord(
                    "efuse_mmr.RMA_SIP_TOKEN_I[0]",
                    mmr_base + tok0,
                    0xC0FF_EE11 & EFUSE_MMR.mask32("RMA_TOKEN_I"),
                ),
                LiveWord(
                    "efuse_mmr.SEC_DISABLE_TOKEN_I[7]",
                    mmr_base + tok_last,
                    0x7E57_0B1D & EFUSE_MMR.mask32("RMA_TOKEN_I"),
                ),
                LiveWord("efuse_mmr.TOKEN_MATCH_FAULT", TOKEN_MATCH_FAULT),
            )
        )
        ctrl_img = _pow2_ceil(block_size("EFUSE_INTERFACE_CTRL"))
        mmr_img = _pow2_ceil(block_size("EFUSE_MMR"))
        # The map states one read word past this extent. Probe both 32-bit lanes of
        # the 64-bit bus: the first word past the extent, and the first word past
        # it with the other value of address bit 2.
        ctrl_other = ctrl_end + 4
        for addr, note in (
            (ctrl_end, "first word past the efuse_interface_ctrl extent"),
            (ctrl_other, "second word past the efuse_interface_ctrl extent (other bus lane)"),
            (ctrl_base + ctrl_img + rto, "EFUSE_READ_REQ_TIMEOUT, one extent image up"),
            (ctrl_base + window // 2 + rto, "EFUSE_READ_REQ_TIMEOUT, half a window up"),
            (ctrl_base + window - 4, "last word of the efuse_interface_ctrl window"),
        ):
            for op in ("r", "w"):
                self.probes.append(Probe(GROUP_EFUSE_CTRL, addr, op, note))
        for addr, note in (
            (mmr_end, "first word past the efuse_mmr extent (after TOKEN_MATCH_FAULT)"),
            (mmr_base + mmr_img + tok0, "RMA_SIP_TOKEN_I[0], one extent image up"),
            (mmr_base + window // 2 + tok_last, "SEC_DISABLE_TOKEN_I[7], half a window up"),
            (mmr_base + window - 4, "last word of the efuse_mmr window"),
        ):
            for op in ("r", "w"):
                self.probes.append(Probe(GROUP_EFUSE_MMR, addr, op, note))
        self.mmr_end = mmr_end

    # --- SPI host past its extent ---------------------------------------
    def _build_spi(self) -> None:
        spi = RegBlock("SPI_CONTROLLER")
        base = sym("SPI_CONTROLLER_REG_MAP_BASE_ADDR")
        end = base + block_size("SPI_CONTROLLER")
        aperture = sep_map_row(base).end + 1 - base
        csid = spi.offset("CSID")
        configopts = spi.offset("CONFIGOPTS")
        # CSID only selects a chip select when a command is issued, and this leaf
        # issues none, so a distinct value there has no side effect.
        self.live.extend(
            (
                LiveWord("spi_controller.CSID", spi.addr("CSID"), 0x0000_5A5A & spi.mask32("CSID")),
                LiveWord("spi_controller.CONFIGOPTS", spi.addr("CONFIGOPTS")),
            )
        )
        img = _pow2_ceil(block_size("SPI_CONTROLLER"))
        for addr, note in (
            (end, "first word past the spi_controller extent"),
            (end + 4, "second word past the spi_controller extent (other bus lane)"),
            (base + img + csid, "CSID, one extent image up"),
            (base + aperture // 2 + configopts, "CONFIGOPTS, half an aperture up"),
            (base + aperture - 4, "last word of the spi_controller aperture"),
        ):
            for op in ("r", "w"):
                self.probes.append(Probe(GROUP_SPI, addr, op, note))

    def _self_check(self) -> None:
        for p in self.probes:
            e = self.expect[(p.addr, p.op)] = expected_unbacked(p.addr, p.op)
            if e.resp == RESP_OKAY:
                raise RuntimeError(
                    f"{p.group} probe {p.op} 0x{p.addr:08x} ({p.note}): the map states "
                    f"OKAY ({e.row}, {e.column}), so it is not a refusal point"
                )
        for t in self.tails:
            for op in ("r", "w"):
                e = expected_unbacked(t.addr, op)
                ok_zero = e.resp == RESP_OKAY and not e.rdata
                if t.in_extent == ok_zero:
                    self.expect[(t.addr, op)] = e
                elif t.in_extent:
                    self.map_disagree[t.addr] = f"{e.cell} ({e.row}, {e.column})"
                else:
                    raise RuntimeError(
                        f"{t.label} {op} 0x{t.addr:08x} is past the RDL allocation but the "
                        f"map states {e.cell!r} ({e.row}, {e.column})"
                    )
        addrs = [w.addr for w in self.live]
        if len(addrs) != len(set(addrs)):
            raise RuntimeError("a live word is listed twice")
        self.unreset = frozenset(a for a in addrs if word_has_unreset_field(a))
        for w in self.live:
            if w.addr in self.unreset and w.value is None:
                raise RuntimeError(
                    f"{w.name} 0x{w.addr:08x}: a field has no RDL reset, so a "
                    "snapshot-only read of it has no defined value"
                )
        values = [w.value for w in self.live if w.value is not None]
        if any(v == 0 for v in values) or len(values) != len(set(values)):
            raise RuntimeError(
                "programmed live values must be non-zero and distinct, or a read "
                "alias cannot be told from a refusal"
            )
        for w in self.live:
            if w.value is not None and (w.value ^ PROBE_WDATA) == 0:
                raise RuntimeError(f"{w.name}: probe data equals the programmed value")
        live = set(addrs)
        for p in self.probes:
            if p.addr in live:
                raise RuntimeError(f"probe 0x{p.addr:08x} ({p.note}) is a live word")
        for g in REFUSE_GROUPS:
            ops = {p.op for p in self.probes if p.group == g}
            if ops != {"r", "w"}:
                raise RuntimeError(f"{g}: both channels must be probed, got {sorted(ops)}")
        for g in (GROUP_EFUSE_CTRL, GROUP_SPI):
            lanes = {p.addr & 0x4 for p in self.probes if p.group == g and p.op == "r"}
            if lanes != {0, 4}:
                raise RuntimeError(f"{g}: reads must cover both 32-bit lanes of the bus")
        # TOKEN_MATCH_FAULT is the last word the RDL gives the token MMR.
        if TOKEN_MATCH_FAULT + 4 != self.mmr_end:
            raise RuntimeError(
                f"TOKEN_MATCH_FAULT 0x{TOKEN_MATCH_FAULT:08x} is not the last word of "
                f"the efuse_mmr extent (ends 0x{self.mmr_end - 1:08x})"
            )

    @property
    def probe_watch(self) -> list[int]:
        """Words re-read after each probe write: every programmed word, plus the
        snapshot-only words outside the arrays. The remaining array slot words
        are covered by the tail walk and by the closing full compare."""
        in_arrays = {w for t in self.tails for w in t.neighbours}
        return [w.addr for w in self.live if w.value is not None or w.addr not in in_arrays]

    @property
    def programmed(self) -> list[LiveWord]:
        return [w for w in self.live if w.value is not None]

    def summary(self) -> str:
        per = " ".join(f"{g}={sum(1 for p in self.probes if p.group == g)}" for g in REFUSE_GROUPS)
        n_in = sum(1 for t in self.tails if t.in_extent)
        return (
            f"live={len(self.live)} programmed={len(self.programmed)} "
            f"no-rdl-reset={len(self.unreset)} "
            f"probes={len(self.probes)} [{per}] tails={len(self.tails)} "
            f"(in-extent={n_in}, past-extent={len(self.tails) - n_in})"
        )


@dataclass
class ProbeResult:
    probe: Probe
    resp: int
    rdata: int
    timed_out: bool
    lite_reached: bool | None = None
    alias: str | None = None
    changed: tuple[str, ...] = ()


class SepUnmappedAccess:
    """Drive the probes and the live-word snapshot for the unmapped-access leaf."""

    def __init__(self, test, cfg: SepUnmappedCfg) -> None:
        self.test = test
        self.cfg = cfg
        self.log = test.logger
        self.snap: dict[int, int] = {}
        self.pre: dict[int, int] = {}
        self.names = {w.addr: w.name for w in cfg.live}
        self.decerr_reported = 0
        # Error-response reads, and how many of them the monitor lane-checked.
        self.err_reads = 0
        self.err_reads_lane_checked = 0

    async def access(
        self, op: str, addr: int, *, wdata: int = 0, may_refuse: bool
    ) -> tuple[int, int, bool]:
        """One 32-bit single. ``may_refuse`` grades the response here, not in the scoreboard.

        A DECERR credit is armed around every such access and handed back
        unless a DECERR beat consumed it, the way the dead-space probe does it.
        """
        mon = self.test.env.axi_monitor
        axi_op = SepAxiOp.WRITE if op == "w" else SepAxiOp.READ
        kwargs = {}
        check_err_lanes = may_refuse and op == "r"
        if may_refuse:
            mon.arm_expected_decerr(1)
            if op == "w":
                kwargs["allow_unverified_write_resp"] = True
            else:
                kwargs["allow_ungraded_read_resp"] = True
        seq = SepAxiAccessSeq(
            f"unmapped_{op}_0x{addr:08x}",
            op=axi_op,
            addr=addr,
            wdata=wdata,
            length=4,
            size=2,
            **kwargs,
        )
        checked0 = mon.r_beats_lane_checked
        if check_err_lanes:
            # Lane-check the read data of an error response for X/Z too: the
            # caller grades that data, and the driver would read X as 0.
            mon.open_error_rdata_window()
        try:
            await self.test.start_seq(seq)
        finally:
            if check_err_lanes:
                mon.close_error_rdata_window()
        if check_err_lanes and not seq.timed_out and seq.resp_code != RESP_OKAY:
            self.err_reads += 1
            if mon.r_beats_lane_checked > checked0:
                self.err_reads_lane_checked += 1
        if may_refuse:
            if seq.timed_out or seq.resp_code != RESP_DECERR:
                mon.release_expected_decerr(1)
            else:
                self.decerr_reported += 1
        return seq.resp_code, seq.rdata & 0xFFFF_FFFF, seq.timed_out

    async def program_live(self) -> list[str]:
        """Write every programmed word, then snapshot every live word.

        A word with an RDL reset is read first, for the restore. A word in
        ``cfg.unreset`` is written with no read before it.

        Returns failure strings. A programmed word must read back its value
        exactly and with OKAY; a snapshot-only word must read OKAY.
        """
        fails: list[str] = []
        reached: set[int] = set()
        for w in self.cfg.live:
            if w.addr in self.cfg.unreset:
                self.log.info(
                    "UNMAPPED-LIVE: %s 0x%08x has a field with no RDL reset; it is "
                    "written before its first read and is not restored",
                    w.name,
                    w.addr,
                )
            else:
                resp, val, to = await self.access("r", w.addr, may_refuse=False)
                if to or resp != RESP_OKAY:
                    fails.append(f"{w.name} 0x{w.addr:08x} pre-read resp={resp} timed_out={to}")
                    continue
                self.pre[w.addr] = val
            if w.value is not None:
                resp, _d, to = await self.access("w", w.addr, wdata=w.value, may_refuse=False)
                if to or resp != RESP_OKAY:
                    fails.append(f"{w.name} 0x{w.addr:08x} write resp={resp} timed_out={to}")
                    continue
            reached.add(w.addr)
        for w in self.cfg.live:
            if w.addr not in reached:
                continue
            resp, val, to = await self.access("r", w.addr, may_refuse=False)
            if to or resp != RESP_OKAY:
                fails.append(f"{w.name} 0x{w.addr:08x} read-back resp={resp} timed_out={to}")
                continue
            if w.value is not None and val != w.value:
                fails.append(
                    f"{w.name} 0x{w.addr:08x} read back 0x{val:08x}, programmed 0x{w.value:08x}"
                )
                continue
            self.snap[w.addr] = val
        return fails

    async def compare(self, addrs) -> list[str]:
        """Re-read ``addrs`` and name every word that moved or could not be read."""
        out: list[str] = []
        for addr in addrs:
            if addr not in self.snap:
                continue
            resp, val, to = await self.access("r", addr, may_refuse=False)
            name = self.names.get(addr, f"0x{addr:08x}")
            if to or resp != RESP_OKAY:
                out.append(f"{name} re-read resp={resp} timed_out={to}")
            elif val != self.snap[addr]:
                out.append(f"{name} 0x{self.snap[addr]:08x}->0x{val:08x}")
        return out

    def read_alias(self, rdata: int) -> str | None:
        """Name the programmed word whose value a read returned, if any."""
        for w in self.cfg.programmed:
            if self.snap.get(w.addr) == rdata:
                return w.name
        return None

    async def probe(self, p: Probe) -> ProbeResult:
        watch = p.group in LITE_WATCHED
        if watch:
            task, lite = self.test.watch_sys_csr_lite(write=p.op == "w")
        try:
            resp, rdata, to = await self.access(p.op, p.addr, wdata=PROBE_WDATA, may_refuse=True)
        finally:
            if watch:
                task.kill()
        res = ProbeResult(p, resp, rdata, to)
        if watch:
            res.lite_reached = any((a & ~0x7) == (p.addr & ~0x7) for a in lite)
        if p.op == "r" and not to:
            res.alias = self.read_alias(rdata)
        if p.op == "w":
            res.changed = tuple(await self.compare(self.cfg.probe_watch))
        return res

    async def tail(
        self, t: TailWord, op: str
    ) -> tuple[int, int, bool, tuple[str, ...], tuple[int, int, bool] | None]:
        """One access to a tail word.

        After a write, re-read the words of this slot and of the next slot. After
        a write inside the array extent, also re-read the tail word itself and
        return that ``(resp, rdata, timed_out)``: the extent rule discards the
        write, so the re-read must answer OKAY with zero.
        """
        resp, rdata, to = await self.access(op, t.addr, wdata=PROBE_WDATA, may_refuse=True)
        changed: tuple[str, ...] = ()
        reread: tuple[int, int, bool] | None = None
        if op == "w":
            changed = tuple(await self.compare(t.neighbours))
            if t.in_extent:
                reread = await self.access("r", t.addr, may_refuse=True)
        return resp, rdata, to, changed, reread

    async def restore(self) -> None:
        """Write back the pre-test value of every programmed word that has one.

        A word in ``cfg.unreset`` has no pre-test value and is left as written.
        """
        for w in self.cfg.programmed:
            if w.addr in self.pre:
                await self.access("w", w.addr, wdata=self.pre[w.addr], may_refuse=False)
