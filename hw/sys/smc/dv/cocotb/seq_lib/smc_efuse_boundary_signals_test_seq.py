# SPDX-License-Identifier: Apache-2.0
"""eFuse reset_n = sense && rst_ni && ext_boot_seq_done_i; fuse_reset_n is 16-stage. Requires +smc_hold_ext_boot. No Force."""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

LOCKS = smc_addr("SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR")
LOCKS_PRELOAD = 0xA5A55A5A
PROG_IF_RD = smc_addr(
    "SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_INTERFACE_READ_DATA_BASE_ADDR"
)
SCRATCH_COLD_WARM_0 = smc_addr(
    "SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR"
)
# 16-stage fuse_reset_n pipe + margin. Stay-low after sense must cover this
# or a released ext_boot would already have raised tb_fuse_reset_n.
_PIPE_STAY = 24
_SENSE_BOUND = 200_000
_RELEASE_BOUND = 256


class smc_efuse_boundary_signals_test_seq(SmcCsrSeq):
    """ext_boot hold keeps fuse_reset_n low after sense; release raises it."""

    def __init__(self, name: str = "smc_efuse_boundary_signals_test_seq") -> None:
        super().__init__(name)
        self.hold_ok = False
        self.map_ok = False
        self.release_ok = False

    async def body(self) -> None:
        dut = cocotb.top
        clk = dut.clk_smc_i
        assert hasattr(dut, "tb_hold_ext_boot"), "tb_hold_ext_boot missing"
        assert int(dut.tb_hold_ext_boot.value) == 1, (
            "+smc_hold_ext_boot required so ext_boot_seq_done stays 0 from t=0"
        )

        last_sense = last_frst = None
        for cycle in range(_SENSE_BOUND):
            await RisingEdge(clk)
            last_sense = int(dut.tb_fuse_sense_done.value)
            last_frst = int(dut.tb_fuse_reset_n.value)
            if last_frst != 0:
                raise AssertionError(
                    f"HOLD: tb_fuse_reset_n rose at cycle {cycle} while "
                    f"ext_boot held (sense={last_sense})"
                )
            if last_sense == 1:
                break
        else:
            raise AssertionError(
                f"HOLD: tb_fuse_sense_done never rose in {_SENSE_BOUND} clocks "
                f"last_sense={last_sense} last_frst={last_frst}"
            )
        self.hold_ok = True
        cocotb.log.info(
            "CHK-EFUSE-BND-HOLD: sense=1 fuse_reset_n=0 hold_ext_boot=1"
        )

        for cycle in range(_PIPE_STAY):
            await RisingEdge(clk)
            if int(dut.tb_fuse_sense_done.value) != 1:
                raise AssertionError(f"STAY: sense dropped at cycle {cycle}")
            if int(dut.tb_fuse_reset_n.value) != 0:
                raise AssertionError(
                    f"STAY: fuse_reset_n rose at cycle {cycle} "
                    f"(pipe would only rise if ext_boot were 1)"
                )
        cocotb.log.info(
            "CHK-EFUSE-BND-STAY: fuse_reset_n stayed 0 for %d clocks after sense",
            _PIPE_STAY,
        )

        locks = await self.csr_read("EFUSE_MAP_LOCKS_HELD", LOCKS, expected=LOCKS_PRELOAD)
        self.map_ok = True
        cocotb.log.info(
            "CHK-EFUSE-BND-MAP: LOCKS=0x%x after sense while fuse_reset_n=0",
            locks,
        )

        dut.tb_hold_ext_boot.value = 0
        last_frst = None
        for _ in range(_RELEASE_BOUND):
            await RisingEdge(clk)
            last_frst = int(dut.tb_fuse_reset_n.value)
            if last_frst == 1:
                break
        else:
            raise AssertionError(
                f"RELEASE: tb_fuse_reset_n stayed 0 after ext_boot release "
                f"last={last_frst} bound={_RELEASE_BOUND}"
            )
        if hasattr(dut, "tb_rst_warm_smc_clk_n"):
            last_warm = None
            for _ in range(_RELEASE_BOUND):
                await RisingEdge(clk)
                last_warm = int(dut.tb_rst_warm_smc_clk_n.value)
                if last_warm == 1:
                    break
            else:
                raise AssertionError(
                    f"RELEASE: tb_rst_warm_smc_clk_n stayed 0 last={last_warm}"
                )

        prog = await self.csr_read("EFUSE_PROG_IF_RD", PROG_IF_RD)
        warm = await self.csr_read(
            "SCRATCH_COLD_WARM_0", SCRATCH_COLD_WARM_0, expected=0
        )
        self.release_ok = True
        cocotb.log.info(
            "CHK-EFUSE-BND-REL: fuse_reset_n=1 PROG_IF=0x%x COLD_WARM=0x%x",
            prog,
            warm,
        )
        cocotb.log.info(
            "CHK-EFUSE-BND-BASIC: hold=%s map=%s release=%s",
            self.hold_ok,
            self.map_ok,
            self.release_ok,
        )
