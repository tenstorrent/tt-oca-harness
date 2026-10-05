# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Every SRAM byte lane, data pattern, boundary word and address bit reads back exactly.

Provenance: OCAH `sep_sram_uvm_byte_strobe`, `..._byte_pattern`, `..._data_pattern`,
`..._addr_boundary`, `..._write_read`, `..._sequential_access`. Exercises the external scratch SRAM
(0x1000_0000, 256 KiB) over the CPU-LSU AXI splice (no_cpu) beyond the
smoke (a single 64-bit R/W + one 32-bit partial).

`[RANDCFG]` -- ``SepSramBreadthCfg`` is the single source of truth for both the
DUT programming and the golden expectations. Required coverage is walked
deterministically so one seed never skips a cell; only legal knobs are
seed-randomized:
  * deterministic required cells: all 36 contiguous WSTRB masks (all 8 one-hot
    lanes + every contiguous multi-byte run); the required data patterns
    (0xAAAA/0x5555, walking one, walking zero, one fixed mixed word); the
    base + top-valid boundary words; a sequential window of >= 4 words.
  * randomized legal knobs: WSTRB mask order, the SRAM region offsets, the
    init/new/pattern data values, the sequential-window length, plus a few extra
    random data patterns -- all masked so they read back exactly.

This leaf drives single-beat accesses only. INCR bursts are
sep_sram_inbound_burst_attr_test, and refused FIXED/WRAP bursts are
sep_sram_burst_type_test. WSTRB=0x00 is excluded (undefined). Non-contiguous
WSTRB masks (e.g. 0x05) are not walked: cocotbext-axi derives the
strobe from addr+length (contiguous only), and this master has no explicit-strobe
write.

Checks (each value-compares an exact read-back against the cfg golden + logs a
positive PASS line):
  CHK-WSTRB    : every contiguous WSTRB mask changes only its byte lanes; all
                 neighbor lanes preserved (independent ``apply_wstrb`` golden).
  CHK-PATTERN  : each cfg data pattern reads back exactly: 0xAAAA/0x5555, a
                 walking one and a walking zero over all 64 bit positions, and
                 seed-random extras.
  CHK-BOUNDARY : the base word and the top valid word R/W read back exactly.
  CHK-SEQ      : a run of consecutive single-beat 64-bit words, per-word integrity.
  CHK-NONVAC   : two addresses hold complementary written values, so a
                 stuck read path fails.
  CHK-ADDR-LINES: the base word, a word at every power-of-two offset up to
                 half the generated SRAM size, and the top word each hold their
                 own value after all are written, so every SRAM address bit
                 selects distinct storage; the offsets at or above 0x1_0000
                 are the upper 192 KiB of the 256 KiB SRAM.

Run mode: no_cpu with +skip_fuse_sense (SRAM reached via the xbar sram port; no OTP read).
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_sram_breadth_seq import (
    WALKING_ONE_PATTERNS,
    WALKING_ZERO_PATTERNS,
    SepSramBreadth,
    SepSramBreadthCfg,
)


@pyuvm.test()
class sep_sram_datapath_breadth_test(sep_base_test):
    """Each RANDCFG cell (strobe, pattern, boundary, sequence, address line) reads back exactly."""

    async def run_scenario(self) -> None:
        self.scfg = SepSramBreadthCfg(self.random_seed())
        self.logger.info("SRAM-breadth config: %s", self.scfg.summary())
        await self.bring_up_no_cpu()
        self.sram = SepSramBreadth(self, self.scfg)
        await self._chk_wstrb()
        await self._chk_pattern()
        await self._chk_boundary()
        await self._chk_seq()
        await self._chk_nonvac()
        await self._chk_addr_lines()
        self.logger.info(
            "SRAM datapath breadth PASS: SRAM datapath breadth verified "
            "(wstrb / pattern / boundary / seq / nonvac / addr lines)"
        )

    async def _chk_wstrb(self) -> None:
        cfg = self.scfg
        addr = cfg.base_addr + cfg.wstrb_offset
        for idx, (offset, length) in enumerate(cfg.wstrb_specs):
            mask = ((1 << length) - 1) << offset
            # A length-L write carries exactly L bytes (mask the seed data to L bytes
            # so wdata.to_bytes(L) does not overflow); the same value feeds the golden.
            wr_data = cfg.wstrb_newdata[idx] & ((1 << (8 * length)) - 1)
            # Re-init the whole word, then a single WSTRB-masked write of its bytes.
            await self.sram.write(addr, cfg.wstrb_init, length=8)
            await self.sram.write(addr + offset, wr_data, length=length)
            rb = await self.sram.read(addr, length=8)
            exp = SepSramBreadth.apply_wstrb(cfg.wstrb_init, wr_data, offset, length)
            assert rb == exp, (
                f"CHK-WSTRB mask 0x{mask:02x} (off {offset} len {length}): "
                f"0x{rb:016x} != 0x{exp:016x} (only those lanes should change)"
            )
        self.logger.info(
            "CHK-WSTRB PASS: all %d contiguous WSTRB masks change only their byte "
            "lanes (neighbors preserved, apply_wstrb golden) @0x%08x",
            len(cfg.wstrb_specs),
            addr,
        )

    async def _chk_pattern(self) -> None:
        cfg = self.scfg
        addr = cfg.base_addr + cfg.pattern_offset
        walked = set(WALKING_ONE_PATTERNS) | set(WALKING_ZERO_PATTERNS)
        missing = walked - set(cfg.pattern_values)
        assert not missing, (
            f"CHK-PATTERN FAIL: {len(missing)} walking-one/zero words are not in the pattern set"
        )
        for p in cfg.pattern_values:
            await self.sram.write(addr, p, length=8)
            rb = await self.sram.read(addr, length=8)
            assert rb == p, f"CHK-PATTERN 0x{p:016x} readback 0x{rb:016x}"
        self.logger.info(
            "CHK-PATTERN PASS: %d 64-bit data patterns read back exactly @0x%08x, "
            "including a walking one (%d positions) and a walking zero (%d positions)",
            len(cfg.pattern_values),
            addr,
            len(WALKING_ONE_PATTERNS),
            len(WALKING_ZERO_PATTERNS),
        )

    async def _chk_boundary(self) -> None:
        base, top = self.scfg.boundary_addrs
        bval = 0x0BAD_C0DE_F00D_1234
        tval = 0xCAFE_F00D_1234_5678
        await self.sram.write(base, bval, length=8)
        await self.sram.write(top, tval, length=8)
        rb_b = await self.sram.read(base, length=8)
        rb_t = await self.sram.read(top, length=8)
        assert rb_b == bval, f"CHK-BOUNDARY base 0x{rb_b:016x} != 0x{bval:016x}"
        assert rb_t == tval, f"CHK-BOUNDARY top@0x{top:08x} 0x{rb_t:016x} != 0x{tval:016x}"
        self.logger.info(
            "CHK-BOUNDARY PASS: base 0x%08x and top valid word 0x%08x R/W exact", base, top
        )

    async def _chk_seq(self) -> None:
        cfg = self.scfg
        addr0 = cfg.base_addr + cfg.seq_offset
        words = [
            (cfg.seq_seed + (i << 4) + i) & 0xFFFF_FFFF_FFFF_FFFF for i in range(cfg.seq_words)
        ]
        for i, w in enumerate(words):
            await self.sram.write(addr0 + 8 * i, w, length=8)
        for i, w in enumerate(words):
            rb = await self.sram.read(addr0 + 8 * i, length=8)
            assert rb == w, f"CHK-SEQ word {i} @0x{addr0 + 8 * i:08x} 0x{rb:016x} != 0x{w:016x}"
        self.logger.info(
            "CHK-SEQ PASS: %d consecutive single-beat 64-bit words write->read match @0x%08x",
            cfg.seq_words,
            addr0,
        )

    async def _chk_nonvac(self) -> None:
        cfg = self.scfg
        wr_addr = cfg.base_addr + cfg.nonvac_wr_offset
        rd_addr = cfg.base_addr + cfg.nonvac_rd_offset
        # Both addresses are written, with complementary patterns, and both are read
        # back and value-checked. Comparing a written address against an unwritten one
        # would not catch the stuck read path this names: zero-initialised memory
        # differs from any non-zero pattern by construction, so a datapath returning
        # all-zeros or all-ones would pass. Two written values that must differ from
        # each other cannot be satisfied by a constant.
        other_pattern = (~cfg.nonvac_pattern) & ((1 << 64) - 1)
        await self.sram.write(wr_addr, cfg.nonvac_pattern, length=8)
        await self.sram.write(rd_addr, other_pattern, length=8)
        got_wr = await self.sram.read(wr_addr, length=8)
        got_rd = await self.sram.read(rd_addr, length=8)
        assert got_wr == cfg.nonvac_pattern, (
            f"CHK-NONVAC @0x{wr_addr:08x} read 0x{got_wr:016x} != written "
            f"0x{cfg.nonvac_pattern:016x}"
        )
        assert got_rd == other_pattern, (
            f"CHK-NONVAC @0x{rd_addr:08x} read 0x{got_rd:016x} != written "
            f"0x{other_pattern:016x} -- a stuck read path returns the same value for "
            f"both addresses"
        )
        self.logger.info(
            "CHK-NONVAC PASS: two addresses hold complementary values "
            "(0x%016x / 0x%016x), so the read path is not a stuck constant",
            got_wr,
            got_rd,
        )

    async def _chk_addr_lines(self) -> None:
        cfg = self.scfg
        pairs = list(zip(cfg.addr_line_offsets, cfg.addr_line_values))
        for off, val in pairs:
            await self.sram.write(cfg.base_addr + off, val, length=8)
        bad = []
        for off, val in pairs:
            got = await self.sram.read(cfg.base_addr + off, length=8)
            if got != val:
                bad.append(f"+0x{off:05x} read 0x{got:016x} want 0x{val:016x}")
        assert not bad, "CHK-ADDR-LINES FAIL: " + "; ".join(bad)
        upper = [off for off in cfg.addr_line_offsets if off >= 0x1_0000]
        assert upper, "CHK-ADDR-LINES FAIL: no offset reached the upper 192 KiB"
        self.logger.info(
            "CHK-ADDR-LINES PASS: %d words at +0 / power-of-two offsets / top of "
            "the 0x%x-byte SRAM hold distinct values; upper-SRAM offsets %s",
            len(pairs),
            cfg.size,
            ", ".join(f"+0x{off:05x}" for off in upper),
        )
