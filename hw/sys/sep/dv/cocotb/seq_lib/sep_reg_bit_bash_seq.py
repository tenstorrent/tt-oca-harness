# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CSR reset / RW / RO / reserved sweep for sep_reg_bit_bash_rand_test.

Walks the generated SystemRDL export in env/sep_reg_meta.py. Not a RAL model.
SepRegBitBashCfg is the single source of truth for which registers get a reset
check, which take a write bash, and the seed-selected walk order.

Exclusions are data: one reason string per entry. A silent skip is a bug.
``iter_register_walk`` counts OFFSET symbols that lack DEFAULT/struct
(``nometa``) instead of dropping them without a tally.
Inbound-filter START/END stay in the write sweep under the full export
mask. ``axi_filter_wrap`` rewrites a same-beat window only
(``START[2:0]->0``, ``END[2:0]->1``; END reset ``0x7``). Solo bash keeps
the peer at reset, so the checker compares readback to that wrap model
rather than stripping ``[2:0]`` from the mask.

Full complement bash stays on no-side-effect blocks. The masked storage
touch is wider: every register the safety gate admits gets a seed-derived
``x`` inside the software-usable mask, a ``(readback & mask) == (x & mask)``
compare, and a restore to reset. The gate is
``touch_reason(info) is None and side_effect_reason(info) is None``.
``touch_reason`` alone is NOT a gate: it consults reset_reason, the mask,
name suffixes and the touch deny tables, and never the write-side
side-effect tables, so on its own it admits the outbound-filter,
alias-remap and fabric-remap banks whose write redirects or drops a live
beat. ``TOUCH_BLOCKS`` is the anti-vacuity list of IPs that must each
still contribute at least one touch.
"""

from __future__ import annotations

from collections import defaultdict

from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from env.sep_spec_tables import AXI_BUS_BYTES
from sep_reg_meta import (
    INBOUND_FILTER_CTRL_0,
    KM_MAILBOX_SEP,
    RegAccess,
    RegInfo,
    iter_register_walk,
    reg_hw_updating,
)

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq

# (block, name) -> reason. name None = every register in the block.
# kind is consulted by the cfg, not stored here: RESET_EXCLUDE vs WRITE_EXCLUDE.
RESET_EXCLUDE: dict[tuple[str, str | None], str] = {
    ("SEP_TOP", None): "top container, not a register block",
    ("PIC", None): "CPU-internal PIC, not on the CPU-LSU splice",
    ("SEP_EXTERNAL", None): "adopter extension window",
    ("SEP_EXTERNAL_EFUSE_SHIM_CTRL", None): "adopter extension window",
    ("EFUSE_INTERFACE_CTRL", None): "OTP-trigger; a program/read hangs the command mux",
    ("EFUSE_MMR", None): "OTP-trigger",
    ("SEP_EFUSE_MAP", None): "hw-driven shadow under +skip_fuse_sense",
    ("SEP_LIFECYCLE_CTRL", None): "hw-driven feat_ctrl / demote",
    ("SEP_CPU_CTRL", "REFERENCE_COUNTER"): "hw-driven free-running counter",
    ("SEP_CPU_CTRL", "SEP_TEST_CTRL"): "hw-driven straps",
    ("SEP_CPU_CTRL", "SEP_FUSE_SENSE_STATUS"): "hw-driven fuse-sense status",
    ("SEP_CPU_CTRL", "SMC_FUSE_SENSE_STATUS"): "hw-driven fuse-sense status",
    ("SEP_CPU_CTRL", "TIMEOUT_CLEAR"): "write-only",
    ("SEP_CPU_CTRL", "TIMEOUT_MODE"): "write-only",
    ("SEP_CPU_CTRL", "DMA_BUS_ERR_CLEAR"): "write-only",
    ("SEP_CPU_CTRL", "PERIPH_BUS_ERR_CLEAR"): "write-only",
    ("WDT_TIMER", "WKUP_COUNT_HI"): "hw-driven timer",
    ("WDT_TIMER", "WKUP_COUNT_LO"): "hw-driven timer",
    ("WDT_TIMER", "WDOG_COUNT"): "hw-driven timer",
}


# ENTROPY_SOURCE registers hardware may change while the noise source runs: a
# reset compare on one measures elapsed time, not the DUT's reset value. The set
# is `sw = r` minus proven constants, derived in sep_reg_meta.reg_hw_updating so
# the dead-space store compare uses the SAME source and the two cannot drift
# apart. HT_WATERMARK_NUM is `sw = rw` (a mode selector) and stays in the walk.
# Resolved on first use so importing this module does not need the JSON on disk.
def esrc_reset_skip() -> frozenset[str]:
    """ENTROPY_SOURCE registers whose read value is not the POR value (cached)."""
    cached = getattr(esrc_reset_skip, "_cache", None)
    if cached is None:
        cached = esrc_reset_skip._cache = reg_hw_updating("entropy_source")
    return cached


# Name suffixes excluded from reset and write. Each carries a reason.
RESET_EXCLUDE_SUFFIX: dict[str, str] = {
    "INTR_TEST": "trigger",
    "ALERT_TEST": "trigger",
    "TRIGGER": "trigger",
    "STATUS": "hw-driven",
    "TXDATA": "FIFO",
    "RXDATA": "FIFO",
    "WRITE_DATA": "FIFO",
    "READ_DATA": "FIFO",
    # `RDATA`, not just `READ_DATA`: entropy_source names its auto-incrementing
    # read ports FIFO_RDATA / BIW_OBS_RDATA / NOISE_OBS_RDATA. A read advances
    # the pointer and decrements FIFO_STATUS.LEVEL; on an empty FIFO it also sets
    # INTR_STATUS.FIFO_UNDERFLOW and returns undefined data. Reading one to check
    # a reset value therefore destroys the state it is checking.
    "RDATA": "FIFO",
    "ERROR_FLAGS": "read-clear",
    "GENBITS": "FIFO",
    "CMD": "trigger",
    # spi_controller COMMAND: write-only segment trigger (`sw = w`, `external` in
    # spi_controller.rdl); reads return 0, so it is neither reset-checkable nor a
    # storage touch.
    "COMMAND": "trigger",
    "CMD_REQ": "trigger",
}

# Blocks the aggressive complement/all-ones bash may not enter, block-wide.
# A blanket: the reason names what the block as a whole holds, so a plain
# storage register inside one is still a legal masked touch. touch_reason
# refines these per register, which is how the storage touch reaches AES,
# HMAC, KMAC, OTBN, SECURE_DMA, SPI_CONTROLLER, WDT_TIMER and the mailboxes.
WRITE_EXCLUDE: dict[tuple[str, str | None], str] = {
    ("SECURE_DMA", None): "trigger",
    ("WDT_TIMER", None): "trigger",
    ("SEP_RESET_CTRL", None): "trigger",
    ("OTBN", None): "needs-init",
    ("AES", None): "key / trigger",
    ("HMAC", None): "key / FIFO",
    ("KMAC", None): "key / FIFO",
    ("KM_MAILBOX_SEP", None): "FIFO / trigger",
    ("AXIL_MAILBOX", None): "FIFO",
    ("SPI_CONTROLLER", None): "trigger",
}

# Registers whose write has a side effect beyond its own storage: it moves
# the LSU, changes the fabric window, re-selects the entropy source, fires a
# key wipe, or is not storage at all (read-only / write-once-set). No write
# path may touch one, so write_reason and the masked storage touch both gate
# on this table through side_effect_reason.
SIDE_EFFECT_EXCLUDE: dict[tuple[str, str | None], str] = {
    ("SEP_CPU_CTRL", "CLOCK_GATE_CTRL"): "side-effect",
    ("SEP_CPU_CTRL", "SEP_GLOBAL_BASE_ADDR"): "side-effect: fabric remap",
    ("SEP_CPU_CTRL", "SEP_LOCAL_BASE_ADDR"): "side-effect: fabric remap",
    ("SEP_CPU_CTRL", "SEP_REGION_SIZE"): "side-effect: fabric remap",
    ("SEP_CPU_CTRL", "SMU_GLOBAL_BASE_ADDR"): "side-effect: fabric remap",
    ("SEP_CPU_CTRL", "SMU_REGION_SIZE"): "side-effect: fabric remap",
    ("SEP_CPU_CTRL", "SEP_NMI_VEC_LOCK"): "woset lock",
    ("SEP_CPU_CTRL", "EXT_TRNG_SRC_SEL"): "side-effect: entropy mux",
    ("SEP_CPU_CTRL", "EXT_TRNG_SRC_SEL_LOCK"): "woset lock",
    ("SEP_CPU_CTRL", "KM_WIPE_CTRL"): "trigger",
    ("SEP_CPU_CTRL", "SEP_VERSION_ID"): "read-only",
    ("SEP_CPU_CTRL", "SEP_SW_DEBUG"): "side-effect: debug",
}

# Write bash stays on blocks whose restore cannot redirect the LSU.
# Inbound START/END stay in the sweep; inbound_addr_expected() models the wrap.
WRITE_SAFE_PREFIXES = (
    "SEP_SCRATCH_COLD",
    "SEP_SCRATCH_WARM",
    "SEP_CPU_CTRL",
    "INBOUND_FILTER_CTRL_",
)

# Anti-vacuity list, not the touch set: the touch set is every register the
# gate admits. Each of these IPs sits outside WRITE_SAFE_PREFIXES, so its only
# write coverage is the masked touch. If the export or a deny table stops
# admitting any register in one of them, the cfg raises instead of quietly
# shipping a narrower sweep.
#
# A SHADOWED candidate takes the dual write touch_write issues, so it is a
# valid storage touch; the shadowed control registers stay denied because
# their value has side effects. An INTR_ENABLE row is evidence of block decode
# and storage, not of the engine.
TOUCH_BLOCKS: tuple[str, ...] = (
    "AES",
    "HMAC",
    "KMAC",
    "OTBN",
    "SECURE_DMA",
    "SPI_CONTROLLER",
    "WDT_TIMER",
    "AXIL_MAILBOX_INBOUND_MAILBOX_0",
    "AXIL_MAILBOX_OUTBOUND_MAILBOX_0",
)

# Not usable as a plain storage RW touch (WO, sticky, trigger, W1C status,
# or multi-field encodings that reject a random mask-legal value).
_TOUCH_DENY_SUBSTR: dict[str, str] = {
    "KEY": "key material",
    "IV_": "key material",
    "DATA_IN": "datapath port",
    "DATA_OUT": "datapath port",
    "DIGEST": "hw-produced result",
    "WIPE": "trigger",
    "MSG_LENGTH": "engine-updated",
    "PREFIX_": "multi-field encoding",
    "ENTROPY_SEED": "key material",
    "LOAD_CHECKSUM": "hw-produced result",
    "INSN_CNT": "engine-updated",
    # Labels follow the IP-XACT export (regs/gen/ipxact/sep.xml).
    "ERR_BITS": "hw-updated status (read-write, volatile)",
    "FATAL_ALERT": "read-only hw status",
    "CTRL_SHADOWED": "shadowed control",
    "CFG_SHADOWED": "shadowed control",
    "CTRL_GCM": "multi-field encoding",
    "REGWEN": "sticky lock",
    "CONTROL": "trigger",
    "WDOG_CTRL": "arms the watchdog",
    "WKUP_CTRL": "arms the wakeup timer",
    "SW_RESET": "trigger",
    "CLEAR_INTR": "trigger",
}

# Entropy-complex CSRs the export marks rw but hardware owns. A sticky
# lock is never a storage touch: it changes the machine under the rest
# of the sweep.
_TOUCH_DENY_SUFFIX_HW: dict[str, str] = {
    "_STS": "hw-driven status",
    "_SM_STATE": "hw state observability",
    "COMPONENT_ID": "read-only identity",
    "GENBITS_VLD": "hw-driven valid",
    "INT_STATE_VAL": "windowed read port, not storage",
}

_TOUCH_DENY_PREFIX_HW: dict[str, str] = {
    "RESEED_COUNTER_": "hw-driven counter",
}

# Exact names: W1C / status / enable-ish multi-field CSRs that are still
# export-rw but do not behave as plain storage under a random ``x``.
_TOUCH_DENY_NAME: dict[str, str] = {
    "FIPS_LOCK": "sticky lock; setting it freezes the block for the rest of the run",
    # Both refuse a random mask-legal value:
    # HT_WATERMARK_NUM.WATERMARK_NUM carries `encode = WATERMARK_TEST`:
    # "Unsupported values are sanitized to REPCNT_HI", so a legal encoding lands
    # and any other reads back 0. NOISE_OBS_CTRL holds FLUSH[1:1], `sw = w` and
    # `singlepulse`, inside the software-usable mask -- a value with bit 1 set
    # pulses the flush and self-clears -- and its LANE_SEL sanitizes an
    # out-of-range lane to 0.
    "HT_WATERMARK_NUM": "enumerated selector; an unsupported value sanitizes",
    "NOISE_OBS_CTRL": "write-only singlepulse field inside the mask",
    "CTRL": "trigger",
    "CFG": "multi-field encoding",
    "INTR_STATE": "W1C status",
    "IRQS": "W1C status",
    "IRQP": "read-only hw status",
    "ERR_CODE": "read-only hw status",
    "ERROR_CODE": "read-only hw status",
    "ERROR_FLAGS": "read-clear status",
    "WKUP_CAUSE": "write-zero-to-clear status",
    "RANGE_VALID": "arms the range",
    # Thresholds clamp to FIFO depth; export mask is wider than storage.
    "RIRQT": "clamped to FIFO depth",
    "WIRQT": "clamped to FIFO depth",
    # Entropy CSRs need KMAC CFG / runtime; not plain POR storage.
    "ENTROPY_PERIOD": "needs KMAC cfg",
    "ENTROPY_REFRESH_HASH_CNT": "read-only hw counter",
    "ENTROPY_REFRESH_THRESHOLD_SHADOWED": "needs KMAC cfg",
}

# Remap / outbound-filter writes are reset-checked only: an unprogrammed
# alias region still rewrites a live beat, and an outbound-filter window
# programmed under a random value drops live beats. No write path may enter
# these banks, the masked storage touch included.
SIDE_EFFECT_EXCLUDE_PREFIXES: dict[str, str] = {
    "LOCAL_MASTER_ALIAS_REMAP_CTRL_": "side-effect: alias remap rewrites LSU",
    "AP_OUTPUT_REMAP_CTRL_": "side-effect: outbound remap",
    "STEE_OUTPUT_REMAP_CTRL_": "side-effect: outbound remap",
    "OUTBOUND_FILTER_CTRL_": "side-effect: outbound filter drop",
}

# Blanket bash exclusion, refined per register by touch_reason: the mailbox
# data ports are a FIFO, but IRQEN in the same block is plain storage.
WRITE_EXCLUDE_PREFIXES: dict[str, str] = {
    "AXIL_MAILBOX_": "FIFO",
}

# Beat granule. hw/ip/axi_filter/doc/index.adoc (Address Range Granule): with
# allow_burst = 0 the granule is the data bus width and address bits [2:0] are
# ignored, so the mask is one less than the bus width in bytes.
_GRANULE = AXI_BUS_BYTES - 1
_INBOUND_ADDR = frozenset({"START_ADDR", "END_ADDR"})
# Peer at reset during solo bash (each bash restores before the next reg), taken
# from the generated export rather than transcribed: the value for START_ADDR is
# the peer END_ADDR's reset, and vice versa.
_INBOUND_PEER_RESET = {
    "START_ADDR": INBOUND_FILTER_CTRL_0.reset("END_ADDR"),
    "END_ADDR": INBOUND_FILTER_CTRL_0.reset("START_ADDR"),
}


def write_mask(info: RegInfo) -> int:
    """Software-usable bits a complement write must move.

    ``KM_MAILBOX_SEP.SEP_CTRL`` carries FLUSH inside the software-usable mask:
    the field is write-1 and hardware clears it when the flush completes, so it
    never reads back what a random ``x`` wrote. The two response bits beside it
    are plain storage, so only the pulse bit leaves the mask.
    """
    mask = info.mask
    if info.block == "KM_MAILBOX_SEP" and info.name == "SEP_CTRL":
        mask &= ~KM_MAILBOX_SEP.field_mask("SEP_CTRL", "flush")
    return mask & 0xFFFF_FFFF


def inbound_addr_expected(name: str, written: int) -> int:
    """Readback after a solo START/END write with the peer at reset.

    ``allow_burst`` reset is 0, so the granule is 8 bytes
    (``hw/ip/axi_filter/doc/index.adoc``, ``filter_ctrl.rdl``):
    when START and END share a beat, START[2:0] clears and END[2:0] sets;
    otherwise the write lands. The 4 KB granule is CHK-PAGE-WIDEN.
    """
    written &= 0xFFFF_FFFF
    peer = _INBOUND_PEER_RESET[name]
    if (written >> 3) != (peer >> 3):
        return written
    if name == "START_ADDR":
        return written & ~_GRANULE
    return (written & ~_GRANULE) | _GRANULE


def _is_inbound_addr(info: RegInfo) -> bool:
    return info.block.startswith("INBOUND_FILTER_CTRL_") and info.name in _INBOUND_ADDR


def touch_reason(info: RegInfo) -> str | None:
    """Why this register does not behave as plain storage, or None if it does.

    Mirrors reset_reason/write_reason: every exclusion carries a reason the
    cfg tallies, so the summary accounts for every inventory register.
    Export symbols that lack DEFAULT/struct are counted by
    ``iter_register_walk`` (``nometa``), not here.

    Not a complete gate on its own. It answers "is the storage plain?", not
    "is a write safe?", so a caller must also clear side_effect_reason before
    it writes. Alone it admits the outbound-filter, alias-remap and
    fabric-remap banks.
    """
    why = reset_reason(info)
    if why is not None:
        return why
    # Software cannot write a read-only register, so the touch would write
    # nothing and then compare the readback against the value it meant to
    # write. The reset arms above do not cover this one: a read-only register
    # that DOES declare a reset (abr_reg.rdl MLDSA_VERIFY_RES, `sw = r` with
    # `resetsignal`) is a real reset-compare row and a bogus touch row.
    if info.access.access == frozenset({"read-only"}):
        return "sw=r; a write does not reach storage"
    if info.mask == 0:
        return "no software-usable field"
    why = _suffix_reason(info.name)
    if why is not None:
        return why
    why = _TOUCH_DENY_NAME.get(info.name)
    if why is not None:
        return why
    for frag, reason in _TOUCH_DENY_SUBSTR.items():
        if frag in info.name:
            return reason
    for suffix, reason in _TOUCH_DENY_SUFFIX_HW.items():
        if info.name == suffix or info.name.endswith(suffix):
            return reason
    for prefix, reason in _TOUCH_DENY_PREFIX_HW.items():
        if info.name.startswith(prefix):
            return reason
    return None


def touch_write_value(before: int, mask: int, rng: SepSeededRng) -> int:
    """Seed-derived ``x`` in the software field; differs from ``before & mask``."""
    field = rng.getrandbits(32) & mask
    cur = before & mask
    if mask != 0 and field == cur:
        field ^= mask & -mask
    return (before & ~mask & 0xFFFF_FFFF) | field


def _lookup(table: dict[tuple[str, str | None], str], block: str, name: str) -> str | None:
    return table.get((block, name)) or table.get((block, None))


def _suffix_reason(name: str) -> str | None:
    for suffix, reason in RESET_EXCLUDE_SUFFIX.items():
        if name == suffix or name.endswith("_" + suffix):
            return reason
    if "KEY" in name.split("_"):
        return "key"
    return None


def reset_reason(info: RegInfo) -> str | None:
    """Why a reset read-compare on this register proves nothing, or None.

    The two access-shaped arms come first because they are derived from the
    RDL, not from a name: a register the RDL declares write-only returns no
    storage on a read, and a read-only register with no declared reset is
    driven by hardware, so the generated ``_REG_DEFAULT`` is a field default
    and not a POR value. Comparing a read against either one measures the
    generator. Both shapes read back 0 against a default of 0 far more often
    than not, so leaving them in makes the compare pass without the DUT having
    demonstrated anything.

    The third arm applies the same rule bit by bit: a field with no RDL reset
    has no POR value, and ``_REG_DEFAULT`` holds a 0 placeholder for it. A word
    whose every storage bit is such a field has nothing to compare, so it is
    skipped; a word with only some such bits stays a row, and ``check_reset``
    masks those bits out (``reset_compare_mask``).
    """
    if info.access.write_only:
        return "sw=w; a read does not return storage"
    if info.access.hw_driven:
        return "sw=r with no declared reset; the export DEFAULT is not a POR value"
    if info.unreset and (info.mask_all & ~info.unreset) == 0:
        return "no field with an RDL reset; the export DEFAULT is a placeholder"
    hit = _lookup(RESET_EXCLUDE, info.block, info.name) or _suffix_reason(info.name)
    if hit is not None:
        return hit
    if info.block == "ENTROPY_SOURCE" and info.name in esrc_reset_skip():
        return "hw-owned; read value is not the POR value"
    return None


def reset_compare_mask(info: RegInfo) -> int:
    """Bits a reset read-compare grades: every bit except unreset-field bits.

    Reserved bits stay in the compare (they read 0). Fields with no RDL reset
    leave it, because ``info.reset`` holds a generator placeholder for them.
    """
    return ~info.unreset & 0xFFFF_FFFF


def side_effect_reason(info: RegInfo) -> str | None:
    """Why no write path may touch this register, or None if a write is safe.

    The side-effect half of write_reason, shared with the masked storage touch
    so the two gates cannot drift apart. Covers the registers whose write
    reaches past their own storage -- fabric and alias remap, outbound filter,
    the entropy mux, the write-once-set locks -- plus the ones that are not
    storage at all. FILTER_CONFIG carries a read-only field in the same word,
    so a full-mask compare on it measures the generator, not the DUT.
    """
    if info.name == "FILTER_CONFIG":
        return "read-only field in word"
    hit = _lookup(SIDE_EFFECT_EXCLUDE, info.block, info.name)
    if hit is not None:
        return hit
    for prefix, reason in SIDE_EFFECT_EXCLUDE_PREFIXES.items():
        if info.block.startswith(prefix):
            return reason
    return None


def write_reason(info: RegInfo) -> str | None:
    if reset_reason(info) is not None:
        return reset_reason(info)
    if info.mask == 0:
        return "no software-usable field"
    hit = side_effect_reason(info)
    if hit is not None:
        return hit
    hit = _lookup(WRITE_EXCLUDE, info.block, info.name)
    if hit is not None:
        return hit
    for prefix, reason in WRITE_EXCLUDE_PREFIXES.items():
        if info.block.startswith(prefix):
            return reason
    if not any(info.block == p or info.block.startswith(p) for p in WRITE_SAFE_PREFIXES):
        return "not a no-side-effect block"
    return None


class SepRegBitBashCfg:
    """Seeded walk of the generated register export.

    Discrete cells every seed: every reset-eligible register, every
    bash-safe register, then every register the masked storage touch admits.
    The seed shuffles block order, picks the touch values, and picks whether
    the complement write or the all-ones write runs first. It does not change
    which cells run, so coverage is the same at every seed.
    """

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        walk = iter_register_walk()
        inventory = list(walk.regs)
        if not inventory:
            raise RuntimeError("generated register export is empty")
        self.export = walk.export
        self.inventory = walk.inventory
        self.nometa = walk.nometa

        reset_by_block: dict[str, list[RegInfo]] = defaultdict(list)
        write_by_block: dict[str, list[RegInfo]] = defaultdict(list)
        self.reset_skipped: dict[str, int] = defaultdict(int)
        self.write_skipped: dict[str, int] = defaultdict(int)
        for info in inventory:
            why_r = reset_reason(info)
            if why_r is None:
                reset_by_block[info.block].append(info)
            else:
                self.reset_skipped[why_r] += 1
            why_w = write_reason(info)
            if why_w is None:
                write_by_block[info.block].append(info)
            else:
                self.write_skipped[why_w] += 1

        self.reset_blocks = list(reset_by_block)
        rng_order = SepSeededRng(seed ^ 0xA5A5)
        # Shuffle a copy; do not consume the same stream as ones_first.
        for i in range(len(self.reset_blocks) - 1, 0, -1):
            j = rng_order.randrange(0, i + 1)
            self.reset_blocks[i], self.reset_blocks[j] = (
                self.reset_blocks[j],
                self.reset_blocks[i],
            )
        self.write_blocks = [b for b in self.reset_blocks if b in write_by_block]
        self.ones_first = bool(rng.getrandbits(1))
        self.reset_regs = [info for b in self.reset_blocks for info in reset_by_block[b]]
        self.write_regs = [info for b in self.write_blocks for info in write_by_block[b]]
        if not self.reset_regs:
            raise RuntimeError("reset sweep is empty after exclusions")
        if not self.write_regs:
            raise RuntimeError("write sweep is empty after exclusions")
        inbound_addr = [
            info
            for info in self.write_regs
            if info.block.startswith("INBOUND_FILTER_CTRL_") and info.name in _INBOUND_ADDR
        ]
        if len(inbound_addr) != 32:
            raise RuntimeError(
                f"inbound START/END write sweep is {len(inbound_addr)}, "
                "expected 32 (16 entries x START/END)"
            )

        # Masked storage touch: every register that is plain storage AND whose
        # write has no side effect. touch_reason alone would admit the
        # outbound-filter, alias-remap and fabric-remap banks, so the two
        # halves are ANDed and the side-effect half is the shared predicate,
        # not a second copy of the tables.
        by_block: dict[str, list[RegInfo]] = defaultdict(list)
        self.touch_skipped: dict[str, int] = defaultdict(int)
        for info in inventory:
            why_t = touch_reason(info) or side_effect_reason(info)
            if why_t is None:
                by_block[info.block].append(info)
            else:
                self.touch_skipped[why_t] += 1
        for block in TOUCH_BLOCKS:
            if not by_block.get(block):
                raise RuntimeError(f"TOUCH_BLOCKS {block}: no RW storage candidate in export")
        rng_touch = SepSeededRng(seed ^ 0xC0FFEE)
        touch: list[tuple[RegInfo, int]] = []
        # touch_reason defers to reset_reason first, so every admitted block is
        # also a reset block: the seed-shuffled reset order carries the touch.
        touch_blocks = [b for b in self.reset_blocks if b in by_block]
        for block in touch_blocks:
            for info in by_block[block]:
                # Value uses reset as the pre-touch image (bring-up leaves POR).
                # Draw over the compared mask, so the value always moves a bit
                # the readback grades; bits outside it stay at reset.
                x = touch_write_value(info.reset, write_mask(info), rng_touch)
                touch.append((info, x))
        self.touch_blocks = touch_blocks
        self.touch_regs = tuple(touch)
        if not self.touch_regs:
            raise RuntimeError("storage touch sweep is empty after exclusions")
        admitted = sum(len(regs) for regs in by_block.values())
        if len(self.touch_regs) != admitted:
            raise RuntimeError(
                f"storage touch sweep is {len(self.touch_regs)} of {admitted} "
                "admitted registers; the block order dropped some"
            )

    def summary(self) -> str:
        skip_r = " ".join(f"{k}={v}" for k, v in sorted(self.reset_skipped.items()))
        skip_w = " ".join(f"{k}={v}" for k, v in sorted(self.write_skipped.items()))
        skip_t = " ".join(f"{k}={v}" for k, v in sorted(self.touch_skipped.items()))
        per_block: dict[str, int] = defaultdict(int)
        for info, _x in self.touch_regs:
            per_block[info.block] += 1
        touches = ",".join(f"{b}={per_block[b]}" for b in self.touch_blocks)
        return (
            f"seed={self.seed} ones_first={int(self.ones_first)} "
            f"export={self.export} inventory={self.inventory} nometa={self.nometa} "
            f"reset={len(self.reset_regs)}/{len(self.reset_blocks)}blocks "
            f"write={len(self.write_regs)}/{len(self.write_blocks)}blocks "
            f"touch={len(self.touch_regs)}/{len(self.touch_blocks)}blocks"
            f"[{touches}] "
            f"reset_skip=[{skip_r}] write_skip=[{skip_w}] "
            f"touch_skip=[{skip_t}]"
        )


class SepRegBitBash:
    """Frontdoor AXI sweep driven by SepRegBitBashCfg."""

    def __init__(self, test) -> None:
        self.test = test
        self.log = test.logger
        self.reset_ok = 0
        # Reset rows compared with unreset-field bits masked out; a subset of
        # reset_ok, reported so the PASS line does not claim a full-word match.
        self.reset_masked = 0
        self.write_ok = 0
        self.lands_ok = 0
        self.touch_ok = 0
        # Falsifiable-only tallies, reported separately from the register
        # count. A register whose software-usable mask is all ones has no
        # out-of-mask bits, so its CHK-RO compare cannot fail; one with
        # reserved=0 gives CHK-RESERVED nothing to catch. Counting those into
        # the PASS line would advertise evidence the sweep never produced.
        self.ro_ok = 0
        self.reserved_ok = 0
        # Inbound START/END prove the same-beat wrap model plus mask[31:3];
        # bits [2:0] are pinned by that model compare, not by the move, so
        # they are not full-mask CHK-WRITE-LANDS evidence.
        self.lands_upper_ok = 0

    async def _rd(self, addr: int, *, name: str) -> tuple[int, int]:
        seq = SepAxiAccessSeq(
            f"bash_rd_{name}",
            op=SepAxiOp.READ,
            addr=addr,
            length=4,
            size=2,
        )
        await self.test.start_seq(seq)
        return seq.resp_code, seq.rdata & 0xFFFF_FFFF

    async def _wr(self, addr: int, data: int, *, name: str) -> int:
        seq = SepAxiAccessSeq(
            f"bash_wr_{name}",
            op=SepAxiOp.WRITE,
            addr=addr,
            wdata=data,
            length=4,
            size=2,
        )
        await self.test.start_seq(seq)
        return seq.resp_code

    async def check_reset(self, info: RegInfo) -> str | None:
        resp, got = await self._rd(info.addr, name=f"{info.block}_{info.name}")
        if resp != 0:
            return (
                f"CHK-RESET FAIL: {info.block}.{info.name} @0x{info.addr:08x} "
                f"resp={resp}, expected OKAY"
            )
        keep = reset_compare_mask(info)
        if (got & keep) != (info.reset & keep):
            return (
                f"CHK-RESET FAIL: {info.block}.{info.name} @0x{info.addr:08x} "
                f"read 0x{got:08x} != reset 0x{info.reset:08x} under mask 0x{keep:08x}"
            )
        self.reset_ok += 1
        if keep != 0xFFFF_FFFF:
            self.reset_masked += 1
            self.log.info(
                "CHK-RESET masked: %s.%s @0x%08x read 0x%08x, reset 0x%08x under "
                "mask 0x%08x (unreset-field bits 0x%08x not graded)",
                info.block,
                info.name,
                info.addr,
                got,
                info.reset,
                keep,
                info.unreset,
            )
        return None

    async def bash_write(self, info: RegInfo, *, ones_first: bool) -> None:
        tag = f"{info.block}_{info.name}"
        resp, before = await self._rd(info.addr, name=tag)
        assert resp == 0, f"{info.block}.{info.name} @0x{info.addr:08x} resp={resp} before write"
        inbound = _is_inbound_addr(info)

        async def do_complement(entry: int) -> int:
            mask = write_mask(info)
            pat = (~entry) & 0xFFFF_FFFF
            wr = await self._wr(info.addr, pat, name=f"{tag}_comp")
            assert wr == 0, f"{info.block}.{info.name} complement write resp={wr}"
            rd, after = await self._rd(info.addr, name=f"{tag}_comp")
            assert rd == 0, f"{info.block}.{info.name} complement read resp={rd}"
            if inbound:
                expected = inbound_addr_expected(info.name, pat)
                assert after == expected, (
                    f"CHK-WRITE FAIL: {info.block}.{info.name} wrote "
                    f"0x{pat:08x} read 0x{after:08x}, expected 0x{expected:08x} "
                    f"(same-beat wrap vs peer reset)"
                )
                upper = mask & ~_GRANULE
                moved_upper = (entry ^ after) & upper
                assert moved_upper == upper, (
                    f"CHK-WRITE-LANDS FAIL: {info.block}.{info.name} upper "
                    f"mask 0x{upper:08x} moved 0x{moved_upper:08x} "
                    f"(before 0x{entry:08x} after 0x{after:08x})"
                )
                self.lands_upper_ok += 1
                return after
            moved = (entry ^ after) & 0xFFFF_FFFF
            leaked = moved & ~mask
            assert leaked == 0, (
                f"CHK-RO FAIL: {info.block}.{info.name} bits outside mask "
                f"0x{mask:08x} moved 0x{leaked:08x} "
                f"(before 0x{entry:08x} after 0x{after:08x})"
            )
            if (~mask) & 0xFFFF_FFFF:
                self.ro_ok += 1
            # The reserved-bit compare runs only when the register has a
            # software-usable field and no field is masked out of the write mask.
            if mask != 0 and mask == info.mask:
                reserved = after & info.reserved
                assert reserved == 0, (
                    f"CHK-RESERVED FAIL: {info.block}.{info.name} reserved "
                    f"0x{info.reserved:08x} read 0x{reserved:08x}"
                )
                if info.reserved:
                    self.reserved_ok += 1
            if mask != 0:
                landed = moved & mask
                assert landed == mask, (
                    f"CHK-WRITE-LANDS FAIL: {info.block}.{info.name} mask "
                    f"0x{mask:08x} moved 0x{landed:08x} "
                    f"(before 0x{entry:08x} after 0x{after:08x})"
                )
                self.lands_ok += 1
            return after

        async def do_ones(entry: int) -> int:
            mask = write_mask(info)
            pat = 0xFFFF_FFFF
            wr = await self._wr(info.addr, pat, name=f"{tag}_ones")
            assert wr == 0, f"{info.block}.{info.name} all-ones write resp={wr}"
            rd, after = await self._rd(info.addr, name=f"{tag}_ones")
            assert rd == 0, f"{info.block}.{info.name} all-ones read resp={rd}"
            if inbound:
                expected = inbound_addr_expected(info.name, pat)
                assert after == expected, (
                    f"CHK-WRITE FAIL: {info.block}.{info.name} all-ones read "
                    f"0x{after:08x}, expected 0x{expected:08x}"
                )
                return after
            leaked = (entry ^ after) & ~mask & 0xFFFF_FFFF
            assert leaked == 0, (
                f"CHK-RO FAIL: {info.block}.{info.name} all-ones moved outside mask 0x{leaked:08x}"
            )
            if mask != 0 and mask == info.mask:
                reserved = after & info.reserved
                assert reserved == 0, (
                    f"CHK-RESERVED FAIL: {info.block}.{info.name} reserved "
                    f"after all-ones 0x{reserved:08x}"
                )
            return after

        if ones_first:
            mid = await do_ones(before)
            await do_complement(mid)
        else:
            mid = await do_complement(before)
            await do_ones(mid)

        wr = await self._wr(info.addr, info.reset, name=f"{tag}_restore")
        assert wr == 0, f"{info.block}.{info.name} restore write resp={wr}"
        rd, got = await self._rd(info.addr, name=f"{tag}_restore")
        assert rd == 0 and got == info.reset, (
            f"{info.block}.{info.name} restore read 0x{got:08x} "
            f"resp={rd} != reset 0x{info.reset:08x}"
        )
        self.write_ok += 1

    async def touch_write(self, info: RegInfo, x: int) -> None:
        """RW storage proof: write ``x``, check ``(read & mask) == (x & mask)``.

        Inbound-filter START/END compare against the same-beat wrap model
        instead of ``x``: the peer is at reset here (each touch restores before
        the next), so ``inbound_addr_expected`` is the readback contract. A
        raw ``x`` compare would fail on the RTL widen of bits [2:0].
        """
        tag = f"touch_{info.block}_{info.name}"
        mask = write_mask(info)
        shadowed = "SHADOWED" in info.name
        x &= 0xFFFF_FFFF
        resp, before = await self._rd(info.addr, name=tag)
        assert resp == 0, (
            f"CHK-BLOCK-TOUCH FAIL: {info.block}.{info.name} @0x{info.addr:08x} "
            f"resp={resp} before write"
        )
        wr = await self._wr(info.addr, x, name=f"{tag}_wr")
        assert wr == 0, f"CHK-BLOCK-TOUCH FAIL: {info.block}.{info.name} write resp={wr}"
        if shadowed:
            wr = await self._wr(info.addr, x, name=f"{tag}_wr2")
            assert wr == 0, (
                f"CHK-BLOCK-TOUCH FAIL: {info.block}.{info.name} shadow commit resp={wr}"
            )
        rd, after = await self._rd(info.addr, name=f"{tag}_rd")
        assert rd == 0, f"CHK-BLOCK-TOUCH FAIL: {info.block}.{info.name} read resp={rd}"
        want = inbound_addr_expected(info.name, x) if _is_inbound_addr(info) else x
        assert (after & mask) == (want & mask), (
            f"CHK-BLOCK-TOUCH FAIL: {info.block}.{info.name} "
            f"(read 0x{after:08x} & mask 0x{mask:08x})=0x{after & mask:08x} "
            f"!= (expected 0x{want:08x} & mask)=0x{want & mask:08x} "
            f"(wrote 0x{x:08x})"
        )
        leaked = (before ^ after) & ~mask & 0xFFFF_FFFF
        assert leaked == 0, (
            f"CHK-BLOCK-TOUCH FAIL: {info.block}.{info.name} bits outside mask moved 0x{leaked:08x}"
        )
        wr = await self._wr(info.addr, info.reset, name=f"{tag}_restore")
        assert wr == 0, f"CHK-BLOCK-TOUCH FAIL: {info.block}.{info.name} restore resp={wr}"
        if shadowed:
            wr = await self._wr(info.addr, info.reset, name=f"{tag}_restore2")
            assert wr == 0, (
                f"CHK-BLOCK-TOUCH FAIL: {info.block}.{info.name} shadow restore resp={wr}"
            )
        rd, got = await self._rd(info.addr, name=f"{tag}_restore")
        assert rd == 0 and got == info.reset, (
            f"CHK-BLOCK-TOUCH FAIL: {info.block}.{info.name} restore read "
            f"0x{got:08x} != reset 0x{info.reset:08x}"
        )
        self.touch_ok += 1


def _selftest() -> None:
    start = RegInfo(
        block="INBOUND_FILTER_CTRL_0_",
        name="START_ADDR",
        addr=0,
        reset=0,
        mask=0xFFFF_FFFF,
        mask_all=0xFFFF_FFFF,
    )
    end = RegInfo(
        block="INBOUND_FILTER_CTRL_0_",
        name="END_ADDR",
        addr=0,
        reset=7,
        mask=0xFFFF_FFFF,
        mask_all=0xFFFF_FFFF,
    )
    scratch = RegInfo(
        block="SEP_SCRATCH_COLD",
        name="SCRATCH_0_",
        addr=0,
        reset=0,
        mask=0xFFFF_FFFF,
        mask_all=0xFFFF_FFFF,
    )
    assert write_mask(start) == 0xFFFF_FFFF
    assert write_mask(end) == 0xFFFF_FFFF
    assert write_mask(scratch) == 0xFFFF_FFFF
    assert inbound_addr_expected("START_ADDR", 0xFFFF_FFFF) == 0xFFFF_FFFF
    assert inbound_addr_expected("START_ADDR", 0x5) == 0x0
    assert inbound_addr_expected("END_ADDR", 0xFFFF_FFF8) == 0xFFFF_FFF8
    assert inbound_addr_expected("END_ADDR", 0x0) == 0x7
    # touch_reason admits the outbound-filter bank; the side-effect half is
    # what keeps a write off it. Both halves must be consulted.
    outbound = RegInfo(
        block="OUTBOUND_FILTER_CTRL_0_",
        name="START_ADDR",
        addr=0,
        reset=0,
        mask=0xFFFF_FFFF,
        mask_all=0xFFFF_FFFF,
    )
    filter_cfg = RegInfo(
        block="INBOUND_FILTER_CTRL_0_",
        name="FILTER_CONFIG",
        addr=0,
        reset=0,
        mask=0xFFFF_FFFF,
        mask_all=0xFFFF_FFFF,
    )
    assert touch_reason(outbound) is None
    assert side_effect_reason(outbound) == "side-effect: outbound filter drop"
    assert side_effect_reason(filter_cfg) == "read-only field in word"
    assert side_effect_reason(scratch) is None
    assert side_effect_reason(start) is None
    assert write_reason(scratch) is None
    assert write_reason(outbound) == "side-effect: outbound filter drop"

    # The three access-shaped arms. Every RegInfo above carries the default
    # read-write storage shape, so without these the arms are never taken here
    # and a change to them shows up only in a simulation.
    def shaped(access: str, declared_reset: bool) -> RegInfo:
        return RegInfo(
            block="ABR",
            name="SHAPE_PROBE",
            addr=0,
            reset=0xF,
            mask=0xFFFF_FFFF,
            mask_all=0xFFFF_FFFF,
            access=RegAccess(frozenset({access}), declared_reset),
        )

    write_only = shaped("write-only", True)
    hw_driven = shaped("read-only", False)
    read_only = shaped("read-only", True)
    assert reset_reason(write_only) == "sw=w; a read does not return storage"
    assert reset_reason(hw_driven) == (
        "sw=r with no declared reset; the export DEFAULT is not a POR value"
    )
    # Read-only WITH a reset stays a reset row, and only the touch refuses it.
    assert reset_reason(read_only) is None

    # Unreset fields. A word made only of fields with no RDL reset is skipped;
    # a word with some is a reset row compared under a mask that drops those
    # bits and keeps reserved bits.
    def unreset_probe(unreset: int, mask_all: int) -> RegInfo:
        return RegInfo(
            block="HMAC",
            name="UNRESET_PROBE",
            addr=0,
            reset=0x4100,
            mask=mask_all,
            mask_all=mask_all,
            unreset=unreset,
        )

    all_unreset = unreset_probe(0xFFFF_FFFF, 0xFFFF_FFFF)
    part_unreset = unreset_probe(0x3, 0xFF_FF03)
    assert reset_reason(all_unreset) == (
        "no field with an RDL reset; the export DEFAULT is a placeholder"
    )
    assert reset_reason(part_unreset) is None
    assert reset_compare_mask(part_unreset) == 0xFFFF_FFFC
    assert reset_compare_mask(scratch) == 0xFFFF_FFFF
    assert touch_reason(read_only) == "sw=r; a write does not reach storage"
    assert touch_reason(scratch) is None

    rng = SepSeededRng(1)
    v = touch_write_value(0x11, 0xF, rng)
    assert (v & ~0xF) == (0x11 & ~0xF)
    assert (v & 0xF) != (0x11 & 0xF)


_selftest()
