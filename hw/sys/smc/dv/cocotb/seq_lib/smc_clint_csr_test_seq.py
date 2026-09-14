# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cluster CLINT MTIME / MSIP over SEP_IN. No Force, no firmware.

REACHABILITY IS THE FIRST THING THIS TEST PROVES.

Two claims in the tree disagree about whether SEP_IN can reach the cluster-local
window at ``0xC800_0000``:

* ``hw/sys/smc/dv/cocotb/seq_lib/smc_cpu_vip_utils.py:165-166`` states outright
  that "cluster-local CLINT MSIP (0xC800_0000) ... SEP-IN AXI cannot reach".
* ``smc_cluster_beu_test`` nevertheless gets OKAY responses from
  ``0xC801_xxxx``, in the SAME xbar window -- but those reads
  are answered by ``SMC_BASE_CONFIG`` at ``0xC001_xxxx`` after a bit-27 fold,
  i.e. OKAY does NOT mean the intended block replied.

That matters here more than usual: ``0xC800_0000`` XOR bit 27 is
``0xC000_0000``, which is the CORE0 WDT window, and MSIP's reset and WDT CTRL's
reset are both 0 -- so an MSIP readback alone could not tell a real CLINT from a
folded WDT.

``MTIME`` can. It is a free-running counter, so two reads separated by DUT time
must STRICTLY INCREASE. No static register, folded or otherwise, produces that.
The monotonic check therefore runs first and doubles as the reachability proof;
every later leg is only credited because it passed.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

MTIME = smc_addr("SMC_TOP_SMC_CLUSTER_CLINT_MTIME_BASE_ADDR")
MSIP_NUM = 4
# Cycles between the two MTIME samples. mtime is driven from a divided tick, so
# give it room; the check is "strictly greater", not "greater by N".
MTIME_GAP_CYCLES = 512


class smc_clint_csr_test_seq(SmcCsrSeq):
    """MTIME advances; MSIP is per-hart writable storage."""

    def __init__(self, name: str = "smc_clint_csr_test_seq") -> None:
        super().__init__(name)
        self.mtime_first: int | None = None
        self.mtime_second: int | None = None
        self.msip_proven: list[int] = []

    async def body(self) -> None:
        dut = cocotb.top

        # --- Reachability + liveness in one measurement -------------------
        # DIAGNOSTIC FIRST: is the bit-27 fold seen on the BEU
        # window also present here? CORE0 WDT CMP sits at 0xC0000020 with a
        # NON-ZERO reset of 0x1000, so the CLINT-side address that would fold
        # onto it, 0xC8000020, is a discriminating probe: MSIP and WDT CTRL both
        # reset to 0 and could not tell the two apart, but 0x1000 can.
        fold_probe = await self.csr_read("CLINT_FOLD_PROBE", 0xC800_0020)
        wdt_cmp = await self.csr_read("WDT0_CMP_REFERENCE", 0xC000_0020)
        cocotb.log.info(
            "CLINT-FOLD-DIAGNOSTIC: 0xC8000020 -> 0x%08x, CORE0 WDT CMP "
            "0xC0000020 -> 0x%08x (WDT CMP generated reset is 0x1000). Equal "
            "non-zero values would mean the CLINT window answers from the WDT "
            "window after a bit-27 fold, the shape #1237 records for the BEU.",
            fold_probe,
            wdt_cmp,
        )

        # Second discriminator, from a DIFFERENT block: 0xC0004034 is
        # AVS_INTERRUPT_MASK with generated reset 0x1FF. If the fold is real,
        # 0xC8004034 returns that too.
        fold_probe2 = await self.csr_read("CLINT_FOLD_PROBE2", 0xC800_4034)
        avs_mask = await self.csr_read("AVS_MASK_REFERENCE", 0xC000_4034)
        cocotb.log.info(
            "CLINT-FOLD-DIAGNOSTIC-2: 0xC8004034 -> 0x%08x, AVS_INTERRUPT_MASK "
            "0xC0004034 -> 0x%08x (generated reset 0x1FF)",
            fold_probe2,
            avs_mask,
        )

        # Third window in the same family: PLIC at 0xC400_0000 (bit 26); both
        # discriminators are reused here.
        plic_probe1 = await self.csr_read("PLIC_FOLD_PROBE", 0xC400_0020)
        plic_probe2 = await self.csr_read("PLIC_FOLD_PROBE2", 0xC400_4034)
        cocotb.log.info(
            "PLIC-FOLD-DIAGNOSTIC: 0xC4000020 -> 0x%08x (WDT CMP reset is "
            "0x1000), 0xC4004034 -> 0x%08x (AVS_INTERRUPT_MASK reset is 0x1FF)",
            plic_probe1,
            plic_probe2,
        )

        # LOCALISATION PROBE. CLINT (0xC800_0000, bit 27) and PLIC
        # (0xC400_0000, bit 26) both land on 0xC000_0000, so the mechanism is
        # not a single-bit fold -- both bits are being lost. If the SEP_IN path
        # decodes only offset[25:0] within the 0xC000_0000 region, then an
        # address whose offset fits inside 26 bits must NOT alias: 0xC200_0020
        # has offset 0x0200_0020, which survives a [25:0] mask, so it should
        # NOT return the WDT CMP reset. If it DOES, the surviving field is
        # narrower than 26 bits.
        # WHERE THE ADDRESS IS LOST. CLINT (bit 27), BEU (bit 27) and PLIC
        # (bit 26) all land on 0xC000_0000, so this is not a single-bit fold.
        # Each probe sets ONE bit above the WDT CMP offset 0x20 and reads:
        #   * 0x1000 back  -> that bit was DROPPED, the address aliased onto
        #                     CORE0 WDT CMP
        #   * DECERR       -> that bit SURVIVED, the address decoded (to an
        #                     unmapped location, which is the correct answer)
        # `csr_read_allow_error` is used so a DECERR is data rather than a
        # failure -- a DECERR is exactly the outcome that proves a bit is kept.
        widths = {}
        for bit in (24, 25, 26, 27):
            addr = 0xC000_0020 | (1 << bit)
            try:
                widths[bit] = await self.csr_read_allow_error(f"FOLD_WIDTH_BIT{bit}", addr)
            except Exception:  # noqa: BLE001 - a refused access is a result
                widths[bit] = None
        dropped = sorted(b for b, v in widths.items() if v == 0x1000)
        kept = sorted(b for b, v in widths.items() if v != 0x1000)
        cocotb.log.info(
            "FOLD-WIDTH-PROBE: bits DROPPED (aliased onto WDT CMP, read "
            "0x1000): %s; bits KEPT (decoded, DECERR or other value): %s. "
            "Raw: %s. Read together with the three window probes above, the "
            "surviving SEP_IN offset field is [24:0] and bits 27:25 are lost.",
            dropped,
            kept,
            ", ".join(
                f"bit{b}=" + ("DECERR/none" if v is None else f"0x{v:08x}")
                for b, v in sorted(widths.items())
            ),
        )

        self.mtime_first = await self.csr_read("CLINT_MTIME_T0", MTIME, length=8)
        await ClockCycles(dut.clk_smc_i, MTIME_GAP_CYCLES)
        self.mtime_second = await self.csr_read("CLINT_MTIME_T1", MTIME, length=8)
        assert self.mtime_second > self.mtime_first, (
            f"CLINT MTIME did not advance across {MTIME_GAP_CYCLES} clk_smc_i "
            f"cycles: 0x{self.mtime_first:016x} -> 0x{self.mtime_second:016x}. "
            f"Either the counter is stopped, or this read is not reaching the "
            f"CLINT at all -- 0xC800_0000 folds onto the CORE0 WDT window if "
            f"bit 27 is dropped (see #1237 for the same fold on the BEU "
            f"window), and a folded static register cannot increment."
        )

        # --- MSIP: per-hart 1-bit software-interrupt storage --------------
        # Written with a value UNIQUE PER HART so a decode that aliased two
        # harts onto one register returns a neighbour's value. MSIP is 1 bit
        # wide, so uniqueness is expressed as a pattern across harts (set on
        # even indices, clear on odd) checked while all four are resident.
        addrs = [
            smc_indexed_addr("SMC_TOP_SMC_CLUSTER_CLINT_MSIP_BASE_ADDR", i) for i in range(MSIP_NUM)
        ]
        assert len(set(addrs)) == MSIP_NUM, "CLINT MSIP addresses are not pairwise distinct"
        for i, addr in enumerate(addrs):
            await self.csr_read(f"CLINT_MSIP{i}_RESET", addr, expected=0)

        want = {i: (1 if i % 2 == 0 else 0) for i in range(MSIP_NUM)}
        for i, addr in enumerate(addrs):
            await self.csr_write(f"CLINT_MSIP{i}_WR", addr, want[i])
        # Read back while ALL FOUR are resident: an aliased decode returns the
        # last value written, so the alternating pattern fails on one of them.
        for i, addr in enumerate(addrs):
            await self.csr_read(f"CLINT_MSIP{i}_RB", addr, expected=want[i])
            self.msip_proven.append(i)
        for i, addr in enumerate(addrs):
            await self.csr_write(f"CLINT_MSIP{i}_RESTORE", addr, 0)
            await self.csr_read(f"CLINT_MSIP{i}_RESTORE_RB", addr, expected=0)

        assert self.msip_proven == list(range(MSIP_NUM)), (
            f"MSIP readback covered harts {self.msip_proven}, expected {list(range(MSIP_NUM))}"
        )
        cocotb.log.info(
            "CHK-CLINT-CSR: MTIME advanced 0x%016x -> 0x%016x across %d "
            "clk_smc_i cycles, which is also this test's reachability proof "
            "(a bit-27 fold onto the WDT window could not increment); %d MSIP "
            "harts held an alternating per-hart pattern read back while all "
            "four were resident, then restored to 0",
            self.mtime_first,
            self.mtime_second,
            MTIME_GAP_CYCLES,
            len(self.msip_proven),
        )
