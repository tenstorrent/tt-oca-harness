# SPDX-License-Identifier: Apache-2.0
"""JTAG2AXI error and error-path security scenarios for GH issue #3212."""

from __future__ import annotations

from env.dtp_types import DtpJtag2AxiOp, DtpJtag2AxiStatus, pack_single_op

from .dtp_jtag2axi_base_test_seq import dtp_jtag2axi_base_test_seq

AXI_SLVERR = 2
AXI_DECERR = 3
ERROR_RESPONSES = (AXI_SLVERR, AXI_DECERR)
ERROR_BASE = 0x1800
RECOVERY_BASE = 0x2800


class dtp_jtag2axi_error_test_seq(dtp_jtag2axi_base_test_seq):
    """Run one target-specific JTAG2AXI negative scenario."""

    def __init__(
        self,
        name: str = "dtp_jtag2axi_error_test_seq",
        *,
        target: str = "smc_axi",
        scenario: str = "error_single_write",
        scenario_seed: int | None = None,
        random_count: int = 5,
    ) -> None:
        super().__init__(name, scenario_seed=scenario_seed, random_count=random_count)
        self.target = target
        self.scenario = scenario
        self.status = DtpJtag2AxiStatus.SUCCESS
        self.operation_count = 0

    def _addr(self, base: int, idx: int) -> int:
        cfg = self.target_cfg(self.target)
        return base + idx * max(cfg.beat_bytes, 0x20)

    def _emit_error_nonvacuity(self, label: str) -> None:
        """CHK-AXI-NONVAC: every armed SLVERR/DECERR was consumed by a real
        bus response and each injection was followed by an OKAY recovery.

        An always-OKAY, tied-off, or wedged bridge cannot satisfy this: the
        armed credits would stay unconsumed (also failing CHK-AXI-CREDITS)
        or the recovery accesses would not complete.
        """
        scoreboard = self.axi_scoreboard
        if scoreboard is None:
            return
        unconsumed = scoreboard.unconsumed_credits()
        scoreboard.expect_nonvacuous(
            self.operation_count >= len(ERROR_RESPONSES) and unconsumed == 0,
            context=(
                f"scenario={label} target={self.target} "
                f"injections={self.operation_count} resp_set=SLVERR+DECERR "
                f"credits_unconsumed={unconsumed}"
            ),
        )

    async def _expect_error_write(self, addr: int, data: int, resp: int, context: str) -> None:
        expected = self.configure_target_error(self.target, addr, resp, read=False, write=True)
        before = self.read_target_mem_int(self.target, addr, self.target_cfg(self.target).default_size)
        status, _ = await self.write_target_single_expect_status(
            self.target,
            addr,
            data,
            expected,
            context=context,
        )
        self.status = DtpJtag2AxiStatus(status)
        # OTP AXI-Lite fault RAM suppresses failed writes. The SMC fabric legacy
        # responder reports the error after accepting data, so recovery is the
        # portable side-effect check for that target.
        if self.target != "smc_axi":
            after = self.read_target_mem_int(self.target, addr, self.target_cfg(self.target).default_size)
            self.assert_equal(f"{context}.no_write_side_effect", after, before)
        await self.verify_target_recovery(
            self.target,
            addr=addr + 0x400,
            data=data ^ 0x55AA_55AA_55AA_55AA,
            read=False,
            context=context,
        )
        self.operation_count += 1

    async def _expect_error_read(self, addr: int, data: int, resp: int, context: str) -> None:
        size = self.target_cfg(self.target).default_size
        self.write_target_mem_int(self.target, addr, data, size)
        expected = self.configure_target_error(self.target, addr, resp, read=True, write=False)
        status, _ = await self.read_target_single_expect_status(
            self.target,
            addr,
            expected,
            context=context,
        )
        self.status = DtpJtag2AxiStatus(status)
        await self.verify_target_recovery(
            self.target,
            addr=addr + 0x400,
            data=data ^ 0x00FF_00FF_00FF_00FF,
            read=True,
            context=context,
        )
        self.operation_count += 1

    async def run_error_single_write(self) -> None:
        self.log_banner(f"{self.target} SINGLE_OP write error")
        await self.reset_tap()
        rng = self.rng(f"{self.target}.error_single_write")
        for idx, resp in enumerate(ERROR_RESPONSES, start=1):
            addr = self._addr(ERROR_BASE, idx)
            data = rng.getrandbits(self.target_cfg(self.target).data_width)
            self.log_iteration(idx, len(ERROR_RESPONSES), "write error addr=0x%08x resp=%d", addr, resp)
            await self._expect_error_write(addr, data, resp, f"single_write_error#{idx}")
        self._emit_error_nonvacuity("error_single_write")
        self.status = DtpJtag2AxiStatus.SUCCESS

    async def run_error_single_read(self) -> None:
        self.log_banner(f"{self.target} SINGLE_OP read error")
        await self.reset_tap()
        rng = self.rng(f"{self.target}.error_single_read")
        for idx, resp in enumerate(ERROR_RESPONSES, start=1):
            addr = self._addr(ERROR_BASE + 0x100, idx)
            data = rng.getrandbits(self.target_cfg(self.target).data_width)
            self.log_iteration(idx, len(ERROR_RESPONSES), "read error addr=0x%08x resp=%d", addr, resp)
            await self._expect_error_read(addr, data, resp, f"single_read_error#{idx}")
        self._emit_error_nonvacuity("error_single_read")
        self.status = DtpJtag2AxiStatus.SUCCESS

    async def run_error_series_write(self, *, increment: bool, with_status: bool) -> None:
        mode = "incr" if increment else "no_incr"
        suffix = "_with_status" if with_status else ""
        self.log_banner(f"{self.target} series {mode} write error{suffix}")
        await self.reset_tap()
        rng = self.rng(f"{self.target}.series_write_error.{mode}{suffix}")
        cfg = self.target_cfg(self.target)
        size = cfg.default_size
        stride = cfg.beat_bytes if increment else 0
        base = self._addr(ERROR_BASE + 0x300, 1)
        fault_idx = 1 if increment else 0
        resp = rng.choice(ERROR_RESPONSES)
        expected = self.configure_target_error(
            self.target,
            base + fault_idx * stride,
            resp,
            read=False,
            write=True,
        )
        await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.WRITE, base, size=size, target=self.target)
        expected_addr = base
        for idx in range(3):
            data = rng.getrandbits(cfg.data_width) & self.data_mask(size)
            before = await self.target_activity_counts(self.target)
            self.log_iteration(idx + 1, 3, "series write addr=0x%08x resp=%s", expected_addr, resp if idx == fault_idx else "OKAY")
            if with_status:
                _, status_bit = await self.series_data_with_status(
                    data,
                    size=size,
                    increment=1 if increment else 0,
                    target=self.target,
                    back_to_rti=True,
                )
                self.log.info("series write status-bit=%d", status_bit)
            elif increment:
                await self.series_data_incr(data, size=size, target=self.target, back_to_rti=True)
            else:
                await self.series_data_no_incr(data, size=size, target=self.target, back_to_rti=True)
            await self.wait_for_target_activity(
                self.target,
                before=before,
                read=False,
                context=f"series_write_error.axi#{idx}",
            )
            if idx != fault_idx and not with_status:
                observed = self.read_target_mem_int(self.target, expected_addr, size)
                self.assert_equal(f"series_write_error.mem#{idx}", observed, data)
            elif idx != fault_idx:
                observed = self.read_target_mem_int(self.target, expected_addr, size)
                self.log.info(
                    "series write status-mode beat #%d memory observation addr=0x%08x expected_if_committed=0x%x observed=0x%x",
                    idx,
                    expected_addr,
                    data,
                    observed,
                )
            else:
                _, _, _, _, status = await self.read_series_ctrl(size=size, target=self.target)
                self.log.info(
                    "series write fault beat expected=%s observed_series_ctrl=%s",
                    DtpJtag2AxiStatus(expected).name,
                    DtpJtag2AxiStatus(status).name,
                )
            expected_addr += stride
        await self.verify_target_recovery(
            self.target,
            addr=RECOVERY_BASE,
            data=0xCAFE_BABE_1234_5678,
            read=False,
            context="series_write_error",
        )
        self.status = DtpJtag2AxiStatus.SUCCESS
        self.operation_count += 3

    async def run_error_series_read(self, *, increment: bool, with_status: bool) -> None:
        mode = "incr" if increment else "no_incr"
        suffix = "_with_status" if with_status else ""
        self.log_banner(f"{self.target} series {mode} read error{suffix}")
        await self.reset_tap()
        rng = self.rng(f"{self.target}.series_read_error.{mode}{suffix}")
        cfg = self.target_cfg(self.target)
        size = cfg.default_size
        stride = cfg.beat_bytes if increment else 0
        base = self._addr(ERROR_BASE + 0x600, 1)
        fault_idx = 1 if increment else 0
        resp = rng.choice(ERROR_RESPONSES)
        expected = self.configure_target_error(
            self.target,
            base + fault_idx * stride,
            resp,
            read=True,
            write=False,
        )
        for idx in range(3):
            self.write_target_mem_int(
                self.target,
                base + idx * (cfg.beat_bytes if increment else 0),
                rng.getrandbits(cfg.data_width),
                size,
            )
        for idx in range(3):
            addr = base + idx * stride
            await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.READ, addr, size=size, target=self.target)
            before = await self.target_activity_counts(self.target)
            self.log_iteration(idx + 1, 3, "series read addr=0x%08x resp=%s", addr, resp if idx == fault_idx else "OKAY")
            if with_status:
                await self.series_data_with_status(
                    0,
                    size=size,
                    increment=1 if increment else 0,
                    target=self.target,
                    back_to_rti=True,
                )
            elif increment:
                await self.series_data_incr(0, size=size, target=self.target, back_to_rti=True)
            else:
                await self.series_data_no_incr(0, size=size, target=self.target, back_to_rti=True)
            await self.wait_for_target_activity(
                self.target,
                before=before,
                read=True,
                context=f"series_read_error.axi#{idx}",
            )
            if with_status:
                raw, status_bit = await self.series_data_with_status(
                    0,
                    size=size,
                    increment=0,
                    target=self.target,
                    back_to_rti=True,
                )
                self.log.info("series read capture raw=0x%x status-bit=%d", raw, status_bit)
            elif increment:
                await self.series_data_incr(0, size=size, target=self.target, back_to_rti=True)
            else:
                await self.series_data_no_incr(0, size=size, target=self.target, back_to_rti=True)
            if idx == fault_idx and not with_status:
                _, _, _, _, status = await self.read_series_ctrl(size=size, target=self.target)
                self.log.info(
                    "series read fault beat expected=%s observed_series_ctrl=%s",
                    DtpJtag2AxiStatus(expected).name,
                    DtpJtag2AxiStatus(status).name,
                )
        await self.verify_target_recovery(
            self.target,
            addr=RECOVERY_BASE + 0x100,
            data=0xDEAD_BEEF_7654_3210,
            read=True,
            context="series_read_error",
        )
        self.status = DtpJtag2AxiStatus.SUCCESS
        self.operation_count += 3

    async def run_error_security_gating(self) -> None:
        self.log_banner(f"{self.target} error-path security gating")
        await self.reset_tap()
        cfg = self.target_cfg(self.target)
        size = cfg.default_size
        addr = self._addr(ERROR_BASE + 0x900, 1)
        data = 0xA5A5_5A5A_C3C3_3C3C & self.data_mask(size)
        for idx, bit_name in enumerate(cfg.required_enable_bits, start=1):
            self.log_step(idx, "Gate %s with lifecycle %s and attempt error-path write", self.target, bit_name)
            await self.set_lifecycle(**{bit_name: 0})
            self.configure_target_error(self.target, addr, AXI_SLVERR, read=False, write=True)
            raw = pack_single_op(
                DtpJtag2AxiOp.WRITE,
                addr,
                data,
                wstrb=self.target_full_wstrb(self.target, size),
                size=size,
                target=cfg,
            )
            await self.write_tdr(cfg.single_op_reg, raw)
            await self.expect_no_target_activity(self.target, 8, context=f"error_gate.{bit_name}.no_axi")
            self.clear_target_errors(self.target)
            await self.clear_lifecycle()
            expected = self.configure_target_error(self.target, addr, AXI_DECERR, read=False, write=True)
            status, _ = await self.write_target_single_expect_status(
                self.target,
                addr,
                data ^ idx,
                expected,
                context=f"error_gate.{bit_name}.ungated_error",
            )
            self.assert_equal(f"error_gate.{bit_name}.ungated_status", status, expected)
            await self.verify_target_recovery(
                self.target,
                addr=addr + 0x400 + idx * cfg.beat_bytes,
                data=data ^ (idx << 4),
                read=False,
                context=f"error_gate.{bit_name}",
            )
            self.operation_count += 1
        self.status = DtpJtag2AxiStatus.SUCCESS

    async def body(self) -> None:
        await self.clear_lifecycle()
        scenarios = {
            "error_single_write": self.run_error_single_write,
            "error_single_read": self.run_error_single_read,
            "error_series_no_incr_write": lambda: self.run_error_series_write(increment=False, with_status=False),
            "error_series_no_incr_read": lambda: self.run_error_series_read(increment=False, with_status=False),
            "error_series_incr_write": lambda: self.run_error_series_write(increment=True, with_status=False),
            "error_series_incr_read": lambda: self.run_error_series_read(increment=True, with_status=False),
            "error_series_incr_write_with_status": lambda: self.run_error_series_write(increment=True, with_status=True),
            "error_series_incr_read_with_status": lambda: self.run_error_series_read(increment=True, with_status=True),
            "error_security_gating": self.run_error_security_gating,
        }
        if self.scenario not in scenarios:
            raise ValueError(f"unknown JTAG2AXI error scenario {self.scenario!r}")
        await scenarios[self.scenario]()
        self.clear_target_errors(self.target)
        self.clear_target_backpressure(self.target)
        await self.clear_lifecycle()
        self.log_summary(
            "JTAG2AXI error scenario complete",
            target=self.target,
            scenario=self.scenario,
            operations=self.operation_count,
            status=DtpJtag2AxiStatus(self.status).name,
        )
