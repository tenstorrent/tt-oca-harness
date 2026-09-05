# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""RAS-bank / NDM-reset / DFX-debug diagnostic representative precheck.

Scope note: no ECC and no DBS register is addressed here --
neither surface is exposed at the SMC CSR boundary (``grep -ic ecc`` over the
authoritative map ``hw/sys/smc/regs/gen/c/smc_addr.h`` returns 0, and there is
no ``DBS_``/``_DBS`` symbol). The testcase name is historical; what this
sequence actually reads is the RAS bank type/instance ID pair, the NDM-reset
registers, and the DFX debug control/bus-mux registers.
"""

from __future__ import annotations

import re
from pathlib import Path

import cocotb

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_diagnostic_vip_utils import prove_axil_any_master_activity

_REPO = Path(__file__).resolve().parents[6]
_SMC_CONFIG_PKG_SV = _REPO / "hw" / "sys" / "smc" / "rtl" / "smc_config_pkg.sv"
_NDM_RESET_RDL = _REPO / "hw" / "sys" / "smc" / "regs" / "blocks" / "ndm_reset" / "ndm_reset.rdl"
_CPU_CLUSTER_COUNT_RE = re.compile(
    r"^\s*localparam\s+logic\s*\[\s*\d+\s*:\s*\d+\s*\]\s+CPU_CLUSTER_COUNT\s*=\s*"
    r"(\d+)\s*;",
    re.M,
)
_CLUSTER_COUNT_FIELD_RE = re.compile(r"\}\s*ndmreset_cluster_count\s*\[\s*(\d+)\s*:\s*(\d+)\s*\]")


def _cpu_cluster_count() -> int:
    """``smc_config_pkg::CPU_CLUSTER_COUNT`` by symbol from its declaration.

    PROVENANCE AND SCOPE LIMIT. This is the SMC integration's
    single declaration of the cluster count, and the RTL tie-off that feeds the
    CSR consumes the same symbol (``smc_misc_wrap.sv``:
    ``ndm_hwif_in.NDMRESET_CLUSTER_COUNT.ndmreset_cluster_count.next =
    smc_config_pkg::CPU_CLUSTER_COUNT``). ``smc_config_pkg.sv`` is RTL, and
    quality-policy §4 excludes RTL as a SPEC source, so the equality below is
    deliberately NOT presented as a register value check. What it proves is:

    * **parameter-to-CSR propagation** -- the declared integration parameter
      really does reach the software-visible register through the hwif path and
      survive the RDL field width; and
    * with the ``sw=r`` leg in ``body()``, the **RDL register contract**
      (``ndm_reset.rdl:33-38`` declares ``sw = r; hw = w;``), which no
      observed-value golden could assert.

    NOT proven: that the number itself is the specified cluster count. A
    non-RTL, non-generated, non-VPLAN authority for it does not exist in this
    repo. The closest §4-authoritative documents bound the CPU *core* count to a
    range rather than pinning a cluster count -- ``hw/sys/smc/doc/cpu.adoc:11``
    ("supports 1 to 4 processor cores"), ``:16`` ("Up to 4 Rocket CPU cores")
    and ``:32`` ("|Cores |1-4") -- and ``ndm_reset.rdl:17-19`` only states the
    register "Supports up to 32 CPU Clusters". If the integration tied the wrong
    count, this leg would not catch it; that residual is declared, not hidden.
    """
    text = _SMC_CONFIG_PKG_SV.read_text(encoding="utf-8")
    match = _CPU_CLUSTER_COUNT_RE.search(text)
    if not match:
        raise RuntimeError(f"CPU_CLUSTER_COUNT localparam not found in {_SMC_CONFIG_PKG_SV}")
    return int(match.group(1), 0)


def _cluster_count_field_width() -> int:
    """Width of ``NDMRESET_CLUSTER_COUNT.ndmreset_cluster_count`` from the RDL."""
    text = _NDM_RESET_RDL.read_text(encoding="utf-8")
    match = _CLUSTER_COUNT_FIELD_RE.search(text)
    if not match:
        raise RuntimeError(f"ndmreset_cluster_count field range not found in {_NDM_RESET_RDL}")
    return int(match.group(1)) - int(match.group(2)) + 1


# The DECLARED cluster-count parameter (not a spec-conformance golden -- see
# _cpu_cluster_count), framed by the field width the RDL declares. Reserved bits
# [31:width] read 0.
_CLUSTER_COUNT_WIDTH = _cluster_count_field_width()
_CLUSTER_COUNT_MASK = (1 << _CLUSTER_COUNT_WIDTH) - 1
NDMRESET_CLUSTER_COUNT_DECLARED = _cpu_cluster_count()
assert 0 < NDMRESET_CLUSTER_COUNT_DECLARED <= _CLUSTER_COUNT_MASK, (
    f"smc_config_pkg::CPU_CLUSTER_COUNT={NDMRESET_CLUSTER_COUNT_DECLARED} does "
    f"not fit the {_CLUSTER_COUNT_WIDTH}-bit ndmreset_cluster_count field "
    f"declared in {_NDM_RESET_RDL}"
)

NDMRESET_CLUSTER_COUNT_ADDR = smc_addr(
    "SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_CLUSTER_COUNT_BASE_ADDR"
)
# Software-write pattern for the sw=r leg: every field bit inverted, so a
# register that (wrongly) accepted the write cannot coincidentally read back the
# expected count.
NDMRESET_CLUSTER_COUNT_WR_PATTERN = NDMRESET_CLUSTER_COUNT_DECLARED ^ _CLUSTER_COUNT_MASK

# ``DFX_DEBUG_BUS_MUX`` is a 64-bit register -- ``dfx_ctrl_status.rdl:116-118``
# declares ``reg DEBUG_BUS_MUX { regwidth = 0x40; }`` with fields running to
# ``Muxselseg7[63:58]``. It is therefore read 8 bytes wide so the whole declared
# reset is compared; a 4-byte read left ``Muxselseg2[33:28]``..``Muxselseg7``
# unsampled while the token read as a whole-register default check.
# Every field in that register resets to 0x0 in the RDL.
_DEBUG_BUS_MUX_BYTES = 8

# Value-compared diagnostic reads, identical on Verilator and VCS. Every
# expectation here traces to a cited RDL declaration:
#   * RAS_BANK_INFO (chip_config.rdl) / NDMRESET_PROCESS (ndm_reset.rdl):
#     RDL reset 0x0 -> spec-anchored.
#   * DFX DEBUG_CTRL / DEBUG_BUS_MUX: PeakRDL symbols at 0xC000_B808/B810,
#     RDL reset 0x0 (do not use the old false-identity window 0xC001_0208/0210).
#     DEBUG_CTRL is regwidth 32; DEBUG_BUS_MUX is regwidth 64 (see above).
# NDMRESET_CLUSTER_COUNT is deliberately NOT in this table: its number is not
# RDL/spec-traceable (see _cpu_cluster_count) and it is handled by its own
# propagation + sw=r legs in body(), which say exactly what they prove.
DIAGNOSTIC_READS = [
    (
        "CHIP_CONFIG_RAS_BANK_INFO",
        smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_RAS_BANK_INFO_BASE_ADDR"),
        0x0,
        4,
    ),
    (
        "NDMRESET_PROCESS",
        smc_addr("SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_PROCESS_BASE_ADDR"),
        0x0,
        4,
    ),
    ("DFX_DEBUG_CTRL", smc_addr("SMC_TOP_DFX_CTRL_DEBUG_CTRL_BASE_ADDR"), 0x0, 4),
    (
        "DFX_DEBUG_BUS_MUX",
        smc_addr("SMC_TOP_DFX_CTRL_DEBUG_BUS_MUX_BASE_ADDR"),
        0x0,
        _DEBUG_BUS_MUX_BYTES,
    ),
]


class smc_ecc_dfd_dbs_sanity_test_seq(SmcCsrSeq):
    """Use safe RAS/debug CSRs as the diagnostic representative."""

    def __init__(self, name: str = "smc_ecc_dfd_dbs_sanity_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        # Positive control for the downstream AXI-Lite activity OR that
        # check_diagnostic_observability() re-checks at 0 after this body: drive
        # it to 1 first so the later idle assertion is a live measurement and
        # not a stuck-at-0 pass.
        await prove_axil_any_master_activity(self)

        # csr_read only returns after SmcScoreboard._check_sys_axi has asserted
        # OKAY *and* rdata == the table expected for this item (the SYS-AXI
        # driver writes the analysis port before item_done), so each CHK token
        # below is emitted only after that exact expectation passed. Nothing is
        # printed on the setup path.
        for name, addr, expected, length in DIAGNOSTIC_READS:
            rdata = await self.csr_read(name, addr, expected, length=length)
            cocotb.log.info(
                "CHK-DIAG-CSR-%s: SEP_IN AXI read @ 0x%08x returned OKAY "
                "rdata=0x%0*x == expected 0x%0*x (full %d-bit register, RDL "
                "reset)",
                name,
                addr,
                length * 2,
                rdata,
                length * 2,
                expected,
                length * 8,
            )

        # --- NDMRESET_CLUSTER_COUNT: two legs, neither a spec value check ----
        # Leg 1, parameter-to-CSR propagation: the declared
        # smc_config_pkg::CPU_CLUSTER_COUNT must appear at the software-visible
        # register, masked to the RDL field width. RTL is not a SPEC authority,
        # so this is scoped as a propagation check, not a conformance check --
        # see _cpu_cluster_count for exactly what is and is not proven.
        propagated = await self.csr_read(
            "NDMRESET_CLUSTER_COUNT",
            NDMRESET_CLUSTER_COUNT_ADDR,
            NDMRESET_CLUSTER_COUNT_DECLARED,
        )
        cocotb.log.info(
            "CHK-DIAG-NDMRESET-CLUSTER-COUNT-PROPAGATION: NDMRESET_CLUSTER_COUNT "
            "@ 0x%08x reads 0x%08x == the declared "
            "smc_config_pkg::CPU_CLUSTER_COUNT masked to the %d-bit RDL field. "
            "SCOPE: this proves the declared integration parameter reaches the "
            "software-visible register through the hwif path -- it does NOT "
            "verify that the number is the specified cluster count, because no "
            "non-RTL authority for it exists in-repo (hw/sys/smc/doc/cpu.adoc "
            "bounds CPU cores to 1-4; ndm_reset.rdl only says the register "
            "supports up to 32 clusters)",
            NDMRESET_CLUSTER_COUNT_ADDR,
            propagated,
            _CLUSTER_COUNT_WIDTH,
        )

        # Leg 2, RDL register contract (fully spec-sourced): ndm_reset.rdl:33-38
        # declares the field sw=r / hw=w, so a software write must be dropped and
        # the hardware-supplied value must still be presented afterwards. The
        # write pattern is the bit-inverse, so it fails in both directions: if the
        # field became software-writable the readback returns the inverted
        # pattern, and if the hwif path stopped presenting the parameter it
        # returns something else.
        await self.csr_write(
            "NDMRESET_CLUSTER_COUNT_SW_WRITE",
            NDMRESET_CLUSTER_COUNT_ADDR,
            NDMRESET_CLUSTER_COUNT_WR_PATTERN,
        )
        held = await self.csr_read(
            "NDMRESET_CLUSTER_COUNT_AFTER_SW_WRITE",
            NDMRESET_CLUSTER_COUNT_ADDR,
            NDMRESET_CLUSTER_COUNT_DECLARED,
        )
        cocotb.log.info(
            "CHK-DIAG-NDMRESET-CLUSTER-COUNT-RO: sw write 0x%08x to "
            "NDMRESET_CLUSTER_COUNT @ 0x%08x was dropped (field is sw=r/hw=w in "
            "ndm_reset.rdl:33-38); readback 0x%08x unchanged. This leg's "
            "expectation is the RDL access contract, not the number's value",
            NDMRESET_CLUSTER_COUNT_WR_PATTERN,
            NDMRESET_CLUSTER_COUNT_ADDR,
            held,
        )

        assert self.accesses == len(DIAGNOSTIC_READS) + 4, (
            f"diagnostic CSR precheck issued {self.accesses} accesses, expected "
            f"{len(DIAGNOSTIC_READS) + 4} (1 activity positive control + "
            f"{len(DIAGNOSTIC_READS)} value-compared diagnostic reads + the "
            f"NDMRESET_CLUSTER_COUNT propagation read + its sw=r write/readback)"
        )
        cocotb.log.info(
            "CHK-DIAG-CSR-COUNT: %d/%d RDL-traceable diagnostic CSR reads "
            "value-checked, plus 1 activity positive-control access and the "
            "NDMRESET_CLUSTER_COUNT propagation read + sw=r write/readback pair "
            "(%d SEP_IN AXI accesses total)",
            len(DIAGNOSTIC_READS),
            len(DIAGNOSTIC_READS),
            self.accesses,
        )
