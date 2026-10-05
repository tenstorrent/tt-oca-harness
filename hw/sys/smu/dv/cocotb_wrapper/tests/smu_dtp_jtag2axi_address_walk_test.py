# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dtp_jtag2axi_address_walk_test - every address bit of the three DTP JTAG2AXI bridges.

The DTP's three JTAG2AXI bridges reach the SMC fabric, the SMC OTP controller
and the SEP OTP controller through nets the SMU wires between u_dtp, u_smc and
u_sep, and the SMC fabric bridge also reaches the adopter AXI-Lite window and
the DTP CSR window through the SMC. A single-op carries its own write strobe,
and a strobe of zero is a legal AXI write that changes no byte, so every
walked write that could land on a live register or fuse carries a zero
strobe.

Each walk records the address handshakes on the AXI-Lite link at the far end
of the path, and every address issued has to arrive there, in order, on the
channel it was issued on:

S1: SMC fabric bridge: a distinct byte written at byte offsets 1, 2 and 3 of
    SCRATCH_COLD, a read-write register (smc_misc_wrap register description),
    reads back at its offset, and the word read afterwards holds all three
    bytes over the byte at offset 0; the register is then restored. A
    zero-strobe write to 0x1000, outside the SMC map and inside the SEP
    aperture, completes.
S2: adopter window (smc_addr.h SMC_EXTERNAL, at 0xC040_0000):
    the SMC forwards every access to its AXI-Lite external bus except the
    eFuse SHIM range at the window base, which it diverts to the eFuse
    controller, and that reaches the SHIM on ``efuse_bank_ctrl_req_o``
    (``doc/integrator/src/smu.adoc``, "AXI-Lite External Window"). A write
    and a read at the base plus 2^k for every k below 22 each arrive, in
    order, on one of those two links at their window offset.
S3: DTP CSR window (DTP_CTRL_REG, 2 KiB at 0xC000_B000): a read and a
    zero-strobe write at the base plus 2^k for every k below 11 each arrive,
    in order, on the SMC-to-DTP CSR link at their window offset. The
    responses are recorded: the SMC forwards the window to the DTP
    undecoded, and the cross-trigger network answers offsets 0x100 and 0x400,
    which fall outside its matrix registers and port windows, with an error
    (``hw/ip/cross_trigger/cross_trigger_network/doc/memmap.adoc``).
S4, S5: the SMC and SEP OTP bridges: a read and a zero-strobe write at 0,
    2^k for every k below 32 and 0xFFFF_FFFF each complete and arrive on the
    DTP-to-OTP link with the address issued.
S6: a cold reset on rst_cold_ni takes the primary SMC reset low and releases
    it again.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from ocah_jtag_vip import OcahJtagState
from seq_lib.smu_addr_map import smc_addr
from seq_lib.smu_compose_helpers import hier, sample
from seq_lib.smu_jtag_helpers import (
    J2A_OP_READ,
    J2A_OP_WRITE,
    J2A_STATUS_BUSY,
    J2A_STATUS_SUCCESS,
    axi64_unpack32,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    pack_otp_single_op,
    require_jtag_tdo_resolved,
    unpack_otp_single_op,
)
from seq_lib.smu_tb_pins import smu_scope
from smu_base_test import smu_base_test

SCRATCH = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR")
EXT_BASE = smc_addr("SMC_TOP_SMC_EXTERNAL_BASE_ADDR")
# smc_pkg::SmcExternalWindowSize: the decoded window, not just what smc_external allocates.
EXT_SIZE = 0x40_0000
DTP_BASE = smc_addr("SMC_TOP_DTP_CTRL_REG_BASE_ADDR")
DTP_SIZE = smc_addr("SMC_TOP_DTP_CTRL_REG_SIZE")
SEP_APERTURE_ADDR = 0x1000
POLLS = 128
RESET_BOUND = 20000
RESET_HOLD = 64


# AXI-Lite 32/32 request and response packing, LSB first: r_ready, ar_valid,
# ar {prot, addr}, b_ready, w_valid, w {strb, data}, aw_valid, aw {prot, addr};
# r_valid, r {resp, data}, ar_ready, b_valid, b, w_ready, aw_ready.
AXIL_REQ_BITS = 111
AR_VALID, AR_ADDR = 1, 5
AW_VALID, AW_ADDR = 75, 79
AR_READY, AW_READY = 35, 40
S1_BYTES = {1: 0x5A, 2: 0xC3, 3: 0x96}


def _bits_below(size: int) -> list[int]:
    return [1 << k for k in range(size.bit_length() - 1)]


class _AxilTap:
    """Address handshakes on one AXI-Lite 32/32 link, in arrival order."""

    def __init__(self, req, resp, clk, seen: list | None = None) -> None:
        if len(req) != AXIL_REQ_BITS:
            raise AssertionError(f"{req._path} is {len(req)} bits, not an AXI-Lite 32/32 request")
        self._req, self._resp, self._clk = req, resp, clk
        self.seen: list[tuple[str, int]] = [] if seen is None else seen
        self._task = cocotb.start_soon(self._watch())

    async def _watch(self) -> None:
        while True:
            await RisingEdge(self._clk)
            req, resp = self._req.value, self._resp.value
            if not (req.is_resolvable and resp.is_resolvable):
                continue
            req, resp = int(req), int(resp)
            if (req >> AW_VALID) & 1 and (resp >> AW_READY) & 1:
                self.seen.append(("w", (req >> AW_ADDR) & 0xFFFF_FFFF))
            if (req >> AR_VALID) & 1 and (resp >> AR_READY) & 1:
                self.seen.append(("r", (req >> AR_ADDR) & 0xFFFF_FFFF))

    def take(self) -> list[tuple[str, int]]:
        seen = list(self.seen)
        self.seen.clear()
        return seen

    def stop(self) -> None:
        self._task.cancel()


@pyuvm.test()
class smu_dtp_jtag2axi_address_walk_test(smu_base_test):
    """Every address bit of the SMC fabric and both OTP JTAG2AXI bridges reaches its target."""

    use_shared_env = True

    async def _fab(self, jtag, write: bool, addr: int, *, size: int, wstrb: int = 0) -> int:
        if write:
            st, _ = await jtag2axi_single_write(
                jtag, addr, 0, wstrb=wstrb, size=size, poll_limit=POLLS
            )
        else:
            st, _ = await jtag2axi_single_read(jtag, addr, size=size, poll_limit=POLLS)
        require_jtag_tdo_resolved(f"fabric walk @0x{addr:x}")
        return st

    async def _fab_data(
        self, jtag, write: bool, addr: int, data: int, *, size: int, wstrb: int = 0
    ) -> tuple[int, int]:
        if write:
            st, rdata = await jtag2axi_single_write(
                jtag, addr, data, wstrb=wstrb, size=size, poll_limit=POLLS, require_complete=True
            )
        else:
            st, rdata = await jtag2axi_single_read(
                jtag, addr, size=size, poll_limit=POLLS, require_complete=True
            )
        require_jtag_tdo_resolved(f"fabric @0x{addr:x}")
        return st, int(rdata)

    async def _rd32(self, jtag, addr: int) -> int:
        st, rdata = await self._fab_data(jtag, False, addr, 0, size=2)
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(f"read @0x{addr:x} status={st}")
        return axi64_unpack32(addr, rdata)

    async def _otp(self, jtag, tdr: str, write: bool, addr: int) -> int:
        op = J2A_OP_WRITE if write else J2A_OP_READ
        await jtag.write(tdr, pack_otp_single_op(op, addr, 0, wstrb=0))
        require_jtag_tdo_resolved(f"{tdr} issue @0x{addr:x}")
        await ClockCycles(cocotb.top.clk_smu_i, 32)
        status = J2A_STATUS_BUSY
        for _ in range(POLLS):
            capt = await jtag.read(tdr, shift_value=0)
            status, _ = unpack_otp_single_op(capt)
            if status != J2A_STATUS_BUSY:
                break
            await ClockCycles(cocotb.top.clk_smu_i, 16)
        return status

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard
        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)

        smu = smu_scope(dut)
        before = await self._rd32(jtag, SCRATCH)
        s1 = []
        for offset, byte in S1_BYTES.items():
            addr = SCRATCH + offset
            lane = addr & 7
            st, _ = await self._fab_data(
                jtag, True, addr, byte << (8 * lane), size=0, wstrb=1 << lane
            )
            st_r, rdata = await self._fab_data(jtag, False, addr, 0, size=0)
            s1.append((st, st_r, (rdata >> (8 * lane)) & 0xFF))
        after = await self._rd32(jtag, SCRATCH)
        await self._fab_data(
            jtag, True, SCRATCH, before << (8 * (SCRATCH & 4)), size=2, wstrb=0x0F << (SCRATCH & 4)
        )
        outside = await self._fab(jtag, True, SEP_APERTURE_ADDR, size=2, wstrb=0)
        want_after = (before & 0xFF) | sum(b << (8 * o) for o, b in S1_BYTES.items())
        self.logger.info(f"CHK-J2A-WALK-FABRIC bytes={s1} word=0x{after:08x} outside_map={outside}")
        sb.expect_eq(
            "CHK-J2A-WALK-FABRIC",
            (s1, after, outside != J2A_STATUS_BUSY),
            (
                [(J2A_STATUS_SUCCESS, J2A_STATUS_SUCCESS, b) for b in S1_BYTES.values()],
                want_after,
                True,
            ),
            evidence="CHK-J2A-WALK-FABRIC",
        )

        # The eFuse SHIM range at the window base leaves on the eFuse bank
        # control link rather than the external bus, so both feed one list.
        window: list[tuple[str, int]] = []
        taps = [
            _AxilTap(req, resp, dut.clk_smu_i, window)
            for req, resp in (
                (dut.u_dut.smc_external_req, dut.u_dut.smc_external_resp),
                (dut.u_dut.smc_efuse_bank_ctrl_req, dut.u_dut.smc_efuse_bank_ctrl_resp),
            )
        ]
        s2, issued = [], []
        for bit in _bits_below(EXT_SIZE):
            addr = EXT_BASE + bit
            size = 0 if bit < 4 else 2
            wstrb = (1 << (bit & 7)) if size == 0 else (0x0F << (addr & 4))
            s2.append(await self._fab(jtag, True, addr, size=size, wstrb=wstrb))
            s2.append(await self._fab(jtag, False, addr, size=size))
            issued += [("w", bit), ("r", bit)]
        arrived = [(ch, a & (EXT_SIZE - 1)) for ch, a in window]
        for tap in taps:
            tap.stop()
        self.logger.info(f"CHK-J2A-WALK-EXTERNAL arrived={arrived}")
        self.logger.info(f"OBSERVATION CHK-J2A-WALK-EXTERNAL statuses={s2}")
        sb.expect_eq(
            "CHK-J2A-WALK-EXTERNAL every walked offset arrives on the external or eFuse SHIM link",
            (arrived, J2A_STATUS_BUSY in s2),
            (issued, False),
            evidence="CHK-J2A-WALK-EXTERNAL",
        )

        tap = _AxilTap(
            hier(smu, "smc_axil_dtp_csr_req"), hier(smu, "smc_axil_dtp_csr_resp"), dut.clk_smu_i
        )
        s3, issued = [], []
        for bit in _bits_below(DTP_SIZE):
            addr = DTP_BASE + bit
            size = 0 if bit < 4 else 2
            s3.append(await self._fab(jtag, False, addr, size=size))
            s3.append(await self._fab(jtag, True, addr, size=size, wstrb=0))
            issued += [("r", bit), ("w", bit)]
        arrived = [(ch, a & (DTP_SIZE - 1)) for ch, a in tap.take()]
        tap.stop()
        self.logger.info(f"CHK-J2A-WALK-DTP-CSR arrived={arrived}")
        self.logger.info(f"OBSERVATION CHK-J2A-WALK-DTP-CSR statuses={s3}")
        sb.expect_eq(
            "CHK-J2A-WALK-DTP-CSR every walked offset arrives on the DTP CSR link",
            (arrived, J2A_STATUS_BUSY in s3),
            (issued, False),
            evidence="CHK-J2A-WALK-DTP-CSR",
        )

        otp_addrs = [0] + [1 << k for k in range(32)] + [0xFFFF_FFFF]
        for tdr, net, token in (
            ("SMC_OTP_AXI_SINGLE_OP", "dtp_axil_smc_otp_jtag", "CHK-J2A-WALK-SMC-OTP"),
            ("SEP_OTP_AXI_SINGLE_OP", "dtp_axil_sep_otp_jtag", "CHK-J2A-WALK-SEP-OTP"),
        ):
            tap = _AxilTap(hier(smu, f"{net}_req"), hier(smu, f"{net}_resp"), dut.clk_smu_i)
            statuses, issued = [], []
            for addr in otp_addrs:
                statuses.append(await self._otp(jtag, tdr, False, addr))
                statuses.append(await self._otp(jtag, tdr, True, addr))
                issued += [("r", addr), ("w", addr)]
            arrived = tap.take()
            tap.stop()
            self.logger.info(f"{token} statuses={statuses} arrived={len(arrived)}")
            sb.expect_eq(
                f"{token} every OTP address arrives on the DTP-to-OTP link",
                (arrived, J2A_STATUS_BUSY in statuses),
                (issued, False),
                evidence=token,
            )

        observed = []
        dut.rst_cold_ni.value = 0
        dut.jtag_trst.value = 0
        for _ in range(RESET_BOUND):
            await RisingEdge(dut.clk_ref_i)
            if sample(dut.rst_primary_smc_clk_n_o, "rst_primary_smc_clk_n_o") == 0:
                break
        observed.append(sample(dut.rst_primary_smc_clk_n_o, "rst_primary_smc_clk_n_o"))
        await ClockCycles(dut.clk_ref_i, RESET_HOLD)
        dut.rst_cold_ni.value = 1
        dut.jtag_trst.value = 1
        await self.jtag_tap_reset(16)
        for _ in range(RESET_BOUND):
            await RisingEdge(dut.clk_smu_i)
            if sample(dut.rst_primary_smc_clk_n_o, "rst_primary_smc_clk_n_o") == 1:
                break
        observed.append(sample(dut.rst_primary_smc_clk_n_o, "rst_primary_smc_clk_n_o"))
        self.logger.info(f"CHK-J2A-WALK-COLD-RESET primary reset during/after={observed}")
        sb.expect_eq(
            "CHK-J2A-WALK-COLD-RESET", observed, [0, 1], evidence="CHK-J2A-WALK-COLD-RESET"
        )
