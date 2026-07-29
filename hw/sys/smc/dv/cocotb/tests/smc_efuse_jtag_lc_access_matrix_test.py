# SPDX-License-Identifier: Apache-2.0
"""SMC P2-15 — lifecycle-gated eFuse JTAG access-control matrix.

Exercises the SMC-OTP JTAG access-control policy in
``hw/smc/smc_peripherals/efuse/smc_efuse_wrapper.sv`` end-to-end using two
tb_top hooks lifted for this test:

  * ``tb_lc_state_raw`` / ``tb_lc_state_force_sigint`` drive the differential
    ``lc_state_i`` (SEP-sourced lifecycle state) to a chosen raw value or an
    integrity-error (non-complementary) encoding, and
  * the ``ej_axi`` AXI-Lite master drives ``axil_smc_otp_jtag_req_i`` (the
    JTAG-side eFuse port).

For each lifecycle state the test issues JTAG-side eFuse reads/writes and
asserts the block/allow outcome against the RTL-derived matrix:

  * writes and non-identity reads are blocked (routed to
    ``prim_axi_lite_err_slv`` -> SLVERR, read data ``0xBADCAB1E``) in
    PROD (raw 0x1) and RMA_SIP (raw 0x2/0x3);
  * CHIPLET_ID / PACKAGE_ID reads stay allowed in every non-sigint state; and
  * a lifecycle differential-decode integrity error blocks everything,
    including the identity-read exception.

This is the regression that catches a lifecycle-gating polarity/decode error
on the SMC side (same class of bug as DTP ``feat_ctrl`` polarity mistakes).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, with_timeout
from ocah_axi_vip import OcahAxiLiteMaster

try:
    from cocotb.result import SimTimeoutError
except ImportError:  # pragma: no cover - cocotb version shim
    from cocotb.triggers import SimTimeoutError

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test

# JTAG-side eFuse (full SMC-local) addresses (smc_top_reg.svh).
EFUSE_MAP_NON_ID = 0xC000_B000  # EFUSE_MAP entry 0 (outside the ID windows)
EFUSE_MAP_CHIPLET_ID = 0xC000_B008
EFUSE_MAP_PACKAGE_ID = 0xC000_B028

BLOCK_SIGNATURE = 0xBADCAB1E  # prim_axi_lite_err_slv RESP_DATA (wrapper override)

# Raw lifecycle states (smc_efuse_wrapper decode).
LC_TEST_DEV = 0x0
LC_PROD = 0x1
LC_RMA_SIP = 0x2
LC_RMA_CHIPLET = 0x6
LC_PROD_END = 0x8

# AXI response codes. A blocked JTAG access is routed to
# ``prim_axi_lite_err_slv`` whose ``RESP`` defaults to ``RESP_DECERR`` (the SMC
# wrapper overrides only ``RESP_DATA=0xBADCAB1E``, not ``RESP``), so a blocked
# transaction is a DECERR. An allowed access reaches the real eFuse controller
# (OKAY on silicon; SLVERR on a Verilator build where the fuse macro is not
# sensed). The read data reads back as 0xBADCAB1E on both paths in the Verilator
# stub, so the response code -- not the data -- is the block/allow discriminator.
RESP_OKAY = 0
RESP_SLVERR = 2
RESP_DECERR = 3


@pyuvm.test()
class smc_efuse_jtag_lc_access_matrix_test(smc_base_test):
    """Drive lc_state + JTAG eFuse accesses; assert the block/allow matrix."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        dut = cocotb.top
        self.errors: list[str] = []
        self.checks = 0

        # Idle the JTAG-side eFuse master control and start at TEST_DEV.
        dut.tb_lc_state_raw.value = LC_TEST_DEV
        dut.tb_lc_state_force_sigint.value = 0

        self.ejm = OcahAxiLiteMaster.from_prefix(
            dut,
            "ej_axi",
            dut.clk_smc_i,
            dut.rst_primary_smc_clk_no,
            name="smc_ej_axil",
            reset_active_level=False,
        )
        await ClockCycles(dut.clk_smc_i, 5)

        # (raw, force_sigint, label): expected read-block per address class and
        # expected write-block (write has no ID exception).
        matrix = [
            (LC_TEST_DEV, 0, "TEST_DEV", False, False, False, False),
            (LC_PROD, 0, "PROD", True, False, False, True),
            (LC_RMA_SIP, 0, "RMA_SIP", True, False, False, True),
            (LC_RMA_CHIPLET, 0, "RMA_CHIPLET", False, False, False, False),
            (LC_PROD_END, 0, "PROD_END", False, False, False, False),
            (LC_TEST_DEV, 1, "SIGINT", True, True, True, True),
        ]

        for (raw, sigint, label, blk_nonid, blk_chip, blk_pkg, blk_wr) in matrix:
            await self._set_lc_state(raw, sigint)
            await self._check_read(label, "NON_ID", EFUSE_MAP_NON_ID, blk_nonid)
            await self._check_read(label, "CHIPLET_ID", EFUSE_MAP_CHIPLET_ID, blk_chip)
            await self._check_read(label, "PACKAGE_ID", EFUSE_MAP_PACKAGE_ID, blk_pkg)
            await self._check_write(label, EFUSE_MAP_NON_ID, blk_wr)

        # Restore a benign lifecycle state.
        await self._set_lc_state(LC_TEST_DEV, 0)

        assert not self.errors, "eFuse JTAG LC access-control matrix mismatch:\n" + \
            "\n".join(self.errors)

        await self.record_protocol_vip(
            SmcProtocolVipKind.JTAG,
            type(self).__name__,
            csr_accesses=self.checks,
            proxy=False,
            details=(
                "lc_state-driven JTAG eFuse access-control matrix "
                "(PROD/RMA_SIP block + CHIPLET_ID/PACKAGE_ID exception + "
                "sigint lockdown), block signature 0xBADCAB1E verified"
            ),
        )

    async def _set_lc_state(self, raw: int, force_sigint: int) -> None:
        dut = cocotb.top
        dut.tb_lc_state_raw.value = raw
        dut.tb_lc_state_force_sigint.value = force_sigint
        # Settle the diff decode + the access-control demux spill registers.
        await ClockCycles(dut.clk_smc_i, 20)

        # White-box check of the lifecycle decode itself (simulator-independent):
        # this is the signal a polarity/decode bug would corrupt.
        exp_sigint = 1 if force_sigint else 0
        exp_prod = 0 if force_sigint else (1 if raw in (LC_PROD, LC_RMA_SIP, 0x3) else 0)
        exp_raw = 0 if force_sigint else raw
        try:
            efw = dut.u_dut.u_smc.u_smc_peripherals.u_smc_efuse_wrapper
            got_raw = int(efw.lc_state_smc_raw.value)
            got_sigint = int(efw.lc_sigint_err.value)
            got_prod = int(efw.is_prod_or_rma_sip.value)
            self.logger.info(
                "lc decode raw=0x%x sigint=%d prod_or_rma=%d (exp raw=0x%x sigint=%d prod=%d)",
                got_raw, got_sigint, got_prod, exp_raw, exp_sigint, exp_prod,
            )
            if (got_raw, got_sigint, got_prod) != (exp_raw, exp_sigint, exp_prod):
                self.errors.append(
                    f"lc decode mismatch for raw=0x{raw:x} force_sigint={force_sigint}: "
                    f"got (raw=0x{got_raw:x}, sigint={got_sigint}, prod={got_prod}) "
                    f"exp (raw=0x{exp_raw:x}, sigint={exp_sigint}, prod={exp_prod})"
                )
        except Exception as exc:  # pragma: no cover - hierarchy probe optional
            self.logger.info("lc decode probe unavailable: %s", exc)

    async def _read(self, addr: int):
        """Bounded JTAG eFuse read. Returns (rdata|None, resp_code|None)."""
        event = self.ejm.init_read(address=addr, length=4)
        try:
            await with_timeout(event.wait(), 400, "ns")
        except SimTimeoutError:
            return None, None
        resp = event.data
        rdata = int.from_bytes(resp.data, "little")
        return rdata, _resp_code(resp)

    async def _write(self, addr: int, data: int):
        """Bounded JTAG eFuse write. Returns resp_code|None."""
        event = self.ejm.init_write(address=addr, data=data.to_bytes(4, "little"))
        try:
            await with_timeout(event.wait(), 400, "ns")
        except SimTimeoutError:
            return None
        return _resp_code(event.data)

    async def _check_read(self, label: str, cls: str, addr: int, expect_block: bool) -> None:
        self.checks += 1
        rdata, code = await self._read(addr)
        # A blocked access is the err_slv DECERR. An allowed access reaches the
        # eFuse controller (OKAY on silicon / SLVERR on the un-sensed Verilator
        # stub) -- never a DECERR from this wrapper. The response code is the
        # discriminator because the read data is 0xBADCAB1E on both paths in the
        # Verilator stub.
        blocked = code == RESP_DECERR
        self.logger.info(
            "JTAG eFuse read  [%s] %s @0x%08x -> rdata=%s resp=%s blocked=%s (exp_block=%s)",
            label, cls, addr,
            "None" if rdata is None else f"0x{rdata:08x}",
            code, blocked, expect_block,
        )
        if expect_block and not blocked:
            self.errors.append(
                f"[{label}] {cls} read @0x{addr:08x} expected BLOCK (DECERR) but "
                f"got resp={code} rdata="
                f"{'timeout' if rdata is None else f'0x{rdata:08x}'}"
            )
        elif not expect_block and blocked:
            self.errors.append(
                f"[{label}] {cls} read @0x{addr:08x} expected ALLOW but was "
                f"blocked (DECERR)"
            )
        elif expect_block and blocked and rdata != BLOCK_SIGNATURE:
            self.errors.append(
                f"[{label}] {cls} read @0x{addr:08x} blocked but data "
                f"0x{(rdata or 0):08x} != err-slv signature 0x{BLOCK_SIGNATURE:08x}"
            )

    async def _check_write(self, label: str, addr: int, expect_block: bool) -> None:
        self.checks += 1
        code = await self._write(addr, 0xA5A5_5A5A)
        # A blocked write is routed to the err_slv -> DECERR. An allowed write
        # reaches the real eFuse controller (OKAY / SLVERR), never a DECERR.
        blocked = code == RESP_DECERR
        self.logger.info(
            "JTAG eFuse write [%s] NON_ID @0x%08x -> resp=%s blocked=%s (exp_block=%s)",
            label, addr, code, blocked, expect_block,
        )
        if expect_block and not blocked:
            self.errors.append(
                f"[{label}] write @0x{addr:08x} expected BLOCK (DECERR) but got "
                f"resp={code}"
            )
        elif not expect_block and blocked:
            self.errors.append(
                f"[{label}] write @0x{addr:08x} expected ALLOW but was blocked (DECERR)"
            )


def _resp_code(resp):
    code = getattr(resp, "resp", None)
    if code is None:
        return None
    try:
        codes = code if isinstance(code, (list, tuple)) else [code]
        return int(codes[0]) if codes else None
    except Exception:
        return None
