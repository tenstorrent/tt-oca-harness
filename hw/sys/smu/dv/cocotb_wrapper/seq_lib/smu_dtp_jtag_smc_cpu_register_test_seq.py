# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC CPU_CTRL SCRATCH_15 via fabric JTAG2AXI (SEP=1, no Force).

S1: After TCK sync, ``tb_smc_jtag2axi_security_disable`` is 0.
S2: DEBUG_CONTROL boot_stall=1 / ovrd=1 so ROM cannot race the mailbox.
S3: SINGLE_OP 32b write/readback of SCRATCH_15 with two distinct patterns.
    SCRATCH_0 is the live boot ROM PASS mailbox; do not use it.

Addresses from ``smc_addr.h``. No Force.

Not claimed: SPM; series modes; Force-closed gate; OTP J2A.
"""

from __future__ import annotations

import cocotb
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_indexed_addr
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    DTP_EXPECTED_SMC_JTAG2AXI_CAPS,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    pack_debug_control,
    require_jtag_tdo_resolved,
)

SCRATCH_15 = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", 15)
PATTERNS = (0xDEAD_BEEF, 0x1234_5678)
OTP_POLL = 128


class smu_dtp_jtag_smc_cpu_register_test_seq:
    """CPU_CTRL SCRATCH_15 two-pattern R/W; gate open on the SEP=1 wrapper."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.s1_ok = False
        self.s2_ok = False
        self.s3_ok = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _sample_int(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on OSS tb_top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val)

    async def _wr32(self, jtag, addr: int, data: int) -> None:
        st, _ = await jtag2axi_single_write(
            jtag,
            addr,
            data,
            wstrb=0x0F,
            size=SMC_DBG_AXSIZE_4B,
            poll_limit=OTP_POLL,
            require_complete=True,
        )
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"J2A WR32 SCRATCH_15 @0x{addr:08x} status={st} want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        self._log(f"J2A WR32 SCRATCH_15 @0x{addr:08x} data=0x{data:08x} status=SUCCESS")

    async def _rd32(self, jtag, addr: int) -> int:
        st, rdata = await jtag2axi_single_read(
            jtag,
            addr,
            size=SMC_DBG_AXSIZE_4B,
            poll_limit=OTP_POLL,
            require_complete=True,
        )
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"J2A RD32 SCRATCH_15 @0x{addr:08x} status={st} want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        return int(rdata) & 0xFFFF_FFFF

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        jtag = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)

        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        sb.expect_eq("CHK-CPU-REG-JTAG-READY", idcode, DTP_DEFAULT_IDCODE)

        gate = self._sample_int("tb_smc_jtag2axi_security_disable") & 1
        if gate != 0:
            raise AssertionError(f"SMC J2A still gated after TCK sync: security_disable={gate}")
        caps = int(await jtag.read("SMC_JTAG2AXI_CAPS")) & ((1 << 14) - 1)
        require_jtag_tdo_resolved("SMC J2A CAPS")
        if caps != DTP_EXPECTED_SMC_JTAG2AXI_CAPS:
            raise AssertionError(
                f"SMC J2A CAPS=0x{caps:04x} want 0x{DTP_EXPECTED_SMC_JTAG2AXI_CAPS:04x}"
            )
        self.s1_ok = True
        self._log(f"CHK-CPU-REG-GATE-OPEN disable={gate} caps=0x{caps:04x}")
        sb.expect_eq(
            "CHK-CPU-REG-GATE-OPEN",
            (gate, caps),
            (0, DTP_EXPECTED_SMC_JTAG2AXI_CAPS),
        )

        stall = pack_debug_control(boot_stall=1, boot_stall_ovrd=1)
        await jtag.write("DEBUG_CONTROL", stall)
        require_jtag_tdo_resolved("DEBUG_CONTROL stall")
        rb = int(await jtag.read("DEBUG_CONTROL", shift_value=stall)) & 0x1F
        if rb != stall:
            raise AssertionError(f"DEBUG_CONTROL readback=0x{rb:02x} want 0x{stall:02x}")
        self.s2_ok = True
        self._log(f"CHK-CPU-REG-STALL DEBUG_CONTROL=0x{rb:02x} boot_stall=1 boot_stall_ovrd=1")
        sb.expect_eq("CHK-CPU-REG-STALL", rb, stall, evidence="CPU_REG_STALL")

        observed = []
        for pat in PATTERNS:
            await self._wr32(jtag, SCRATCH_15, pat)
            got = await self._rd32(jtag, SCRATCH_15)
            if got != pat:
                raise AssertionError(f"SCRATCH_15 want 0x{pat:08x} got 0x{got:08x}")
            observed.append(got)
            self._log(f"CHK-JTAG2AXI-RW @0x{SCRATCH_15:08x} data=0x{got:08x}")
        if observed[0] == observed[1]:
            raise AssertionError(
                f"SCRATCH_15 two-pattern compare collapsed to one value 0x{observed[0]:08x}"
            )
        self.s3_ok = True
        sb.expect_eq("CHK-JTAG2AXI-RW", tuple(observed), PATTERNS, evidence="JTAG2AXI_RW_OK")

        self._log(
            f"PASS DTP-JTAG-SMC-CPU-REGISTER s1={self.s1_ok} s2={self.s2_ok} "
            f"s3={self.s3_ok} scratch=0x{SCRATCH_15:08x} "
            f"p0=0x{observed[0]:08x} p1=0x{observed[1]:08x}"
        )
