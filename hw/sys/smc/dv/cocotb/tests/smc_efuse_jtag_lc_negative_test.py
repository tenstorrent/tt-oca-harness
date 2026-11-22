# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC eFuse JTAG lifecycle *negative* test (PROD deny + identity allow).

Drives product ports only:

  * ``tb_lc_state`` → ``lc_state_i`` (complementary encoding)
  * ``ej_axi`` → ``axil_smc_otp_jtag_req_i``

Under PROD (raw 0x1):

  * non-identity read (LOCKS, the LOCKS word just below the identity window,
    the I2C_I3C_ID word just above it) → BLOCK (SLVERR + 0xBADCAB1E); write to
    LOCKS and write to JTAG_PUBLIC_IDENTITY → BLOCK (SLVERR)
  * JTAG_PUBLIC_IDENTITY read, first and last word → ALLOW (resp=OKAY with the
    word the sensed image holds there; timeout fails)
  * TEST_DEV control: LOCKS and the first identity word read OKAY as the sensed
    words, so neither refused write landed; then the same LOCKS write that PROD
    refused completes OKAY and reads back, so a JTAG write to LOCKS does land
    when the state allows it

Every JTAG-side access waits for fuse sense first: until sense completes the
shadow window answers SLVERR / 0xBADCAB1E to allowed and blocked requests
alike, and an allow verdict taken then would not be the DUT's decision.

The leaf senses its own image (``smc_efuse_jtag_lc_image``): every lock clear
and a known identity word. A read-locked identity window would answer SLVERR
with 0xBADCAB1E for the lock, the same response as the lifecycle gate, so the
exception could not be told from the block.

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
from seq_lib.smc_addr_map import smc_addr, smc_indexed_addr
from seq_lib.smc_base_test_seq import wait_fuse_sense_done
from seq_lib.smc_efuse_jtag_lc_negative_test_seq import (
    SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY,
    SMC_EFUSE_MAP_LOCKS,
    smc_efuse_jtag_lc_negative_test_seq,
)
from seq_lib.smc_jtag_vip_utils import check_cpu_jtag_pin_vip
from smc_base_test import smc_base_test
from smc_efuse_jtag_lc_image import word_index, write_unlocked_image

BLOCK_SIGNATURE = 0xBADCAB1E
#: Data of every JTAG write; LOCKS is set-only, so from the sensed 0 it reads back as written.
WRITE_PATTERN = 0xA5A5_5A5A
# The map words on either side of the JTAG_PUBLIC_IDENTITY window: the high LOCKS word
# below it and the first I2C_I3C_ID word above it (generated map).
SMC_EFUSE_MAP_LOCKS_HI = smc_addr("SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR") + 4
SMC_EFUSE_MAP_I2C_I3C_ID0 = smc_indexed_addr("SMC_TOP_SMC_EFUSE_MAP_I2C_I3C_ID_BASE_ADDR", 0)
# Last 32-bit word of the JTAG_PUBLIC_IDENTITY window: the word before the next
# region of the generated map.
SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY_LAST = (
    smc_indexed_addr("SMC_TOP_SMC_EFUSE_MAP_I2C_I3C_ID_BASE_ADDR", 0) - 4
)
LC_PROD = 0x1
# Non-restricted lifecycle state, the positive control for the PROD block.
LC_TEST_DEV = 0x0
RESP_OKAY = 0
RESP_SLVERR = 2


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
        "CHK-EFUSE-JTAG-LC-NEG",
    )
    min_evidence = 4

    auto_protocol_vip = False

    run_written_file_plusargs = ("smc_efuse_hex",)

    def build_phase(self) -> None:
        super().build_phase()
        self.image = write_unlocked_image()

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
            "PROD",
            "JTAG_PUBLIC_IDENTITY",
            SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY,
            expect_block=False,
            expect_data=self._sensed(SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY),
        )
        await self._check_read(
            "PROD",
            "JTAG_PUBLIC_IDENTITY_LAST",
            SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY_LAST,
            expect_block=False,
            expect_data=self._sensed(SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY_LAST),
        )
        # The words on either side of the window stay blocked: the exception
        # covers the identity window and nothing next to it.
        await self._check_read("PROD", "LOCKS_HI", SMC_EFUSE_MAP_LOCKS_HI, expect_block=True)
        await self._check_read("PROD", "I2C_I3C_ID0", SMC_EFUSE_MAP_I2C_I3C_ID0, expect_block=True)
        await self._check_write("PROD", "NON_ID", SMC_EFUSE_MAP_LOCKS, expect_block=True)
        # architecture.adoc:363: no write exception for the identity window.
        await self._check_write(
            "PROD", "JTAG_PUBLIC_IDENTITY", SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY, expect_block=True
        )

        # Positive control on the same address, with only the lifecycle state
        # changed: an SLVERR from a wedged JTAG path, or from an address the
        # shadow window refuses in every lifecycle state, satisfies the PROD legs
        # too. Sense has completed, so the allowed read completes OKAY at the eFuse
        # controller.
        dut.tb_lc_state.value = pack_lc_state(LC_TEST_DEV)
        await ClockCycles(dut.clk_smc_i, 20)
        dev_rdata, dev_code = await self._read(SMC_EFUSE_MAP_LOCKS)
        if dev_code is None:
            self.errors.append("[TEST_DEV] NON_ID read TIMEOUT")
        elif dev_code != RESP_OKAY:
            self.errors.append(
                f"[TEST_DEV] NON_ID read @0x{SMC_EFUSE_MAP_LOCKS:08x} expected ALLOW "
                f"(resp=OKAY) once the lifecycle state moved, got resp={dev_code}; the "
                f"PROD block above is then not attributable to the lifecycle state"
            )
        elif dev_rdata != self._sensed(SMC_EFUSE_MAP_LOCKS):
            # LOCKS is set-only, so a refused write that nevertheless landed
            # would show as set bits over the sensed 0.
            self.errors.append(
                f"[TEST_DEV] NON_ID read @0x{SMC_EFUSE_MAP_LOCKS:08x} completed OKAY but "
                f"data 0x{dev_rdata:08x} != sensed LOCKS word "
                f"0x{self._sensed(SMC_EFUSE_MAP_LOCKS):08x}; the write "
                f"PROD refused has landed"
            )
        else:
            self.checks += 1
            self.logger.info(
                "JTAG eFuse read  [TEST_DEV] NON_ID @0x%08x -> resp=OKAY rdata=0x%08x: the "
                "same address that PROD blocked completes once the lifecycle state moves, "
                "and the refused write did not land",
                SMC_EFUSE_MAP_LOCKS,
                dev_rdata,
            )
        # The identity word PROD refused to write still holds the sensed word.
        await self._check_read(
            "TEST_DEV",
            "JTAG_PUBLIC_IDENTITY",
            SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY,
            expect_block=False,
            expect_data=self._sensed(SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY),
        )
        # Live control for "did not land": the same write to LOCKS completes
        # OKAY in TEST_DEV and, LOCKS being set-only over the sensed 0, reads
        # back as written; a JTAG write to LOCKS that never commits would make
        # the PROD readback above insensitive to the gate.
        await self._check_write("TEST_DEV", "NON_ID", SMC_EFUSE_MAP_LOCKS, expect_block=False)
        await self._check_read(
            "TEST_DEV", "NON_ID", SMC_EFUSE_MAP_LOCKS, expect_block=False, expect_data=WRITE_PATTERN
        )
        dut.tb_lc_state.value = packed
        await ClockCycles(dut.clk_smc_i, 20)

        # Secondary: CHIP_CONFIG mirror must match the driven packed state.
        lc_seq = _LcStateExactSeq("lc_state_exact", expected=packed)
        await self.start_seq(lc_seq, self.env.sys_axi_agent.sequencer)

        assert not self.errors, "eFuse JTAG LC negative mismatch:\n" + "\n".join(self.errors)
        self.logger.info(
            "CHK-EFUSE-JTAG-LC-NEG: under PROD the LOCKS, LOCKS_HI and I2C_I3C_ID0 reads "
            "completed SLVERR with 0x%08x, the writes to LOCKS and to JTAG_PUBLIC_IDENTITY "
            "completed SLVERR, and the first and the last JTAG_PUBLIC_IDENTITY word read "
            "OKAY with the sensed words 0x%08x and 0x%08x; under TEST_DEV LOCKS and the "
            "first identity word read OKAY with the sensed words, and the LOCKS write of "
            "0x%08x completed OKAY and read back",
            BLOCK_SIGNATURE,
            self._sensed(SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY),
            self._sensed(SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY_LAST),
            WRITE_PATTERN,
        )

        await check_cpu_jtag_pin_vip()
        await self.record_protocol_vip(
            SmcProtocolVipKind.JTAG,
            type(self).__name__,
            # Directed stimulus floor: the seven PROD legs, the four TEST_DEV
            # control accesses, and the LC-state CSR read. Literal here, not
            # read from the sequence counters.
            min_csr_accesses=12,
            csr_accesses=self.checks + lc_seq.accesses,
            proxy=False,
            details=(
                "PROD JTAG eFuse: LOCKS, LOCKS_HI and I2C_I3C_ID0 reads BLOCK "
                "(SLVERR+0xBADCAB1E), LOCKS and JTAG_PUBLIC_IDENTITY writes BLOCK (SLVERR); "
                "JTAG_PUBLIC_IDENTITY first and last word ALLOW via resp=OKAY with the sensed "
                "words after fuse sense, on an image with every lock clear; TEST_DEV LOCKS "
                "and identity read OKAY with the sensed words, LOCKS write OKAY and read "
                "back; "
                "CHIP_CONFIG_LC_STATE exact; CPU JTAG pins checked"
            ),
        )

    def _sensed(self, addr: int) -> int:
        """The word the leaf's image holds at ``addr``."""
        return self.image.words[word_index(addr)]

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

    async def _check_read(
        self,
        label: str,
        cls: str,
        addr: int,
        *,
        expect_block: bool,
        expect_data: int | None = None,
    ) -> None:
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
        blocked = code == RESP_SLVERR
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
                    f"(SLVERR) but got resp={code} rdata=0x{rdata:08x}"
                )
            elif rdata != BLOCK_SIGNATURE:
                self.errors.append(
                    f"[{label}] {cls} read @0x{addr:08x} blocked but data "
                    f"0x{rdata:08x} != err-slv signature "
                    f"0x{BLOCK_SIGNATURE:08x}"
                )
            return
        # ALLOW is the access reaching the eFuse controller and completing
        # OKAY with the word the sensed image holds there (or the word just
        # written), which the lock sentinel and a stuck data path cannot produce.
        if code != RESP_OKAY:
            self.errors.append(
                f"[{label}] {cls} read @0x{addr:08x} expected ALLOW "
                f"(resp=OKAY) but got resp={code} rdata=0x{rdata:08x}"
            )
        elif expect_data is not None and rdata != expect_data:
            self.errors.append(
                f"[{label}] {cls} read @0x{addr:08x} completed OKAY but data "
                f"0x{rdata:08x} != expected word 0x{expect_data:08x}"
            )
        else:
            self.logger.info(
                "JTAG eFuse ALLOW [%s] %s @0x%08x resp=OKAY rdata=0x%08x",
                label,
                cls,
                addr,
                rdata,
            )

    async def _check_write(self, label: str, cls: str, addr: int, *, expect_block: bool) -> None:
        code = await self._write(addr, WRITE_PATTERN)
        if code is None:
            self.errors.append(
                f"[{label}] write @0x{addr:08x} TIMEOUT (expect_block={expect_block})"
            )
            return
        self.checks += 1
        blocked = code == RESP_SLVERR
        self.logger.info(
            "JTAG eFuse write [%s] %s @0x%08x -> resp=%s blocked=%s (exp_block=%s)",
            label,
            cls,
            addr,
            code,
            blocked,
            expect_block,
        )
        if expect_block and not blocked:
            self.errors.append(
                f"[{label}] {cls} write @0x{addr:08x} expected BLOCK (SLVERR) but got resp={code}"
            )
        elif not expect_block and blocked:
            self.errors.append(
                f"[{label}] {cls} write @0x{addr:08x} expected ALLOW but was blocked"
            )


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
