# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Compact register-boundary depth sweep over real SEP_IN AXI."""

from __future__ import annotations

import os
import random

import cocotb
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_addr
from .smc_csr_field_catalog import catalog_entry, misc_wrap_reset
from .smc_csr_seq_utils import SmcCsrSeq

SCRATCH_COLD_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR")
SCRATCH_COLD_7 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR") + 0x1C
SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")
SCRATCH_COLD_WARM_7 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR") + 0x1C
CHIP_CONFIG_BASE = smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_BASE_ADDR")
# The last register of the CHIP_CONFIG window, derived from the window size the
# generated map exports and required to be the LC_STATE register it names.
CHIP_CONFIG_LAST = CHIP_CONFIG_BASE + smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_SIZE") - 4
assert CHIP_CONFIG_LAST == smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_LC_STATE_BASE_ADDR"), (
    f"CHIP_CONFIG window end 0x{CHIP_CONFIG_LAST:08x} is not the LC_STATE register"
)
for _win in ("SCRATCH_COLD", "SCRATCH_COLD_WARM"):
    assert smc_addr(f"SMC_TOP_SMC_MISC_WRAP_{_win}_SIZE") == 0x20, (
        f"{_win} window is not eight words"
    )

BOUNDARY_READS = [
    ("SCRATCH_COLD_0", SCRATCH_COLD_0, 0),
    ("SCRATCH_COLD_7", SCRATCH_COLD_7, 0),
    ("SCRATCH_COLD_WARM_0", SCRATCH_COLD_WARM_0, 0),
    ("SCRATCH_COLD_WARM_7", SCRATCH_COLD_WARM_7, 0),
    (
        "CHIP_CONFIG_VERSION_LO",
        CHIP_CONFIG_BASE,
        misc_wrap_reset("CHIP_CONFIG__VERSION_LO__VERSION_LO_reset"),
    ),
    ("CHIP_CONFIG_VERSION_HI", CHIP_CONFIG_BASE + 0x4, 0),
]
# CHIP_CONFIG.LC_STATE is `sw = r; hw = w`, the lifecycle value the SEP drives,
# so the last register of that window is read for an OKAY response and its
# value is reported, not compared.
BOUNDARY_STATUS_READS = [
    ("CHIP_CONFIG_LC_STATE", CHIP_CONFIG_LAST),
]

BOUNDARY_WRITES = [
    ("SCRATCH_COLD_7", SCRATCH_COLD_7, 0x1357_2468),
    ("SCRATCH_COLD_WARM_7", SCRATCH_COLD_WARM_7, 0x2468_1357),
]

# One probe read per window at a seed-drawn offset and AxSIZE. A 4-byte probe
# is held to OKAY and, at a word with an RDL value, to that value; the other
# sizes are reported, because memmap.adoc states the answer to a 32-bit access
# only.
PROBE_WINDOWS = (
    ("SCRATCH_COLD", SCRATCH_COLD_0, smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SIZE")),
    (
        "SCRATCH_COLD_WARM",
        SCRATCH_COLD_WARM_0,
        smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SIZE"),
    ),
    ("CHIP_CONFIG", CHIP_CONFIG_BASE, smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_SIZE")),
)
PROBE_SIZES = (1, 2, 4, 8)
AXI_RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}


class smc_register_boundary_depth_test_seq(SmcCsrSeq):
    """Exercise safe first/last registers from representative CSR windows."""

    def __init__(self, name: str = "smc_register_boundary_depth_test_seq") -> None:
        super().__init__(name)
        self.seed = int(os.environ.get("RANDOM_SEED", "1"), 0)
        self.compared_window = ""

    def _draw_probes(self) -> list[tuple[str, int, int, int]]:
        rng = random.Random(self.seed)
        # One drawn window takes a 4-byte probe, so every run carries a compared probe (OKAY,
        # and the RDL word at a first or last word); the other two draw any AxSIZE.
        compared = rng.randrange(len(PROBE_WINDOWS))
        probes = []
        for index, (name, base, size) in enumerate(PROBE_WINDOWS):
            length = 4 if index == compared else rng.choice(PROBE_SIZES)
            offset = rng.randrange(0, size - length + 1, length)
            probes.append((name, base + offset, offset, length))
        self.compared_window = PROBE_WINDOWS[compared][0]
        assert any(length == 4 for _n, _a, _o, length in probes), f"no 4-byte probe in {probes}"
        cocotb.log.info(
            "RAND-SEED: %d; RAND-DRAW: window probes %s (the 4-byte probe pinned to %s)",
            self.seed,
            ", ".join(f"{n}+0x{o:x} len={ln}" for n, _a, o, ln in probes),
            self.compared_window,
        )
        return probes

    async def _probe(self, name: str, addr: int, length: int, expected: int | None) -> str:
        """One drawn probe read; the compare class follows the AxSIZE."""
        if length == 4:
            data = await self.csr_read(f"{name}_PROBE", addr, expected=expected, length=4)
            kind = "rdl" if expected is not None else "okay"
            return f"{name}@0x{addr:08x} len=4 OKAY 0x{data:08x} cmp={kind}"
        item = SmcSysAxiItem(f"rd_{name}_PROBE")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = length
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert not item.timed_out and item.resp_code is not None, f"{name} probe: no response"
        resp = AXI_RESP_NAME.get(item.resp_code, str(item.resp_code))
        return f"{name}@0x{addr:08x} len={length} {resp} 0x{item.rdata:x} cmp=printed"

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        probes = self._draw_probes()

        for name, addr, _expected in BOUNDARY_READS:
            catalog_entry(name, addr, writable=name.startswith("SCRATCH_"))
        for name, addr, _pattern in BOUNDARY_WRITES:
            catalog_entry(name, addr, writable=True)

        await self.csr_read_many(BOUNDARY_READS)
        status_values = []
        for name, addr in BOUNDARY_STATUS_READS:
            status_values.append((name, addr, await self.csr_read(name, addr)))

        rdl_value = {addr: expected for _name, addr, expected in BOUNDARY_READS}
        probe_lines = [
            await self._probe(name, addr, length, rdl_value.get(addr) if length == 4 else None)
            for name, addr, _offset, length in probes
        ]

        original = []
        for name, addr, pattern in BOUNDARY_WRITES:
            old_value = await self.csr_read(f"{name}_SAVE", addr)
            original.append((name, addr, old_value))
            await self.csr_write_readback(name, addr, pattern)

        for name, addr, value in reversed(original):
            await self.csr_restore(name, addr, value)

        expected_accesses = (
            len(BOUNDARY_READS)
            + len(BOUNDARY_STATUS_READS)
            + len(probes)
            + (len(BOUNDARY_WRITES) * 5)
        )
        self.assert_all_reachable(expected_accesses, "REGISTER_BOUNDARY")
        cocotb.log.info(
            "CHK-CSR-BOUNDARY-SWEEP: %d first/last-of-window read(s) over SEP_IN AXI "
            "each compared against its expected value (%s); %d hardware-status "
            "last-of-window read(s) answered OKAY and reported (%s); %d last-of-window "
            "write(s) read back the pattern and then the saved value (%s); all %d "
            "access(es) checked by the scoreboard; drawn=seed %d probes [%s], the %s probe "
            "being the run's 4-byte compared probe",
            len(BOUNDARY_READS),
            "; ".join(f"{name}@0x{addr:08x}==0x{exp:x}" for name, addr, exp in BOUNDARY_READS),
            len(BOUNDARY_STATUS_READS),
            "; ".join(f"{name}@0x{addr:08x}=0x{val:x}" for name, addr, val in status_values),
            len(BOUNDARY_WRITES),
            "; ".join(
                f"{name}@0x{addr:08x} pattern 0x{pattern:08x} restored 0x{old:08x}"
                for (name, addr, pattern), (_, _, old) in zip(BOUNDARY_WRITES, original)
            ),
            expected_accesses,
            self.seed,
            "; ".join(probe_lines),
            self.compared_window,
        )
