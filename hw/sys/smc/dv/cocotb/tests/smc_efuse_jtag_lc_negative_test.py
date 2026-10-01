# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC eFuse JTAG lifecycle *negative* test (PROD deny + identity allow).

Drives product ports only:

  * ``tb_lc_state`` → ``lc_state_i`` (complementary encoding)
  * ``ej_axi`` → ``axil_smc_otp_jtag_req_i``

Under PROD (raw 0x1):

  * non-identity read / write → BLOCK (DECERR + 0xBADCAB1E)
  * JTAG_PUBLIC_IDENTITY read → ALLOW (resp=OKAY; timeout fails)

Every JTAG-side access waits for fuse sense first: until sense completes the
shadow window answers SLVERR / 0xBADCAB1E to allowed and blocked requests
alike, and an allow verdict taken then would not be the DUT's decision.

Also records ``CHIP_CONFIG_LC_STATE`` over SEP_IN with an exact expected
matching the packed ``tb_lc_state`` value. Full multi-state matrix lives in
``smc_efuse_jtag_lc_access_matrix_test``.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, SimTimeoutError, with_timeout
from env.smc_protocol_vip_item import SmcProtocolVipKind
from env.smc_sys_axi_agent import idle_axil_master_inputs
from ocah_axi_vip import OcahAxiLiteMasterAgent
from seq_lib.smc_base_test_seq import wait_fuse_sense_done
from seq_lib.smc_efuse_jtag_lc_negative_test_seq import (
    SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY,
    SMC_EFUSE_MAP_LOCKS,
    smc_efuse_jtag_lc_negative_test_seq,
)
from seq_lib.smc_jtag_vip_utils import check_cpu_jtag_pin_vip
from smc_base_test import smc_base_test

BLOCK_SIGNATURE = 0xBADCAB1E
LC_PROD = 0x1
# Non-restricted lifecycle state, the positive control for the PROD block.
LC_TEST_DEV = 0x0
RESP_OKAY = 0
RESP_DECERR = 3


def pack_lc_state(raw: int) -> int:
    """Pack product lc_state_i = {diff_n, diff_p} (WIDTH=4 each)."""
    raw4 = int(raw) & 0xF
    return (((~raw4) & 0xF) << 4) | raw4


@pyuvm.test()
class smc_efuse_jtag_lc_negative_test(smc_base_test):
    """PROD JTAG eFuse deny paths + identity-read exception."""

    required_evidence = (
        "CHK-CPU-JTAG-DTMCS",
        "CHK-CPU-JTAG-IDCODE",
        "CHK-CPU-JTAG-SCAN-ACTIVITY",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        dut = cocotb.top
        self.errors: list[str] = []
        self.checks = 0

        packed = pack_lc_state(LC_PROD)
        dut.tb_lc_state.value = packed

        idle_axil_master_inputs(dut, "ej_axi")
        self.ejm = OcahAxiLiteMasterAgent.from_prefix(
            dut,
            "ej_axi",
            dut.clk_smc_i,
            dut.rst_primary_smc_clk_no,
            name="smc_ej_axil_neg",
            reset_active_level=False,
        ).sequence
        await ClockCycles(dut.clk_smc_i, 20)
        await wait_fuse_sense_done()

        # Negative: non-identity blocked; identity exception still allowed.
        await self._check_read("PROD", "NON_ID", SMC_EFUSE_MAP_LOCKS, expect_block=True)
        await self._check_read(
            "PROD", "JTAG_PUBLIC_IDENTITY", SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY, expect_block=False
        )
        await self._check_write("PROD", SMC_EFUSE_MAP_LOCKS, expect_block=True)

        # Positive control for the block above, in this same run and on the
        # SAME address, with the lifecycle state the only thing that changed.
        # Without it a DECERR from a wedged JTAG path, or an address that
        # answers DECERR unconditionally, satisfies the PROD legs identically.
        # Sense has completed, so the allowed read must complete OKAY at the
        # eFuse controller; SLVERR would be the shadow window refusing it.
        dut.tb_lc_state.value = pack_lc_state(LC_TEST_DEV)
        await ClockCycles(dut.clk_smc_i, 20)
        _, dev_code = await self._read(SMC_EFUSE_MAP_LOCKS)
        if dev_code is None:
            self.errors.append("[TEST_DEV] NON_ID read TIMEOUT")
        elif dev_code != RESP_OKAY:
            self.errors.append(
                f"[TEST_DEV] NON_ID read @0x{SMC_EFUSE_MAP_LOCKS:08x} expected ALLOW "
                f"(resp=OKAY) once the lifecycle state moved, got resp={dev_code}; the "
                f"PROD block above is then not attributable to the lifecycle state"
            )
        else:
            self.checks += 1
            self.logger.info(
                "JTAG eFuse read  [TEST_DEV] NON_ID @0x%08x -> resp=OKAY: the same "
                "address that PROD blocked completes once the lifecycle state moves",
                SMC_EFUSE_MAP_LOCKS,
            )
        dut.tb_lc_state.value = packed
        await ClockCycles(dut.clk_smc_i, 20)

        # Secondary: CHIP_CONFIG mirror must match the driven packed state.
        lc_seq = _LcStateExactSeq("lc_state_exact", expected=packed)
        await self.start_seq(lc_seq, self.env.sys_axi_agent.sequencer)

        assert not self.errors, "eFuse JTAG LC negative mismatch:\n" + "\n".join(self.errors)

        await check_cpu_jtag_pin_vip()
        await self.record_protocol_vip(
            SmcProtocolVipKind.JTAG,
            type(self).__name__,
            # Directed stimulus floor: the three PROD legs, the TEST_DEV
            # positive control, and the LC-state CSR read. Literal here, not
            # read from the sequence counters.
            min_csr_accesses=5,
            csr_accesses=self.checks + lc_seq.accesses,
            proxy=False,
            details=(
                "PROD JTAG eFuse: NON_ID/write BLOCK (DECERR+0xBADCAB1E); "
                "JTAG_PUBLIC_IDENTITY ALLOW via resp=OKAY after fuse sense "
                "(identity rdata not scored: map content is "
                "smc_efuse_map_read_test's claim); "
                "CHIP_CONFIG_LC_STATE exact; CPU JTAG pins checked"
            ),
        )

    async def _read(self, addr: int):
        event = self.ejm.init_read(address=addr, length=4)
        try:
            await with_timeout(event.wait(), 400, "ns")
        except SimTimeoutError:
            return None, None
        resp = event.data
        rdata = int.from_bytes(resp.data, "little")
        return rdata, _resp_code(resp)

    async def _write(self, addr: int, data: int):
        event = self.ejm.init_write(address=addr, data=data.to_bytes(4, "little"))
        try:
            await with_timeout(event.wait(), 400, "ns")
        except SimTimeoutError:
            return None
        return _resp_code(event.data)

    async def _check_read(self, label: str, cls: str, addr: int, *, expect_block: bool) -> None:
        rdata, code = await self._read(addr)
        # Timeout on a claimed path is a hard fail ([TIMEOUT-MUST-FAIL]).
        if rdata is None or code is None:
            self.errors.append(
                f"[{label}] {cls} read @0x{addr:08x} TIMEOUT (expect_block={expect_block})"
            )
            return
        # Counted once the access came back, so the tally is completions rather
        # than attempts and a run of timeouts cannot report a full count.
        self.checks += 1
        blocked = code == RESP_DECERR
        self.logger.info(
            "JTAG eFuse read  [%s] %s @0x%08x -> rdata=0x%08x resp=%s blocked=%s (exp_block=%s)",
            label,
            cls,
            addr,
            rdata,
            code,
            blocked,
            expect_block,
        )
        if expect_block:
            if not blocked:
                self.errors.append(
                    f"[{label}] {cls} read @0x{addr:08x} expected BLOCK "
                    f"(DECERR) but got resp={code} rdata=0x{rdata:08x}"
                )
            elif rdata != BLOCK_SIGNATURE:
                self.errors.append(
                    f"[{label}] {cls} read @0x{addr:08x} blocked but data "
                    f"0x{rdata:08x} != err-slv signature "
                    f"0x{BLOCK_SIGNATURE:08x}"
                )
            return
        # ALLOW is the response-code contract: the access reached the eFuse
        # controller and completed. The map content behind it is
        # smc_efuse_map_read_test's claim, so rdata is logged, not scored.
        if code != RESP_OKAY:
            self.errors.append(
                f"[{label}] {cls} read @0x{addr:08x} expected ALLOW "
                f"(resp=OKAY) but got resp={code} rdata=0x{rdata:08x}"
            )
        else:
            self.logger.info(
                "JTAG eFuse ALLOW [%s] %s @0x%08x resp=OKAY (rdata=0x%08x not scored)",
                label,
                cls,
                addr,
                rdata,
            )

    async def _check_write(self, label: str, addr: int, *, expect_block: bool) -> None:
        code = await self._write(addr, 0xA5A5_5A5A)
        if code is None:
            self.errors.append(
                f"[{label}] write @0x{addr:08x} TIMEOUT (expect_block={expect_block})"
            )
            return
        self.checks += 1
        blocked = code == RESP_DECERR
        self.logger.info(
            "JTAG eFuse write [%s] NON_ID @0x%08x -> resp=%s blocked=%s (exp_block=%s)",
            label,
            addr,
            code,
            blocked,
            expect_block,
        )
        if expect_block and not blocked:
            self.errors.append(
                f"[{label}] write @0x{addr:08x} expected BLOCK (DECERR) but got resp={code}"
            )
        elif not expect_block and blocked:
            self.errors.append(f"[{label}] write @0x{addr:08x} expected ALLOW but was blocked")


class _LcStateExactSeq(smc_efuse_jtag_lc_negative_test_seq):
    """One-shot SEP_IN CHIP_CONFIG_LC_STATE exact-read sequence."""

    def __init__(self, name: str, *, expected: int) -> None:
        super().__init__(name)
        self._expected = expected

    async def body(self) -> None:
        await self.read_lc_state_exact(self._expected)


def _resp_code(resp):
    code = getattr(resp, "resp", None)
    if code is None:
        return None
    try:
        codes = code if isinstance(code, (list, tuple)) else [code]
        return int(codes[0]) if codes else None
    except Exception:
        return None
