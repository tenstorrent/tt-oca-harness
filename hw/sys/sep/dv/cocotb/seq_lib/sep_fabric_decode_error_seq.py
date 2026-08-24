# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Fabric decode-error stimulus for sep_fabric_decode_error_response_test.

Drives the CPU-LSU AXI master (no_cpu splice, no inbound filter) at:
  * a KNOWN-MAPPED local CSR -> expects OKAY + the exact reset value (proves the
    bus is live and the decode reaches a real aperture), and
  * UNMAPPED local addresses -> expects the SEP local xbar to route the access to
    its error slave and return exactly DECERR (the negative half).

The mapped read is value-checked by the scoreboard (``item.expected``). The
unmapped probe sets ``item.expect_error`` so the scoreboard tolerates the
intentional non-OKAY; the test asserts the exact ``resp_code == DECERR`` and the
s_axi monitor is armed (``arm_expected_decerr``) to tally rather than fail on the
intentional DECERR (a DECERR on the CPU-LSU bus is otherwise a real decode bug).

reference provenance: sep_cpu_lsu_negative_matrix_test,
sep_cpu_ifu_invalid_target_test, and
sep_fabric_xbar_error_closure_test. the reference suite accepts any non-OKAY
(including a tolerated timeout); the OSS port is COVERED_STRONGER -- it asserts
the EXACT spec response (DECERR, per fabric/port_table.adoc "Tie to DECERR if
unused") with allow_timeout=False so a wedge FAILs.

Register-map constants live here (co-located with the stimulus, never copied
into the test).
"""

from __future__ import annotations

from pyuvm import uvm_sequence

from env.sep_axi_agent import SepAxiItem, SepAxiOp
from sep_reg_meta import SEP_CPU_CTRL

# sep_cpu_ctrl SEP_NMI_VEC on the CPU-local map: a known-good decode target with
# a non-zero generated reset (0xC000_0100) and no read side effects. CLOCK_GATE_CTRL
# resets to 0, so a value-check there is zero-vs-zero and would also pass a tied-off
# decode. Address and expected value are derived from the generated SystemRDL export.
MAPPED_CSR_ADDR = SEP_CPU_CTRL.addr("SEP_NMI_VEC")
MAPPED_CSR_EXP = SEP_CPU_CTRL.reset32("SEP_NMI_VEC")

# The addresses below stay LITERAL by definition and must NOT be converted to sym()
# lookups: having no decode target is the whole point of the test, so no generated
# symbol can ever name them.
#
# Unmapped LOCAL addresses (high nibble 0x10xx => SEP-local space, not routed out
# to SMN/SMC alias) that the SEP local xbar decodes to its error slave:
#   * 0x10FF_0000 -- reference suite INVALID_TARGET_ADDR (reserved invalid target).
#   * 0x10FF_1000 -- reference suite bad_addr (reserved region).
#   * reserved gap 0x1080_3008..0x108F_FFFF (memory_map.adoc) -- e.g. 0x1087_0000.
# The reserved gap is the randomization window (see SepFabricDecErrCfg).
RESERVED_GAP_LO = 0x1080_300C       # 4-aligned start of the reserved local gap
RESERVED_GAP_HI = 0x108F_FFFC       # 4-aligned end
REFERENCE_INVALID_TARGETS = (0x10FF_0000, 0x10FF_1000)

# axi_pkg response codes.
RESP_OKAY = 0
RESP_DECERR = 3


class SepFabricDecErrCfg:
    """Seeded selection of unmapped local addresses for the decode-error probes.

    Single source of truth for which addresses the test probes. Anchors on the two
    reference suite-proven invalid targets (0x10FF_0000/0x10FF_1000) and adds N randomized
    4-aligned addresses from the reserved local gap (0x1080_3008..0x108F_FFFF), which
    all decode to the SEP local xbar error slave (DECERR). One is chosen for the WRITE
    (B-channel) probe. The mapped-CSR anchor stays fixed (known reset value). The
    contract (unmapped->DECERR, mapped->OKAY) is identical for every address; the
    randomization just broadens which decode points are exercised per seed. Seed +
    resolved addresses logged; regression mode can sweep this via TOML ``reseed = N``.
    """

    def __init__(self, seed: int, *, n_random: int = 2) -> None:
        import random
        self.seed = seed
        rng = random.Random(seed)
        rand: list[int] = []
        while len(rand) < n_random:
            a = rng.randint(RESERVED_GAP_LO, RESERVED_GAP_HI) & ~0x3
            if a not in rand:
                rand.append(a)
        # reference suite-proven invalid targets + randomized reserved-gap addresses.
        self.unmapped_reads = list(REFERENCE_INVALID_TARGETS) + rand
        self.unmapped_write = rng.choice(self.unmapped_reads)

    def summary(self) -> str:
        reads = " ".join(f"0x{a:08x}" for a in self.unmapped_reads)
        return f"seed={self.seed} unmapped_reads=[{reads}] write=0x{self.unmapped_write:08x}"


class SepFabricMappedReadSeq(uvm_sequence):
    """Read the known-mapped CSR; the scoreboard value-checks (OKAY + exact value)."""

    def __init__(self, *, name: str = "fabric_mapped_read") -> None:
        super().__init__(name)
        self.rdata: int = 0
        self.resp_code: int = -1

    async def body(self) -> None:
        item = SepAxiItem("rd_mapped")
        item.op = SepAxiOp.READ
        item.addr = MAPPED_CSR_ADDR
        item.length = 4
        item.expected = MAPPED_CSR_EXP
        await self.start_item(item)
        await self.finish_item(item)
        self.rdata = item.rdata & 0xFFFF_FFFF
        self.resp_code = item.resp_code


class SepFabricUnmappedProbeSeq(uvm_sequence):
    """Read one UNMAPPED local address; expose resp_code/timed_out for the test.

    ``expect_error`` makes the scoreboard tolerate the intentional non-OKAY (the
    test asserts the exact DECERR). ``allow_timeout`` stays False: a non-completing
    access is a wedge and must FAIL, not be mistaken for "blocked".
    """

    def __init__(self, addr: int, *, name: str = "fabric_unmapped_probe") -> None:
        super().__init__(name)
        self.addr = addr
        self.resp_ok: bool = False
        self.resp_code: int = -1
        self.timed_out: bool = False

    async def body(self) -> None:
        item = SepAxiItem(f"rd_unmapped_0x{self.addr:08x}")
        item.op = SepAxiOp.READ
        item.addr = self.addr
        item.length = 4
        item.expect_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.resp_ok = item.resp_ok
        self.resp_code = item.resp_code
        self.timed_out = item.timed_out


class SepFabricUnmappedWriteProbeSeq(uvm_sequence):
    """Write one UNMAPPED local address; expose the B-channel resp_code.

    The write decode + B-response path is distinct from the read AR/R path, so this
    proves the error slave returns DECERR on writes too. ``expect_error`` makes the
    scoreboard tolerate the intentional non-OKAY; ``allow_timeout`` stays False so a
    non-completing write FAILs as a wedge.
    """

    def __init__(self, addr: int, *, name: str = "fabric_unmapped_write_probe") -> None:
        super().__init__(name)
        self.addr = addr
        self.resp_ok: bool = False
        self.resp_code: int = -1
        self.timed_out: bool = False

    async def body(self) -> None:
        item = SepAxiItem(f"wr_unmapped_0x{self.addr:08x}")
        item.op = SepAxiOp.WRITE
        item.addr = self.addr
        item.length = 4
        item.wdata = 0xDEAD_BEEF
        item.expect_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.resp_ok = item.resp_ok
        self.resp_code = item.resp_code
        self.timed_out = item.timed_out
