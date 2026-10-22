# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A zero-size SEP or SMC aperture disables that aperture in the SMU crossbar.

``hw/sys/smu/rtl/smu_axi_xbar.sv``: each aperture covers [base, base + size)
and a zero size disables the aperture whatever its base; ``sep_out`` and
``smc_out`` traffic matching neither aperture goes to ``ext_out``, and
unmatched ``ext_in`` traffic gets a decode error. ``hw/sys/smu/doc/index.adoc``
says the same of a region size of 0: no address hits the aperture and its
requests take the miss column of the routing table. SEP BL0 writes
SEP_REGION_SIZE 0 around each DMA into ICCM
(``hw/sys/sep/bootrom/prod/src/sep_dma.c``), so the zero size is a production
state of the crossbar, not a corner.

S0..S3 are ``smu_dtp_sep_dm_dmi_test``: the TEST_DEV posture leaves SEP debug
open, so the SEP inbound filter admits all inbound traffic and the debug
module's system bus is reachable.
S4: the system bus programs the SEP aperture to [0x8000_0000, +0x1100_0000),
    which puts SEP SRAM at global 0x9000_0000, the egress page of
    ``smu_dtp_sep_dm_sba_test``, and lies clear of the SMC window at its reset
    [0x4000_0000, +16 MiB); it opens SEP outbound filter entry 1 over that
    page, and through the SEP's view of the SMC window opens SMC inbound
    filter entry 0 over the whole space. SEP traffic in the SMC window takes
    the dedicated SEP-to-SMC port and never reaches the crossbar
    (``hw/sys/sep/doc/fabric.adoc``, "Fabric Topology"), so the ``sep_out``
    probe uses the SEP's own window instead. The probes then take their
    baseline: an ext_in write into SEP SRAM is OKAY and moves the
    crossbar-to-SEP AW count by one; an ext_in read of the SMC's VERSION_LO
    at its global address is OKAY with the RDL reset value and moves the
    crossbar-to-SMC AR count by one; an ext_in byte read of the top address
    2^56 - 1 is DECERR and moves no count; a system-bus write into the SEP
    window on the egress page matches the SEP rule, which ``sep_out`` has no
    route to, so it reports ``sberror`` and leaves the ``smu_axi_out`` write
    count where it was.
S5: SEP_REGION_SIZE 0 with the SMC aperture unchanged. The ext_in write into
    the former SEP window is DECERR and the crossbar-to-SEP AW count holds,
    with the base where it was and again with the base moved to 0x2000_0000;
    the system-bus write into the former SEP window now matches no rule and
    leaves on ``smu_axi_out`` with ``sberror`` 0, the write count moving and
    the responder holding the word; the SMC and top-byte probes read as the
    baseline. With the base and size restored the SEP probe reads as the
    baseline again.
S6: SMC REGION_SIZE 0, written over the system bus through the SMC window as
    the last access that window admits, with the SEP aperture unchanged. The
    ext_in read of VERSION_LO is DECERR and the crossbar-to-SMC AR count
    holds; the SEP, top-byte and system-bus probes read as the baseline.
S7: both sizes 0. Every ext_in probe is DECERR and no crossbar count moves;
    the system-bus write into the SEP window leaves on ``smu_axi_out``.
S8: a cold reset on ``rst_cold_ni`` returns both apertures to their RDL reset
    values on the ports, and an ext_in write into the reset SEP window and an
    ext_in read into the reset SMC window each move their crossbar count by
    one again. Their responses are recorded, not claimed: the SEP address is
    unowned and the SMC inbound filter is back at its reset.

No request is in flight across an aperture change, and no programmed window
overlaps the other.
"""

from __future__ import annotations

from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge, with_timeout
from ocah_axi_vip import PROT_NONSECURE, RESP_OKAY, resp_name, worst_resp

from seq_lib.smu_addr_map import (
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    SMC_CHIP_CONFIG_VERSION_LO,
    SMC_CHIP_CONFIG_VERSION_LO_RESET,
    c_header_u32,
)
from seq_lib.smu_axi_helpers import AXI_TIMEOUT_NS, make_smu_axi_master
from seq_lib.smu_boundary_regs import smc_base_config_u32
from seq_lib.smu_compose_helpers import sample
from seq_lib.smu_dtp_sep_dm_dmi_test_seq import (
    DMI_OP_READ,
    DMI_OP_WRITE,
    smu_dtp_sep_dm_dmi_test_seq,
)
from seq_lib.smu_dtp_sep_dm_sba_test_seq import (
    COLD_RESET_BOUND,
    COLD_RESET_HOLD,
    EGRESS_ADDR,
    EGRESS_PAGE_END,
    OUTBOUND_CFG_OPEN,
    OUTBOUND_END_ADDR,
    OUTBOUND_FILTER_CONFIG,
    OUTBOUND_START_ADDR,
    SBA_POLLS,
    SBADDRESS0_ADDR,
    SBCS_ADDR,
    SBCS_SBACCESS_32,
    SBCS_SBBUSY,
    SBCS_SBERROR_MASK,
    SBCS_SBERROR_SHIFT,
    SBCS_SBERROR_W1C,
    SBDATA0_ADDR,
    SEP_GLOBAL_BASE_ADDR,
    SEP_GLOBAL_BASE_RESET,
    SEP_REGION_SIZE_ADDR,
    SEP_REGION_SIZE_RESET,
    smu_dtp_sep_dm_sba_test_seq,
)
from seq_lib.smu_filter_helpers import (
    PASS_ALL_END,
    PASS_RW_CONFIG,
    SMC_APERTURE_LOCAL_BASE,
    SMC_APERTURE_REGION_SIZE_REG,
)
from seq_lib.smu_tb_pins import smc_primary_reset

_SEP_ADDR_H = Path(__file__).resolve().parents[6] / "hw/sys/sep/regs/gen/c/sep_addr.h"
SRAM_LOCAL = c_header_u32(_SEP_ADDR_H, "SEP_TOP_SEP_SRAM_BASE_ADDR")
SMC_GLOBAL_BASE_RESET = smc_base_config_u32("SMC_BASE_CONFIG__GLOBAL_BASE__BASE_reset")
SMC_REGION_SIZE_RESET = smc_base_config_u32("SMC_BASE_CONFIG__REGION_SIZE__SIZE_reset")

TOP_BYTE = (1 << 56) - 1
# The SEP window puts SEP SRAM on the egress page the SEP outbound path delivers, so one
# address serves the ext_in probe into SEP SRAM and the sep_out probe into the SEP window.
SEP_WIN_BASE = EGRESS_ADDR - SRAM_LOCAL
SEP_WIN_SIZE = 0x1100_0000
# A second base for the disabled SEP aperture, disjoint from both windows.
SEP_ALT_BASE = 0x2000_0000
SEP_PATTERN = 0x5A5A_0000_5E00_0000
EGRESS_PATTERN = 0x5E00_0000
EGRESS_OFFSET = 0x800
SETTLE_CYCLES = 8
RESET_SETTLE_CYCLES = 512
COUNTS = (
    "sep_xbar_in_aw_count_o",
    "smc_xbar_in_ar_count_o",
    "smc_xbar_in_aw_count_o",
    "smu_axi_out_write_count_o",
    "smu_axi_out_read_count_o",
)
PORTS = {
    "sep_xbar_global_base_o": "sep_base",
    "sep_xbar_region_size_o": "sep_size",
    "smc_global_base_o": "smc_base",
    "smc_region_size_o": "smc_size",
}


class smu_xbar_zero_aperture_test_seq(smu_dtp_sep_dm_sba_test_seq):
    """Probe the crossbar with the SEP aperture, the SMC aperture and both at size 0."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.steps: dict[str, bool] = {}
        self.serial = 0

    def _counts(self) -> tuple[int, ...]:
        return tuple(sample(getattr(self.dut, name), name) for name in COUNTS)

    def _ports(self) -> dict[str, int]:
        return {short: sample(getattr(self.dut, name), name) for name, short in PORTS.items()}

    def _smc_view(self, local: int) -> int:
        return sample(self.dut.smc_global_base_o, "smc_global_base_o") + (
            local - SMC_APERTURE_LOCAL_BASE
        )

    async def _sba_write_status(self, jtag, addr: int, data: int) -> int:
        """A 32-bit system-bus write; returns sberror, cleared again."""
        await self._dmi(jtag, SBCS_ADDR, SBCS_SBACCESS_32 | SBCS_SBERROR_W1C, DMI_OP_WRITE)
        await self._dmi(jtag, SBADDRESS0_ADDR, addr, DMI_OP_WRITE)
        await self._dmi(jtag, SBDATA0_ADDR, data, DMI_OP_WRITE)
        sbcs = SBCS_SBBUSY
        for _ in range(SBA_POLLS):
            sbcs = await self._dmi(jtag, SBCS_ADDR, 0, DMI_OP_READ)
            if not sbcs & SBCS_SBBUSY:
                break
        await self._dmi(jtag, SBCS_ADDR, SBCS_SBERROR_W1C, DMI_OP_WRITE)
        return (sbcs >> SBCS_SBERROR_SHIFT) & SBCS_SBERROR_MASK

    async def _ext(self, master, *, write: bool, addr: int, payload, size: int, label: str):
        """One ext_in transfer; returns (resp, data) once the crossbar counts have settled."""
        if write:
            event = master.init_write(addr, payload, size=size, prot=PROT_NONSECURE)
        else:
            event = master.init_read(addr, payload, size=size, prot=PROT_NONSECURE)
        try:
            await with_timeout(event.wait(), AXI_TIMEOUT_NS, "ns")
        except Exception as exc:
            raise AssertionError(f"TIMEOUT {label} addr=0x{addr:014x}: {exc}") from exc
        raw = event.data
        await ClockCycles(self.dut.clk_smu_i, SETTLE_CYCLES)
        return worst_resp(getattr(raw, "resp", None)), bytes(getattr(raw, "data", b""))

    async def _sep_probe(self, master, base: int, tag: str) -> tuple[str, int]:
        """ext_in writes SEP SRAM at the window `base`: (response, SEP AW count delta)."""
        self.serial += 1
        word = (SEP_PATTERN | self.serial).to_bytes(8, "little")
        before = self._counts()
        resp, _ = await self._ext(
            master, write=True, addr=base + SRAM_LOCAL, payload=word, size=3, label=f"{tag}_sep"
        )
        return resp_name(resp), self._counts()[0] - before[0]

    async def _smc_probe(self, master, tag: str) -> tuple[str, int | None, int]:
        """ext_in reads VERSION_LO through the SMC window: (response, word, SMC AR delta)."""
        before = self._counts()
        resp, data = await self._ext(
            master,
            write=False,
            addr=self._smc_view(SMC_CHIP_CONFIG_VERSION_LO),
            payload=4,
            size=2,
            label=f"{tag}_smc",
        )
        word = int.from_bytes(data[:4], "little") if resp == RESP_OKAY else None
        return resp_name(resp), word, self._counts()[1] - before[1]

    async def _top_probe(self, master, tag: str) -> tuple[str, tuple[int, ...]]:
        """ext_in reads the top byte of the space: (response, every count delta)."""
        before = self._counts()
        resp, _ = await self._ext(
            master, write=False, addr=TOP_BYTE, payload=1, size=0, label=f"{tag}_top"
        )
        return resp_name(resp), tuple(a - b for a, b in zip(self._counts(), before))

    async def _sep_out_probe(self, jtag, tag: str) -> tuple[bool, int, bool]:
        """The system bus writes the egress page, inside the SEP window.

        Returns (refused, smu_axi_out write delta, the responder holds the word).
        """
        self.serial += 1
        word = EGRESS_PATTERN | self.serial
        addr = EGRESS_ADDR + EGRESS_OFFSET
        before = self._counts()
        sberror = await self._sba_write_status(jtag, addr, word)
        await ClockCycles(self.dut.clk_smu_i, SETTLE_CYCLES)
        after = self._counts()
        held = self.test.cfg.axi_out_mem.read_int(addr, 4) == word
        self._log(
            f"{tag} sep_out egress @0x{addr:x} word=0x{word:08x} sberror={sberror} held={held}"
        )
        return sberror != 0, after[3] - before[3], held

    async def _probe(self, master, jtag, tag: str, sep_base: int = SEP_WIN_BASE) -> dict:
        out = {
            "sep": await self._sep_probe(master, sep_base, tag),
            "smc": await self._smc_probe(master, tag),
            "top": await self._top_probe(master, tag),
            "sep_out": await self._sep_out_probe(jtag, tag),
        }
        self._log(f"{tag} ports={self._ports()} probes={out}")
        return out

    async def _sep_aperture(self, jtag, base: int, size: int) -> dict[str, int]:
        """Program the SEP aperture, size first when it shrinks, and return the ports."""
        order = (
            ((SEP_REGION_SIZE_ADDR, size), (SEP_GLOBAL_BASE_ADDR, base))
            if size <= sample(self.dut.sep_xbar_region_size_o, "sep_xbar_region_size_o")
            else ((SEP_GLOBAL_BASE_ADDR, base), (SEP_REGION_SIZE_ADDR, size))
        )
        for addr, value in order:
            await self._sba_write64(jtag, addr, value)
        await self._port_settles("sep_xbar_global_base_o", base)
        await self._port_settles("sep_xbar_region_size_o", size)
        return self._ports()

    async def _cold_reset(self) -> None:
        dut = self.dut
        dut.rst_cold_ni.value = 0
        dut.jtag_trst.value = 0
        for _ in range(COLD_RESET_BOUND):
            await RisingEdge(dut.clk_ref_i)
            if sample(dut.obs_sep_rst_n_o, "obs_sep_rst_n_o") == 0:
                break
        else:
            raise AssertionError("cold reset never reached the SEP reset")
        await ClockCycles(dut.clk_ref_i, COLD_RESET_HOLD)
        dut.rst_cold_ni.value = 1
        dut.jtag_trst.value = 1
        await self.test.jtag_tap_reset(16)
        for _ in range(COLD_RESET_BOUND):
            await RisingEdge(dut.clk_smu_i)
            if sample(dut.obs_sep_rst_n_o, "obs_sep_rst_n_o") == 1:
                break
        else:
            raise AssertionError("the SEP reset never released after the cold reset")
        smc_reset = smc_primary_reset(dut)
        for _ in range(COLD_RESET_BOUND):
            await RisingEdge(dut.clk_smu_i)
            if sample(smc_reset, "smc primary reset") == 1:
                break
        else:
            raise AssertionError("the SMC primary reset never released after the cold reset")
        await ClockCycles(dut.clk_smu_i, RESET_SETTLE_CYCLES)

    async def run(self) -> None:
        await smu_dtp_sep_dm_dmi_test_seq.run(self)
        sb = self.test.env.scoreboard
        jtag = self.jtag
        dut = self.dut

        # S4: the SEP window, the SMC inbound filter, and the baseline of every probe.
        ports = await self._sep_aperture(jtag, SEP_WIN_BASE, SEP_WIN_SIZE)
        await self._sba_write64(jtag, OUTBOUND_START_ADDR, EGRESS_ADDR)
        await self._sba_write64(jtag, OUTBOUND_END_ADDR, EGRESS_PAGE_END)
        await self._sba_write(jtag, OUTBOUND_FILTER_CONFIG, OUTBOUND_CFG_OPEN)
        for addr, value in (
            (INBOUND0_START, 0),
            (INBOUND0_END, PASS_ALL_END),
            (INBOUND0_FILTER_CONFIG, PASS_RW_CONFIG),
        ):
            await self._sba_write64(jtag, self._smc_view(addr), value)
        master = await make_smu_axi_master(cocotb.top, dut.clk_smu_i, smc_primary_reset(dut))
        baseline = await self._probe(master, jtag, "S4")
        want_baseline = {
            "sep": ("OKAY", 1),
            "smc": ("OKAY", SMC_CHIP_CONFIG_VERSION_LO_RESET, 1),
            "top": ("DECERR", (0, 0, 0, 0, 0)),
            "sep_out": (True, 0, False),
        }
        sb.expect_eq(
            "CHK-XBAR-ZERO-BASELINE both apertures programmed: ext_in reaches SEP SRAM and the "
            "SMC, the top byte is DECERR, and the system bus's write into the SEP window is refused",
            (ports, baseline),
            (
                {
                    "sep_base": SEP_WIN_BASE,
                    "sep_size": SEP_WIN_SIZE,
                    "smc_base": SMC_GLOBAL_BASE_RESET,
                    "smc_size": SMC_REGION_SIZE_RESET,
                },
                want_baseline,
            ),
            evidence="CHK-XBAR-ZERO-BASELINE",
        )
        self.steps["S4"] = True

        # S5: SEP size 0, base kept, base moved, then restored.
        zero = await self._sep_aperture(jtag, SEP_WIN_BASE, 0)
        kept = await self._probe(master, jtag, "S5-ZERO")
        moved_ports = await self._sep_aperture(jtag, SEP_ALT_BASE, 0)
        moved = await self._sep_probe(master, SEP_ALT_BASE, "S5-MOVED")
        restored_ports = await self._sep_aperture(jtag, SEP_WIN_BASE, SEP_WIN_SIZE)
        restored = await self._sep_probe(master, SEP_WIN_BASE, "S5-RESTORED")
        sb.expect_eq(
            "CHK-XBAR-ZERO-SEP a zero-size SEP aperture matches nothing at either base, sends "
            "the system bus's write into it out on smu_axi_out, leaves the SMC route alone, and "
            "comes back when restored",
            (zero["sep_size"], kept, moved_ports["sep_base"], moved, restored_ports, restored),
            (
                0,
                {**want_baseline, "sep": ("DECERR", 0), "sep_out": (False, 1, True)},
                SEP_ALT_BASE,
                ("DECERR", 0),
                {
                    "sep_base": SEP_WIN_BASE,
                    "sep_size": SEP_WIN_SIZE,
                    "smc_base": SMC_GLOBAL_BASE_RESET,
                    "smc_size": SMC_REGION_SIZE_RESET,
                },
                ("OKAY", 1),
            ),
            evidence="CHK-XBAR-ZERO-SEP",
        )
        self.steps["S5"] = True

        # S6: SMC size 0 through the SMC window itself; the SEP aperture stays.
        await self._sba_write(jtag, self._smc_view(SMC_APERTURE_REGION_SIZE_REG), 0)
        smc_size = await self._port_settles("smc_region_size_o", 0)
        smc_zero = await self._probe(master, jtag, "S6")
        sb.expect_eq(
            "CHK-XBAR-ZERO-SMC a zero-size SMC aperture matches nothing from ext_in and leaves "
            "the SEP routes alone",
            (smc_size, smc_zero),
            (0, {**want_baseline, "smc": ("DECERR", None, 0)}),
            evidence="CHK-XBAR-ZERO-SMC",
        )
        self.steps["S6"] = True

        # S7: both sizes 0.
        both_ports = await self._sep_aperture(jtag, SEP_WIN_BASE, 0)
        both = await self._probe(master, jtag, "S7")
        sb.expect_eq(
            "CHK-XBAR-ZERO-BOTH with both apertures at size 0 every ext_in probe is DECERR with "
            "no crossbar count moving, and the system bus's write into the SEP window leaves on "
            "smu_axi_out",
            ((both_ports["sep_size"], both_ports["smc_size"]), both),
            (
                (0, 0),
                {
                    **want_baseline,
                    "sep": ("DECERR", 0),
                    "smc": ("DECERR", None, 0),
                    "sep_out": (False, 1, True),
                },
            ),
            evidence="CHK-XBAR-ZERO-BOTH",
        )
        self.steps["S7"] = True

        # S8: cold reset restores both apertures and both routes.
        await self._cold_reset()
        reset_ports = self._ports()
        before = self._counts()
        sep_resp, _ = await self._ext(
            master,
            write=True,
            addr=SEP_GLOBAL_BASE_RESET + 8,
            payload=bytes(8),
            size=3,
            label="S8_sep",
        )
        mid = self._counts()
        smc_resp, _ = await self._ext(
            master,
            write=False,
            addr=SMC_GLOBAL_BASE_RESET + (SMC_CHIP_CONFIG_VERSION_LO - SMC_APERTURE_LOCAL_BASE),
            payload=4,
            size=2,
            label="S8_smc",
        )
        after = self._counts()
        self._log(
            f"S8 ports={reset_ports} sep_resp={resp_name(sep_resp)} "
            f"smc_resp={resp_name(smc_resp)} counts {before}->{mid}->{after}"
        )
        sb.expect_eq(
            "CHK-XBAR-ZERO-COLD-RESET a cold reset returns both apertures to their RDL reset "
            "values and ext_in reaches the SEP and SMC ports again",
            (reset_ports, mid[0] - before[0], after[1] - mid[1]),
            (
                {
                    "sep_base": SEP_GLOBAL_BASE_RESET,
                    "sep_size": SEP_REGION_SIZE_RESET,
                    "smc_base": SMC_GLOBAL_BASE_RESET,
                    "smc_size": SMC_REGION_SIZE_RESET,
                },
                1,
                1,
            ),
            evidence="CHK-XBAR-ZERO-COLD-RESET",
        )
        self.steps["S8"] = True
