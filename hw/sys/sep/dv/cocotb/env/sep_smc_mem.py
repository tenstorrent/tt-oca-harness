# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC-side memory behind the SEP->SMC AXI4 boundary.

The ``rom_boot`` target places the wrapper's ``sep_ext_to_smc_axi`` struct port
on ``u_smc_axi_if`` and the shared ``OcahAxiSlaveAgent`` answers it. This module
owns the responder's geometry and the words it holds before the Boot ROM's
first fetch: the SMC scratch words the ROM polls, the DFX status word its boot
gate reads, the two strap words, the packed manifest+BL1 image, and the
per-test strap and status injections the testlist carries as plusargs.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator, Mapping
from pathlib import Path

from ocah_axi_vip import OcahAxiConfig, OcahAxiProtocol, OcahAxiSlaveSequence

# sep_pkg sep_system_peripherals_internal_axi_* geometry (56/64/6/12) and the
# sparse span the responder answers.
SMC_AXI_GEOMETRY = OcahAxiConfig(
    protocol=OcahAxiProtocol.AXI4,
    addr_width=56,
    data_width=64,
    id_width=6,
    user_width=12,
)
SMC_MEM_SIZE = 1 << 56

# SEP-side addresses of the SMC words the ROM reads or publishes: smc_addr.h
# through the identity remap tb_top configures (SMC-local 0xC000_xxxx is
# 0x4000_xxxx from SEP).
SMC_SCRATCH8_ADDR = 0x4003_90C0  # manifest offset from the SMC-SRAM base
SMC_SCRATCH9_ADDR = 0x4003_90C8  # SMC->SEP status word the ROM polls
SMC_SCRATCH10_ADDR = 0x4003_90D0  # raw DFX status the ROM publishes when it blocks
SMC_DFT_STATUS_ADDR = 0x4000_B800  # DFX_CTRL_STATUS_SMU, the MEM_REPAIR/MBIST gate's word
SMC_STRAPS_LO_ADDR = 0x4040_3000  # STRAPS_LO, bits [31:0] of the strap word
SMC_STRAPS_HI_ADDR = SMC_STRAPS_LO_ADDR + 4  # STRAPS_HI, bits [63:32]

# scratch[9]: SRAM_INIT | MANIFEST_READY | BUFFER_READY | SRAM_PROTECTED, so the
# ROM's manifest-ready poll breaks.
SMC_SEP_STATUS_DEFAULT = 0x0F
# scratch[8]: the OCA manifest sits at this offset in the packed SMC image, so
# manifest_addr = SMC-SRAM base + 0x1000.
SMC_MANIFEST_OFFSET_DEFAULT = 0x1000
# DFX_CTRL_STATUS_SMU of a part that boots: bit 0 mem_repair_done, bit 1
# mem_repair_success, bit 4 mbist_done, bit 8 mbist_pass. The ROM's boot gate
# checks both arms (vector.S); without mbist_done it polls, times out after
# MBIST_DONE_WAIT_ITERS and halts. Every rom_fw test without +sep_dft_status
# boots against this word.
SMC_DFT_STATUS_DEFAULT = 0x0000_0113
# STRAPS_LO[25] primary_chiplet (sep_smc_interface.h). A strap value, not a
# boot-path selector: boot_from_spi() is `primary_chiplet && !boot_recovery`.
STRAPS_LO_PRIMARY_CHIPLET = 1 << 25

_WORD_MASK = 0xFFFF_FFFF


def load_verilog_hex(path: str | Path) -> Iterator[tuple[int, bytes]]:
    """Yield ``(address, bytes)`` runs from a ``$readmemh`` byte image.

    ``@<hex>`` tokens set the byte address; every other token is one byte.
    ``//`` and ``/* */`` comments are skipped. Consecutive bytes coalesce into
    one run so a multi-megabyte image costs one backdoor write per run.
    """
    text = Path(path).read_text()
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    addr = 0
    run_start = 0
    run = bytearray()
    for tok in text.split():
        if tok.startswith("@"):
            if run:
                yield run_start, bytes(run)
                run = bytearray()
            addr = int(tok[1:], 16)
            continue
        if not run:
            run_start = addr
        run.append(int(tok.replace("_", ""), 16))
        addr += 1
    if run:
        yield run_start, bytes(run)


def _hex_plusarg(plusargs: Mapping[str, object], name: str) -> int | None:
    value = plusargs.get(name)
    if value is None or value is True:
        return None
    return int(str(value), 16) & _WORD_MASK


def preload_smc_mem(
    mem: OcahAxiSlaveSequence,
    plusargs: Mapping[str, object],
    log: logging.Logger,
) -> None:
    """Program the responder's memory the way the Boot ROM expects to find it.

    The ``+sep_smc_mem_hex`` image lands after the defaults and the explicit
    injections land after the image, so an explicit request wins over whatever
    the image covers. ``+sep_boot_from_spi`` and ``+sep_straps_lo`` OR into
    STRAPS_LO so both combine; ``+sep_dft_status`` and ``+sep_straps_hi`` set
    their whole word.
    """
    mem.write32(SMC_SCRATCH9_ADDR, SMC_SEP_STATUS_DEFAULT)
    mem.write32(SMC_SCRATCH8_ADDR, SMC_MANIFEST_OFFSET_DEFAULT)
    mem.write32(SMC_DFT_STATUS_ADDR, SMC_DFT_STATUS_DEFAULT)
    # The ROM's pre-C boot gate reads both strap halves (STRAPS_LO[13]
    # BYPASS_SRAM_REPAIR, STRAPS_HI[22] MBIST_BYPASS); both hold a defined zero.
    mem.write32(SMC_STRAPS_LO_ADDR, 0)
    mem.write32(SMC_STRAPS_HI_ADDR, 0)

    image = plusargs.get("sep_smc_mem_hex")
    if image and image is not True:
        total = 0
        for addr, data in load_verilog_hex(str(image)):
            mem.write(addr, data)
            total += len(data)
        log.info("[smc_mem] preloaded %d bytes from %s", total, image)

    if "sep_boot_from_spi" in plusargs:
        mem.write32(SMC_STRAPS_LO_ADDR, mem.read32(SMC_STRAPS_LO_ADDR) | STRAPS_LO_PRIMARY_CHIPLET)
        log.info("[smc_mem] STRAPS_LO[25] primary_chiplet=1 (+sep_boot_from_spi)")
    straps_lo = _hex_plusarg(plusargs, "sep_straps_lo")
    if straps_lo is not None:
        mem.write32(SMC_STRAPS_LO_ADDR, mem.read32(SMC_STRAPS_LO_ADDR) | straps_lo)
        log.info(
            "[smc_mem] STRAPS_LO or'd with 0x%08x (+sep_straps_lo): "
            "bypass_sram_repair=%d recovery=%d",
            straps_lo,
            (straps_lo >> 13) & 1,
            (straps_lo >> 19) & 1,
        )
    dft_status = _hex_plusarg(plusargs, "sep_dft_status")
    if dft_status is not None:
        mem.write32(SMC_DFT_STATUS_ADDR, dft_status)
        log.info("[smc_mem] DFX_CTRL_STATUS_SMU set to 0x%08x (+sep_dft_status)", dft_status)
    straps_hi = _hex_plusarg(plusargs, "sep_straps_hi")
    if straps_hi is not None:
        mem.write32(SMC_STRAPS_HI_ADDR, straps_hi)
        log.info(
            "[smc_mem] STRAPS_HI set to 0x%08x (+sep_straps_hi): mbist_bypass=%d rotate=%d",
            straps_hi,
            (straps_hi >> 22) & 1,
            (straps_hi >> 26) & 1,
        )
