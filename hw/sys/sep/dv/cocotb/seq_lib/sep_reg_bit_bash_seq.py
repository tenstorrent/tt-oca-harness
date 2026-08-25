# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CSR reset / RW / RO / reserved sweep for sep_reg_bit_bash_rand_test.

Walks the generated SystemRDL export in env/sep_reg_meta.py. Not a RAL model.
SepRegBitBashCfg is the single source of truth for which registers are reset-
checked, which take a write bash, and the seed-selected walk order.

Exclusions are data: one reason string per entry. A silent skip is a bug.
Inbound-filter START/END are write-excluded: the export mask is 32 bits
and the hardware forces [2:0] (END_ADDR reset 0x7).
"""

from __future__ import annotations

from collections import defaultdict

from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from sep_reg_meta import RegInfo, iter_registers
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq

# (block, name) -> reason. name None = every register in the block.
# kind is consulted by the cfg, not stored here: RESET_EXCLUDE vs WRITE_EXCLUDE.
RESET_EXCLUDE: dict[tuple[str, str | None], str] = {
    ("OCH_SEP_TOP", None): "top container, not a register block",
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
    ("SEP_CPU_CTRL", "SEP_STRAPS"): "hw-driven straps",
    ("SEP_CPU_CTRL", "TIMEOUT_CLEAR"): "write-only",
    ("SEP_CPU_CTRL", "TIMEOUT_MODE"): "write-only",
    ("WDT_TIMER", "WKUP_COUNT_HI"): "hw-driven timer",
    ("WDT_TIMER", "WKUP_COUNT_LO"): "hw-driven timer",
    ("WDT_TIMER", "WDOG_COUNT"): "hw-driven timer",
}

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
    "GENBITS": "FIFO",
    "CMD": "trigger",
    "CMD_REQ": "trigger",
}

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
WRITE_SAFE_PREFIXES = (
    "SEP_SCRATCH_COLD",
    "SEP_SCRATCH_WARM",
    "SEP_CPU_CTRL",
)

# Remap / filter writes are reset-checked only: an unprogrammed alias
# region still rewrites a live beat, and inbound START/END are granule-
# aligned so a full-mask complement cannot land (END_ADDR[2:0] stays 1).
WRITE_EXCLUDE_PREFIXES: dict[str, str] = {
    "LOCAL_MASTER_ALIAS_REMAP_CTRL_": "side-effect: alias remap rewrites LSU",
    "AP_OUTPUT_REMAP_CTRL_": "side-effect: outbound remap",
    "STEE_OUTPUT_REMAP_CTRL_": "side-effect: outbound remap",
    "OUTBOUND_FILTER_CTRL_": "side-effect: outbound filter drop",
    "INBOUND_FILTER_CTRL_": "granule-aligned addr; live filter side-effect",
    "AXIL_MAILBOX_": "FIFO",
}


def _lookup(
    table: dict[tuple[str, str | None], str], block: str, name: str
) -> str | None:
    return table.get((block, name)) or table.get((block, None))


def _suffix_reason(name: str) -> str | None:
    for suffix, reason in RESET_EXCLUDE_SUFFIX.items():
        if name == suffix or name.endswith("_" + suffix):
            return reason
    if "KEY" in name.split("_"):
        return "key"
    return None


def reset_reason(info: RegInfo) -> str | None:
    return _lookup(RESET_EXCLUDE, info.block, info.name) or _suffix_reason(info.name)


def write_reason(info: RegInfo) -> str | None:
    if reset_reason(info) is not None:
        return reset_reason(info)
    if info.mask == 0:
        return "no software-usable field"
    if info.name == "FILTER_CONFIG":
        return "read-only field in word"
    hit = _lookup(WRITE_EXCLUDE, info.block, info.name)
    if hit is not None:
        return hit
    for prefix, reason in WRITE_EXCLUDE_PREFIXES.items():
        if info.block.startswith(prefix):
            return reason
    if not any(
        info.block == p or info.block.startswith(p) for p in WRITE_SAFE_PREFIXES
    ):
        return "not a no-side-effect block"
    return None


class SepRegBitBashCfg:
    """Seeded walk of the generated register export.

    Discrete cells every seed: every reset-eligible register, then every
    write-safe register. The seed shuffles block order and whether the
    complement write or the all-ones write runs first.
    """

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        inventory = iter_registers()
        if not inventory:
            raise RuntimeError("generated register export is empty")

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
                self.reset_blocks[j], self.reset_blocks[i]
            )
        self.write_blocks = [b for b in self.reset_blocks if b in write_by_block]
        self.ones_first = bool(rng.getrandbits(1))
        self.reset_regs = [info for b in self.reset_blocks for info in reset_by_block[b]]
        self.write_regs = [info for b in self.write_blocks for info in write_by_block[b]]
        if not self.reset_regs:
            raise RuntimeError("reset sweep is empty after exclusions")
        if not self.write_regs:
            raise RuntimeError("write sweep is empty after exclusions")

    def summary(self) -> str:
        skip_r = " ".join(f"{k}={v}" for k, v in sorted(self.reset_skipped.items()))
        skip_w = " ".join(f"{k}={v}" for k, v in sorted(self.write_skipped.items()))
        return (
            f"seed={self.seed} ones_first={int(self.ones_first)} "
            f"reset={len(self.reset_regs)}/{len(self.reset_blocks)}blocks "
            f"write={len(self.write_regs)}/{len(self.write_blocks)}blocks "
            f"reset_skip=[{skip_r}] write_skip=[{skip_w}]"
        )


class SepRegBitBash:
    """Frontdoor AXI sweep driven by SepRegBitBashCfg."""

    def __init__(self, test) -> None:
        self.test = test
        self.log = test.logger
        self.reset_ok = 0
        self.write_ok = 0
        self.lands_ok = 0

    async def _rd(self, addr: int, *, name: str) -> tuple[int, int]:
        seq = SepAxiAccessSeq(
            f"bash_rd_{name}", op=SepAxiOp.READ, addr=addr, length=4, size=2,
        )
        await self.test.start_seq(seq)
        return seq.resp_code, seq.rdata & 0xFFFF_FFFF

    async def _wr(self, addr: int, data: int, *, name: str) -> int:
        seq = SepAxiAccessSeq(
            f"bash_wr_{name}", op=SepAxiOp.WRITE, addr=addr, wdata=data,
            length=4, size=2,
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
        if got != info.reset:
            return (
                f"CHK-RESET FAIL: {info.block}.{info.name} @0x{info.addr:08x} "
                f"read 0x{got:08x} != reset 0x{info.reset:08x}"
            )
        self.reset_ok += 1
        return None

    async def bash_write(self, info: RegInfo, *, ones_first: bool) -> None:
        tag = f"{info.block}_{info.name}"
        resp, before = await self._rd(info.addr, name=tag)
        assert resp == 0, (
            f"{info.block}.{info.name} @0x{info.addr:08x} resp={resp} before write"
        )

        async def do_complement(entry: int) -> int:
            pat = (~entry) & 0xFFFF_FFFF
            wr = await self._wr(info.addr, pat, name=f"{tag}_comp")
            assert wr == 0, (
                f"{info.block}.{info.name} complement write resp={wr}"
            )
            rd, after = await self._rd(info.addr, name=f"{tag}_comp")
            assert rd == 0, (
                f"{info.block}.{info.name} complement read resp={rd}"
            )
            moved = (entry ^ after) & 0xFFFF_FFFF
            leaked = moved & ~info.mask
            assert leaked == 0, (
                f"CHK-RO FAIL: {info.block}.{info.name} bits outside mask "
                f"0x{info.mask:08x} moved 0x{leaked:08x} "
                f"(before 0x{entry:08x} after 0x{after:08x})"
            )
            reserved = after & info.reserved
            # TIMEOUT_* placeholders: mask=0 and mask_all=1, so the lone
            # reserved bit is real storage. Skip the reserved-must-be-0
            # check when there is no software-usable field.
            if info.mask != 0:
                assert reserved == 0, (
                    f"CHK-RESERVED FAIL: {info.block}.{info.name} reserved "
                    f"0x{info.reserved:08x} read 0x{reserved:08x}"
                )
                landed = moved & info.mask
                assert landed == info.mask, (
                    f"CHK-WRITE-LANDS FAIL: {info.block}.{info.name} mask "
                    f"0x{info.mask:08x} moved 0x{landed:08x} "
                    f"(before 0x{entry:08x} after 0x{after:08x})"
                )
                self.lands_ok += 1
            return after

        async def do_ones(entry: int) -> int:
            wr = await self._wr(info.addr, 0xFFFF_FFFF, name=f"{tag}_ones")
            assert wr == 0, (
                f"{info.block}.{info.name} all-ones write resp={wr}"
            )
            rd, after = await self._rd(info.addr, name=f"{tag}_ones")
            assert rd == 0, (
                f"{info.block}.{info.name} all-ones read resp={rd}"
            )
            leaked = (entry ^ after) & ~info.mask & 0xFFFF_FFFF
            assert leaked == 0, (
                f"CHK-RO FAIL: {info.block}.{info.name} all-ones moved "
                f"outside mask 0x{leaked:08x}"
            )
            if info.mask != 0:
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
        assert wr == 0, (
            f"{info.block}.{info.name} restore write resp={wr}"
        )
        rd, got = await self._rd(info.addr, name=f"{tag}_restore")
        assert rd == 0 and got == info.reset, (
            f"{info.block}.{info.name} restore read 0x{got:08x} "
            f"resp={rd} != reset 0x{info.reset:08x}"
        )
        self.write_ok += 1
