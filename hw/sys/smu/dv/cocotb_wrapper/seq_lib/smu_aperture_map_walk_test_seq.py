# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC aperture walk: the crossbar decodes every programmed base and size.

``smc_base_config`` (``hw/sys/smc/regs/gen/c/blocks/smc_base_config.h``) holds
the SMC aperture: a 56-bit GLOBAL_BASE and a 32-bit REGION_SIZE that "must be a
non-zero power of two" with GLOBAL_BASE "aligned to this size". The SMU
crossbar turns the pair into its SMC rule ``[GLOBAL_BASE, GLOBAL_BASE +
REGION_SIZE)``, and an inbound transfer that misses every rule has no default
port, so the crossbar answers it DECERR without forwarding it.

REGION_SIZE also sizes the SMC local alias window, and JTAG2AXI reaches
BASE_CONFIG and the inbound filter through that window. The smallest size the
walk programs is therefore the smallest power of two above the inbound filter
registers, so every setting can be followed by the next. The RDL requires
LOCAL_BASE to be aligned to REGION_SIZE as well, and LOCAL_BASE is fixed at
0xC000_0000, so the largest size is 1 GiB. The SEP aperture sits
at its reset ``[0, 16 MiB)``; every base the walk programs lies above it, which
the crossbar's overlap assertion requires.

S1: REGION_SIZE walks every power of two from that floor to 1 GiB, and
    GLOBAL_BASE alternates between the 0xAA.. and 0x55.. patterns aligned to
    the size, so every GLOBAL_BASE bit the alignment leaves free and every
    REGION_SIZE bit walked is set in one setting and clear in the next. A last
    setting puts the smallest window at the top of the 56-bit space, where the
    rule's end carries into bit 56 and has no address past it to probe. Each
    setting reaches ``smc_global_base_o`` / ``smc_region_size_o`` and reads
    back over JTAG2AXI.
S2: at each setting an inbound read of VERSION_LO and a write and readback of
    SCRATCH_COLD at the rebased addresses complete OKAY with the RDL reset
    value and the written word, the ARID/AWID alternating between 0xAA and 0x55.
S3: at each setting the first address of the window is forwarded to the SMC,
    and the word just below the window and the first address past it are not:
    the crossbar-to-SMC AR count moves by exactly one for the address inside
    and not at all for each outside, and the outside reads return DECERR. The
    window's last word is not read: its local offset, REGION_SIZE - 8, lands
    in SMC memories whose unwritten contents read X on a four-state simulator.
S4: GLOBAL_BASE and REGION_SIZE written back to LOCAL_BASE and the RDL reset
    reach the ports and read back.

A zero REGION_SIZE is not programmed: the crossbar rule it forms has
``start == end``, which the address decoder's own map check rejects, and it
closes the local window JTAG2AXI needs to reopen the aperture.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, with_timeout
from ocah_axi_vip import PROT_NONSECURE, resp_name, worst_resp
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    SMC_CHIP_CONFIG_VERSION_LO,
    SMC_CHIP_CONFIG_VERSION_LO_RESET,
    filter_ctrl_bm,
    filter_ctrl_field_reset_encode,
    smc_addr,
    smc_indexed_addr,
)
from seq_lib.smu_axi_helpers import AXI_TIMEOUT_NS, make_smu_axi_master
from seq_lib.smu_boundary_regs import smc_base_config_u32
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)
from seq_lib.smu_tb_pins import smc_primary_reset

ADDR_MASK = (1 << 56) - 1
GLOBAL_BASE_REG = smc_addr("SMC_TOP_SMC_BASE_CONFIG_GLOBAL_BASE_BASE_ADDR")
REGION_SIZE_REG = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
LOCAL_BASE = smc_base_config_u32("SMC_BASE_CONFIG__LOCAL_BASE__BASE_reset")
GLOBAL_BASE_RESET = smc_base_config_u32("SMC_BASE_CONFIG__GLOBAL_BASE__BASE_reset")
REGION_SIZE_RESET = smc_base_config_u32("SMC_BASE_CONFIG__REGION_SIZE__SIZE_reset")

VERSION_LO = SMC_CHIP_CONFIG_VERSION_LO
VERSION_LO_RESET = SMC_CHIP_CONFIG_VERSION_LO_RESET
SCRATCH_COLD = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR")

_IN_CFG = "SMC_TOP_SMC_INBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR"
_IN_START = "SMC_TOP_SMC_INBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR"
_IN_END = "SMC_TOP_SMC_INBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR"
FILTER_ENTRY = 0
CFG_WINDOW = (
    filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__READ_ALLOWED_bm")
    | filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__WRITE_ALLOWED_bm")
    | filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm")
    | filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ALLOW_NS_bm")
    | filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ALLOW_BURST_bm")
    | filter_ctrl_field_reset_encode("DATA_BUS_WIDTH")
)

# Highest local offset JTAG2AXI has to reach between settings: the last word of
# the inbound filter entry the walk reprograms.
_CONTROL_TOP = smc_indexed_addr(_IN_END, FILTER_ENTRY) + 8 - LOCAL_BASE
SIZE_FLOOR_LOG2 = max(
    _CONTROL_TOP - 1, SCRATCH_COLD - LOCAL_BASE, VERSION_LO - LOCAL_BASE
).bit_length()
# LOCAL_BASE has to be aligned to REGION_SIZE too, so its lowest set bit caps the size.
SIZE_CEIL_LOG2 = (LOCAL_BASE & -LOCAL_BASE).bit_length() - 1
PATTERN_A = 0xAA_AAAA_AAAA_AAAA
PATTERN_B = 0x55_5555_5555_5555
ID_A = 0xAA
ID_B = 0x55
# The SEP aperture at its reset value; every walked window lies above it.
SEP_TOP = 1 << 24

VERSION_OFF = VERSION_LO - LOCAL_BASE
SCRATCH_OFF = SCRATCH_COLD - LOCAL_BASE
SCRATCH_PATTERN = 0x5E00_0000
PORT_SETTLE_CYCLES = 64


def walk_settings() -> list[tuple[int, int]]:
    """(GLOBAL_BASE, REGION_SIZE) pairs, sizes ascending, bases alternating."""
    out = []
    for idx, log2 in enumerate(range(SIZE_FLOOR_LOG2, SIZE_CEIL_LOG2 + 1)):
        size = 1 << log2
        base = (PATTERN_A if idx % 2 == 0 else PATTERN_B) & ~(size - 1) & ADDR_MASK
        out.append((base, size))
    # The top of the 56-bit space, where the rule's end carries into bit 56.
    out.append(((1 << 56) - (1 << SIZE_FLOOR_LOG2), 1 << SIZE_FLOOR_LOG2))
    return out


def _require_walk() -> None:
    bad = []
    if VERSION_OFF % 8 or SCRATCH_OFF % 8:
        bad.append("probe registers are not 8-byte aligned")
    for base, size in walk_settings():
        if base % size:
            bad.append(f"base 0x{base:x} not aligned to 0x{size:x}")
        if base - 8 < SEP_TOP:
            bad.append(f"window at 0x{base:x} reaches the SEP reset aperture")
        if base + size > ADDR_MASK + 1:
            bad.append(f"window at 0x{base:x} wraps the 56-bit space")
    if bad:
        raise RuntimeError("aperture walk: " + "; ".join(bad))


_require_walk()


class smu_aperture_map_walk_test_seq:
    """Walk the SMC aperture and prove the crossbar decode at every setting."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.s1_ok = False
        self.s2_ok = False
        self.s3_ok = False
        self.s4_ok = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _pin(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on this tb_top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val)

    async def _j2a_wr(self, jtag, addr: int, data: int, name: str, **kwargs) -> None:
        st, _ = await jtag2axi_single_write(jtag, addr, data, require_complete=True, **kwargs)
        require_jtag_tdo_resolved(f"J2A WR {name}")
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A WR {name} @0x{addr:08x} status={st} want SUCCESS")

    async def _j2a_rd(self, jtag, addr: int, name: str, **kwargs) -> int:
        st, rdata = await jtag2axi_single_read(jtag, addr, require_complete=True, **kwargs)
        require_jtag_tdo_resolved(f"J2A RD {name}")
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A RD {name} @0x{addr:08x} status={st} want SUCCESS")
        return int(rdata)

    async def _j2a_wr32(self, jtag, addr: int, data: int, name: str) -> None:
        word = int(data) & 0xFFFF_FFFF
        packed, wstrb = (word << 32, 0xF0) if addr & 0x4 else (word, 0x0F)
        await self._j2a_wr(jtag, addr, packed, name, wstrb=wstrb, size=SMC_DBG_AXSIZE_4B)

    async def _j2a_rd32(self, jtag, addr: int, name: str) -> int:
        raw = await self._j2a_rd(jtag, addr, name, size=SMC_DBG_AXSIZE_4B)
        return (raw >> 32) & 0xFFFF_FFFF if addr & 0x4 else raw & 0xFFFF_FFFF

    async def _bring_up_tap(self):
        jtag = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        if self._pin("tb_smc_jtag2axi_security_disable") & 1:
            raise AssertionError("SMC J2A still gated after TCK sync")
        return jtag

    async def _ax(self, master, *, write: bool, addr: int, label: str, payload, **attrs):
        if write:
            event = master.init_write(addr, payload, prot=PROT_NONSECURE, **attrs)
        else:
            event = master.init_read(addr, payload, prot=PROT_NONSECURE, **attrs)
        try:
            await with_timeout(event.wait(), AXI_TIMEOUT_NS, "ns")
        except Exception as exc:
            raise AssertionError(
                f"TIMEOUT {label} addr=0x{addr:014x} bound={AXI_TIMEOUT_NS}ns: {exc}"
            ) from exc
        raw = event.data
        resp = worst_resp(getattr(raw, "resp", None))
        data = int.from_bytes(bytes(getattr(raw, "data", b"")), "little")
        return resp, data

    async def _read(self, master, addr: int, label: str, arid: int = 0):
        return await self._ax(master, write=False, addr=addr, label=label, payload=4, arid=arid)

    async def _write(self, master, addr: int, value: int, label: str, awid: int = 0):
        resp, _ = await self._ax(
            master,
            write=True,
            addr=addr,
            label=label,
            payload=int(value).to_bytes(4, "little"),
            awid=awid,
        )
        return resp

    async def _counted_read(self, master, addr: int, label: str):
        """Read once; return (resp, data, crossbar-to-SMC AR handshakes it caused)."""
        before = self._pin("smc_xbar_in_ar_count_o")
        resp, data = await self._read(master, addr, label)
        await ClockCycles(self.dut.clk_smu_i, 4)
        return resp, data, self._pin("smc_xbar_in_ar_count_o") - before

    async def _program(self, jtag, base: int, size: int, tag: str) -> tuple[int, int, int, int]:
        """Open filter entry 0 over the window, then move the aperture onto it."""
        await self._j2a_wr(jtag, smc_indexed_addr(_IN_START, FILTER_ENTRY), base, f"{tag}_START")
        await self._j2a_wr(
            jtag, smc_indexed_addr(_IN_END, FILTER_ENTRY), base + size - 1, f"{tag}_END"
        )
        await self._j2a_wr(jtag, smc_indexed_addr(_IN_CFG, FILTER_ENTRY), CFG_WINDOW, f"{tag}_CFG")
        await self._j2a_wr(jtag, GLOBAL_BASE_REG, base, f"{tag}_GLOBAL_BASE")
        await self._j2a_wr32(jtag, REGION_SIZE_REG, size, f"{tag}_REGION_SIZE")
        await ClockCycles(self.dut.clk_smu_i, PORT_SETTLE_CYCLES)
        rb_base = await self._j2a_rd(jtag, GLOBAL_BASE_REG, f"{tag}_GLOBAL_BASE_RB") & ADDR_MASK
        rb_size = await self._j2a_rd32(jtag, REGION_SIZE_REG, f"{tag}_REGION_SIZE_RB")
        return (
            self._pin("smc_global_base_o"),
            self._pin("smc_region_size_o"),
            rb_base,
            rb_size,
        )

    async def run(self) -> None:
        dut = self.dut
        sb = self.test.env.scoreboard
        await self.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, 16)

        sep_window = (self._pin("sep_xbar_global_base_o"), self._pin("sep_xbar_region_size_o"))
        sb.expect_true(
            "SEP aperture lies below every walked SMC window",
            sep_window[0] + sep_window[1] <= SEP_TOP,
        )

        jtag = await self._bring_up_tap()
        master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))
        settings = walk_settings()

        ports, readback, inside, edges = {}, {}, {}, {}
        for idx, (base, size) in enumerate(settings):
            tag = f"W{idx:02d}"
            ident = ID_A if idx % 2 == 0 else ID_B
            gb, rs, rb_base, rb_size = await self._program(jtag, base, size, tag)
            ports[tag] = (gb, rs)
            readback[tag] = (rb_base, rb_size)

            rd_resp, rd_data = await self._read(
                master, base + VERSION_OFF, f"{tag}_version", arid=ident
            )
            value = SCRATCH_PATTERN | idx
            wr_resp = await self._write(
                master, base + SCRATCH_OFF, value, f"{tag}_scratch_wr", awid=ident
            )
            rb_resp, rb_data = await self._read(
                master, base + SCRATCH_OFF, f"{tag}_scratch_rb", arid=ident
            )
            inside[tag] = (
                resp_name(rd_resp),
                rd_data & 0xFFFF_FFFF,
                resp_name(wr_resp),
                resp_name(rb_resp),
                rb_data & 0xFFFF_FFFF,
            )

            first = await self._counted_read(master, base, f"{tag}_first")
            below = await self._counted_read(master, base - 8, f"{tag}_below")
            if base + size <= ADDR_MASK:
                past = await self._counted_read(master, base + size, f"{tag}_past")
            else:
                past = (None, None, 0)
            edges[tag] = (
                first[2],
                below[2],
                resp_name(below[0]),
                past[2],
                resp_name(past[0]) if past[0] is not None else "TOP",
            )
            self._log(
                f"CHK-SMCMAP-WALK {tag} base=0x{base:014x} size=0x{size:08x} "
                f"ports=(0x{gb:x},0x{rs:x}) inside={inside[tag]} "
                f"edges first={first[2]}/{resp_name(first[0])} below={below[2]}/{resp_name(below[0])} "
                f"past={edges[tag][3]}/{edges[tag][4]}"
            )

        want_ports = {f"W{i:02d}": (b, s) for i, (b, s) in enumerate(settings)}
        sb.expect_eq(
            f"CHK-SMCMAP-WALK-PORT {len(settings)} of {len(settings)} settings reach "
            "smc_global_base_o and smc_region_size_o",
            ports,
            want_ports,
            evidence="CHK-SMCMAP-WALK-PORT",
        )
        sb.expect_eq(
            f"CHK-SMCMAP-WALK-PORT {len(settings)} of {len(settings)} settings read back over JTAG2AXI",
            readback,
            want_ports,
        )
        self.s1_ok = True

        sb.expect_eq(
            f"CHK-SMCMAP-WALK-INSIDE {len(settings)} of {len(settings)} settings serve VERSION_LO "
            "and SCRATCH_COLD at the rebased addresses",
            inside,
            {
                f"W{i:02d}": ("OKAY", VERSION_LO_RESET, "OKAY", "OKAY", SCRATCH_PATTERN | i)
                for i in range(len(settings))
            },
            evidence="CHK-SMCMAP-WALK-INSIDE",
        )
        self.s2_ok = True

        sb.expect_eq(
            f"CHK-SMCMAP-WALK-EDGE {len(settings)} of {len(settings)} settings forward the first "
            "address and refuse the word below and the address past the window",
            edges,
            {
                f"W{i:02d}": (1, 0, "DECERR", 0, "DECERR" if b + sz <= ADDR_MASK else "TOP")
                for i, (b, sz) in enumerate(settings)
            },
            evidence="CHK-SMCMAP-WALK-EDGE",
        )
        self.s3_ok = True

        await self._j2a_wr(jtag, GLOBAL_BASE_REG, LOCAL_BASE, "RESTORE_GLOBAL_BASE")
        await self._j2a_wr32(jtag, REGION_SIZE_REG, REGION_SIZE_RESET, "RESTORE_REGION_SIZE")
        await self._j2a_wr(jtag, smc_indexed_addr(_IN_CFG, FILTER_ENTRY), 0, "RESTORE_CFG")
        await ClockCycles(dut.clk_smu_i, PORT_SETTLE_CYCLES)
        restored = (
            self._pin("smc_global_base_o"),
            self._pin("smc_region_size_o"),
            await self._j2a_rd(jtag, GLOBAL_BASE_REG, "RESTORE_GLOBAL_BASE_RB") & ADDR_MASK,
            await self._j2a_rd32(jtag, REGION_SIZE_REG, "RESTORE_REGION_SIZE_RB"),
        )
        sb.expect_eq(
            "CHK-SMCMAP-RESTORE GLOBAL_BASE and REGION_SIZE return to LOCAL_BASE and the RDL reset",
            restored,
            (LOCAL_BASE, REGION_SIZE_RESET, LOCAL_BASE, REGION_SIZE_RESET),
            evidence="CHK-SMCMAP-RESTORE",
        )
        self._log(
            f"CHK-SMCMAP-WALK: {len(settings)} settings, sizes 2^{SIZE_FLOOR_LOG2}..2^"
            f"{SIZE_CEIL_LOG2}, GLOBAL_BASE reset 0x{GLOBAL_BASE_RESET:x}"
        )
        self.s4_ok = True
