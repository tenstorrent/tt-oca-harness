# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_smc_efuse_shadow_sense_reset_test. No Force.

``smc_shadow_regs_o`` carries the SMC eFuse shadow map at the wrapper boundary.
The run mode leaves ``+skip_fuse_sense`` unset, so the shadow is filled by the
SMC eFuse controller's own sense of the image the bank model holds, and the
sense is the claim rather than a step on the way to one.

The expected value comes from two DV-owned sources and no RTL: the image file
``+smc_efuse_hex`` names, which this leaf owns under ``dv/assets``, and the
generated PeakRDL header ``smc_addr.h``, which gives the map's size and the byte
offset of every register in it. The fuse word is 4 bytes and ``smc_efuse_map``
tiles its whole 1024-byte map with no holes, so fuse word ``i`` is map bytes
``4i..4i+3`` and shadow bits ``32i+31..32i``. Every field of every register in
``smc_efuse_map.rdl`` resets to ``0x0``, so the map's reset value is zero across
its full width.

The image programs every fuse bit, which makes the two samples complements of
each other: every bit of the port is observed at 0 before the sense and at 1
after it, then back at 0 under cold reset. A uniform image cannot tell one word
from another, so the word-for-word claim here is that each register's slice of
the port carries its own bytes of the image at the port's full width, not that
the words could not be permuted among themselves; ``smu_dtp_otp_smc_map_rw_test``
and ``smu_otp_vs_fabric_map_race_test`` place distinct data at named offsets.
"""

from __future__ import annotations

from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from seq_lib.smu_addr_map import smc_addr, smc_indexed_addr
from seq_lib.smu_fuse_gate_helpers import wait_fuse_sense_done

SENSE = "CHK-SMU-EFUSE-SHADOW-SENSE"
RESET = "CHK-SMU-EFUSE-SHADOW-RESET"
TOGGLE = "CHK-SMU-EFUSE-SHADOW-TOGGLE"

FUSE_WORD_BYTES = 4
# Every field in smc_efuse_map.rdl carries "= 0x0".
SHADOW_RESET_VALUE = 0
SETTLE_CYCLES = 16
HOLD_CYCLES = 64
# Bound on the cold reset reaching the SMC eFuse controller. The SMC primary
# reset runs a deglitch and an extender on clk_ref before it asserts.
RESET_REACH_BOUND_CYCLES = 5000


class smu_smc_efuse_shadow_sense_reset_seq:
    """The SMC eFuse shadow map after a real sense, and after a cold reset."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.log = test.logger
        self.sb = test.env.scoreboard
        self.map_bytes = smc_addr("SMC_TOP_SMC_EFUSE_MAP_SIZE")
        self.map_words = self.map_bytes // FUSE_WORD_BYTES
        self.map_bits = self.map_bytes * 8

    def _sample(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on this TB top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val)

    def _image_words(self) -> tuple[str, list[int]]:
        """The fuse words ``+smc_efuse_hex`` holds, in the order $readmemh stores them."""
        named = cocotb.plusargs.get("smc_efuse_hex")
        if named is None:
            raise AssertionError("+smc_efuse_hex is required: it is the image the sense reads")
        path = Path(str(named))
        words: dict[int, int] = {}
        idx = 0
        for raw in path.read_text(encoding="ascii").splitlines():
            line = raw.split("//", 1)[0]
            for tok in line.split():
                if tok.startswith("@"):
                    idx = int(tok[1:], 16)
                    continue
                words[idx] = int(tok, 16) & 0xFFFF_FFFF
                idx += 1
        # The bank model zero-fills its array before $readmemh, so a word the
        # image does not reach is sensed as zero.
        return str(path), [words.get(i, 0) for i in range(self.map_words)]

    def _regions(self) -> list[tuple[str, int, int]]:
        """(name, byte offset, byte length) per register of the map, from smc_addr.h."""
        base = smc_addr("SMC_TOP_SMC_EFUSE_MAP_BASE_ADDR")
        entries = [
            ("LOCKS", smc_addr("SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR")),
            (
                "JTAG_PUBLIC_IDENTITY",
                smc_addr("SMC_TOP_SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY_BASE_ADDR"),
            ),
            ("SMC_CONFIG", smc_addr("SMC_TOP_SMC_EFUSE_MAP_SMC_CONFIG_BASE_ADDR")),
            (
                "OCCP_TRANSPORT_TIMEOUT",
                smc_addr("SMC_TOP_SMC_EFUSE_MAP_OCCP_TRANSPORT_TIMEOUT_BASE_ADDR"),
            ),
        ]
        for i in range(smc_addr("SMC_TOP_SMC_EFUSE_MAP_I2C_I3C_ID_NUM")):
            entries.append(
                (
                    f"I2C_I3C_ID[{i}]",
                    smc_indexed_addr("SMC_TOP_SMC_EFUSE_MAP_I2C_I3C_ID_BASE_ADDR", i),
                )
            )
        for k in range(smc_addr("SMC_TOP_SMC_EFUSE_MAP_SPARE_NUM")):
            entries.append(
                (f"SPARE[{k}]", smc_indexed_addr("SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR", k))
            )
        entries.sort(key=lambda row: row[1])
        offsets = [addr - base for _, addr in entries]
        bounds = offsets[1:] + [self.map_bytes]
        regions = [(name, off, end - off) for (name, _), off, end in zip(entries, offsets, bounds)]
        covered = 0
        for name, off, length in regions:
            if off != covered or length <= 0 or length % FUSE_WORD_BYTES:
                raise AssertionError(
                    f"smc_efuse_map registers do not tile the map: {name} at 0x{off:x} "
                    f"length {length} after 0x{covered:x} bytes"
                )
            covered += length
        if covered != self.map_bytes:
            raise AssertionError(
                f"smc_efuse_map registers cover {covered} of {self.map_bytes} bytes"
            )
        return regions

    def _slice(self, value: int, byte_off: int, byte_len: int) -> int:
        return (value >> (byte_off * 8)) & ((1 << (byte_len * 8)) - 1)

    async def _hold_shadow(self, expected: int, *, what: str) -> None:
        """Fail unless ``smc_shadow_regs`` reads ``expected`` on each of HOLD_CYCLES edges."""
        for cycle in range(HOLD_CYCLES):
            await RisingEdge(self.dut.clk_smu_i)
            got = self._sample("smc_shadow_regs")
            if got != expected:
                raise AssertionError(
                    f"smc_shadow_regs left its {what} value at cycle {cycle} of {HOLD_CYCLES}: "
                    f"{got ^ expected:x} changed"
                )

    async def _wait_sense_done_low(self) -> int:
        """Cycles until ``smc_fuse_sense_done_o`` reads 0, having read 1 when the wait began."""
        if self._sample("smc_fuse_sense_done_o") != 1:
            raise AssertionError("smc_fuse_sense_done_o already low before the cold reset")
        for cycle in range(1, RESET_REACH_BOUND_CYCLES + 1):
            await RisingEdge(self.dut.clk_smu_i)
            if self._sample("smc_fuse_sense_done_o") == 0:
                return cycle
        raise AssertionError(
            "timeout waiting for smc_fuse_sense_done_o==0 under cold reset: "
            f"bound={RESET_REACH_BOUND_CYCLES} clk_smu"
        )

    async def run(self) -> None:
        dut = self.dut
        sb = self.sb
        await self.cfg.reset_done.wait()

        sb.expect_true(
            "this run mode leaves +skip_fuse_sense unset, so the sense is the DUT's",
            "skip_fuse_sense" not in cocotb.plusargs,
            evidence=SENSE,
        )
        sb.expect_eq(
            "smc_shadow_regs is as wide as the eFuse map SMC_TOP_SMC_EFUSE_MAP_SIZE declares",
            len(dut.smc_shadow_regs),
            self.map_bits,
            evidence=SENSE,
        )

        path, words = self._image_words()
        expected = 0
        for i, word in enumerate(words):
            expected |= word << (i * 32)
        programmed = bin(expected).count("1")
        self.log.info(
            "eFuse image %s: %d word(s) of %d, %d of %d bit(s) programmed",
            path,
            len(words),
            self.map_words,
            programmed,
            self.map_bits,
        )
        sb.expect_eq(
            f"the image programs every one of the {self.map_bits} shadow bits, so both "
            "edges are observable on all of them",
            programmed,
            self.map_bits,
            evidence=TOGGLE,
        )

        regions = self._regions()
        pre_sense = self._sample("smc_shadow_regs")
        sb.expect_eq(
            "smc_shadow_regs reads the reset value of smc_efuse_map before the sense completes",
            pre_sense,
            SHADOW_RESET_VALUE,
            evidence=RESET,
        )

        cycles = await wait_fuse_sense_done(dut, self.log, phase="cold boot")
        await ClockCycles(dut.clk_smu_i, SETTLE_CYCLES)
        sensed = self._sample("smc_shadow_regs")
        self.log.info(
            "smc_fuse_sense_done_o rose after %d clk_smu; smc_shadow_regs %d bit(s) set",
            cycles,
            bin(sensed).count("1"),
        )

        for name, off, length in regions:
            sb.expect_eq(
                f"{name} carries eFuse map bytes 0x{off:x}..0x{off + length - 1:x} of the "
                "sensed image",
                f"{self._slice(sensed, off, length):#x}",
                f"{self._slice(expected, off, length):#x}",
                evidence=SENSE,
            )
        sb.expect_eq(
            f"no bit of the {self.map_bits}-bit smc_shadow_regs differs from the sensed image",
            bin(sensed ^ expected).count("1"),
            0,
            evidence=SENSE,
        )
        rose = bin(sensed & ~pre_sense).count("1")
        sb.expect_eq(
            f"the sense drives all {self.map_bits} shadow bits 0 -> 1",
            rose,
            programmed,
            evidence=TOGGLE,
        )
        await self._hold_shadow(sensed, what="sensed")
        sb.expect_eq(
            f"smc_shadow_regs holds the sensed image for {HOLD_CYCLES} clk_smu after the sense",
            bin(self._sample("smc_shadow_regs") ^ expected).count("1"),
            0,
            evidence=SENSE,
        )

        dut.rst_cold_ni.value = 0
        dut.jtag_trst.value = 0
        reached = await self._wait_sense_done_low()
        await ClockCycles(dut.clk_smu_i, SETTLE_CYCLES)
        in_reset = self._sample("smc_shadow_regs")
        self.log.info(
            "rst_cold_ni asserted: smc_fuse_sense_done_o fell after %d clk_smu; "
            "smc_shadow_regs %d bit(s) set",
            reached,
            bin(in_reset).count("1"),
        )
        sb.expect_eq(
            "smc_shadow_regs reads the reset value of smc_efuse_map while rst_cold_ni is held",
            in_reset,
            SHADOW_RESET_VALUE,
            evidence=RESET,
        )
        fell = bin(sensed & ~in_reset).count("1")
        sb.expect_eq(
            f"the cold reset drives all {self.map_bits} shadow bits 1 -> 0",
            fell,
            programmed,
            evidence=TOGGLE,
        )
        await self._hold_shadow(SHADOW_RESET_VALUE, what="reset")
        sb.expect_eq(
            f"smc_shadow_regs stays at its reset value for {HOLD_CYCLES} clk_smu with "
            "rst_cold_ni still held",
            self._sample("smc_shadow_regs"),
            SHADOW_RESET_VALUE,
            evidence=RESET,
        )
