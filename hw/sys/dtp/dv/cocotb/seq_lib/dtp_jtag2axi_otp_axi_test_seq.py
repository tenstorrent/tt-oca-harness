# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OTP AXI-Lite JTAG2AXI scenarios for GH issue #3211."""

from __future__ import annotations

from env.dtp_types import DtpJtag2AxiOp, DtpJtag2AxiStatus, pack_single_op

from .dtp_jtag2axi_base_test_seq import dtp_jtag2axi_base_test_seq

DEFAULT_OTP_ADDR = 0x80
DEFAULT_OTP_DATA = 0x0123_4567


class dtp_jtag2axi_otp_axi_test_seq(dtp_jtag2axi_base_test_seq):
    """Run one focused SMC/SEP OTP AXI-Lite JTAG2AXI scenario."""

    def __init__(
        self,
        name: str = "dtp_jtag2axi_otp_axi_test_seq",
        *,
        target: str = "smc_otp",
        scenario: str = "single_write",
        scenario_seed: int | None = None,
        random_count: int = 5,
    ) -> None:
        super().__init__(name, scenario_seed=scenario_seed, random_count=random_count)
        self.target = target
        self.scenario = scenario
        self.status = DtpJtag2AxiStatus.SUCCESS
        self.operation_count = 0

    def directed_cases(self) -> list[tuple[int, int, int, int]]:
        """Return deterministic AXI-Lite address, size, data, strobe cases."""
        cases = []
        for idx, size in enumerate((0, 1, 2)):
            addr = DEFAULT_OTP_ADDR + (idx * 0x20)
            data = (DEFAULT_OTP_DATA ^ (0x1111_1111 * idx)) & self.data_mask(size)
            cases.append((addr, size, data, self.full_wstrb(size)))
        cases.append((DEFAULT_OTP_ADDR + 0x80, 2, 0xA5A5_5A5A, 0x5))
        cases.append((DEFAULT_OTP_ADDR + 0xA0, 2, 0x5A5A_A5A5, 0xA))
        return cases

    async def run_single_write(self) -> None:
        self.log_banner(f"{self.target} SINGLE_OP Directed Write")
        await self.reset_tap()
        for idx, (addr, size, data, wstrb) in enumerate(self.directed_cases(), start=1):
            self.log_iteration(
                idx,
                len(self.directed_cases()),
                "single write addr=0x%08x size=%d data=0x%x wstrb=0x%01x",
                addr,
                size,
                data,
                wstrb,
            )
            status, _ = await self.write_target_single_and_check(
                self.target,
                addr,
                data,
                size=size,
                wstrb=wstrb,
                context=f"single_write#{idx}",
            )
            self.status = status
            self.operation_count += 1

    async def run_single_write_data_verify(self) -> None:
        self.log_banner(f"{self.target} SINGLE_OP Write With Readback")
        await self.reset_tap()
        addr = DEFAULT_OTP_ADDR + 0x100
        data = 0xD00D_F00D
        write_status, _ = await self.write_target_single_and_check(
            self.target,
            addr,
            data,
            context="write_readback.write",
        )
        read_status, rdata = await self.read_target_single_and_check(
            self.target,
            addr,
            data,
            context="write_readback.read",
        )
        self.status = read_status if read_status != DtpJtag2AxiStatus.SUCCESS else write_status
        self.operation_count += 2
        self.log.info("write_readback target=%s rdata=0x%08x", self.target, rdata)

    async def run_series_write_incr(self) -> None:
        self.log_banner(f"{self.target} SERIES_DATA_INCR Write Sweep")
        await self.reset_tap()
        rng = self.rng(f"{self.target}.series_write_incr")
        cfg = self.target_cfg(self.target)
        size = cfg.default_size
        stride = cfg.beat_bytes
        beats = max(2, min(self.random_count, 6))
        base = self.random_target_aligned_addr(self.target, rng)
        await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.WRITE, base, size=size, target=self.target)
        for idx in range(beats):
            addr = base + (idx * stride)
            data = rng.getrandbits(cfg.data_width) & self.data_mask(size)
            self.log_iteration(idx + 1, beats, "series incr write addr=0x%08x data=0x%x", addr, data)
            before = await self.target_activity_counts(self.target)
            await self.series_data_incr(data, size=size, target=self.target, back_to_rti=True)
            await self.wait_for_target_activity(
                self.target,
                before=before,
                read=False,
                context=f"series_incr.axi#{idx}",
            )
            observed = self.read_target_mem_int(self.target, addr, size)
            self.assert_equal(f"series_incr.mem#{idx}", observed, data, f"addr=0x{addr:x}")
            self.operation_count += 1
        _, addr_after, _, _, status = await self.read_series_ctrl(size=size, target=self.target)
        self.assert_equal("series_incr.status", status, DtpJtag2AxiStatus.SUCCESS)
        self.assert_equal("series_incr.addr_after", addr_after, base + (beats * stride))
        self.status = status

    async def run_series_write_no_incr(self) -> None:
        self.log_banner(f"{self.target} SERIES_DATA_NO_INCR Write Sweep")
        await self.reset_tap()
        rng = self.rng(f"{self.target}.series_write_no_incr")
        cfg = self.target_cfg(self.target)
        size = cfg.default_size
        beats = max(2, min(self.random_count, 6))
        addr = self.random_target_aligned_addr(self.target, rng)
        await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.WRITE, addr, size=size, target=self.target)
        last_data = 0
        for idx in range(beats):
            last_data = rng.getrandbits(cfg.data_width) & self.data_mask(size)
            self.log_iteration(
                idx + 1,
                beats,
                "series no-incr write addr=0x%08x data=0x%x",
                addr,
                last_data,
            )
            before = await self.target_activity_counts(self.target)
            await self.series_data_no_incr(last_data, size=size, target=self.target, back_to_rti=True)
            await self.wait_for_target_activity(
                self.target,
                before=before,
                read=False,
                context=f"series_no_incr.axi#{idx}",
            )
            observed = self.read_target_mem_int(self.target, addr, size)
            self.assert_equal(f"series_no_incr.mem#{idx}", observed, last_data)
            self.operation_count += 1
        _, addr_after, _, _, status = await self.read_series_ctrl(size=size, target=self.target)
        self.assert_equal("series_no_incr.status", status, DtpJtag2AxiStatus.SUCCESS)
        self.assert_equal("series_no_incr.addr_after", addr_after, addr)
        self.status = status

    async def run_series_write_incr_with_error(self) -> None:
        self.log_banner(f"{self.target} SERIES_DATA_WITH_ERROR_STATUS Write Mode")
        await self.reset_tap()
        rng = self.rng(f"{self.target}.series_write_with_status")
        cfg = self.target_cfg(self.target)
        size = cfg.default_size
        stride = cfg.beat_bytes
        base = self.random_target_aligned_addr(self.target, rng)
        increments = [1, 0, 1, 1]
        await self.jtag2axi_series_ctrl(
            DtpJtag2AxiOp.WRITE,
            base,
            size=size,
            target=self.target,
            back_to_rti=True,
        )
        expected_addr = base
        for idx, inc in enumerate(increments, start=1):
            data = rng.getrandbits(cfg.data_width) & self.data_mask(size)
            self.log_iteration(idx, len(increments), "status write addr=0x%08x inc=%d", expected_addr, inc)
            before = await self.target_activity_counts(self.target)
            _, status_bit = await self.series_data_with_status(
                data,
                size=size,
                increment=inc,
                target=self.target,
                back_to_rti=True,
            )
            await self.wait_for_target_activity(
                self.target,
                before=before,
                read=False,
                context=f"series_status.axi#{idx}",
            )
            self.assert_equal(f"series_status.status_bit#{idx}", status_bit, 0)
            observed = self.read_target_mem_int(self.target, expected_addr, size)
            self.assert_equal(f"series_status.mem#{idx}", observed, data)
            expected_addr += stride if inc else 0
            self.operation_count += 1
        _, addr_after, _, _, status = await self.read_series_ctrl(size=size, target=self.target)
        self.assert_equal("series_status.status", status, DtpJtag2AxiStatus.SUCCESS)
        self.assert_equal("series_status.addr_after", addr_after, expected_addr)
        self.status = status

    async def run_random_ops(self) -> None:
        self.log_banner(f"{self.target} SINGLE_OP Randomized Writes")
        await self.reset_tap()
        rng = self.rng(f"{self.target}.random_write_ops")
        cfg = self.target_cfg(self.target)
        size = cfg.default_size
        for idx in range(1, self.random_count + 1):
            addr = self.random_target_aligned_addr(self.target, rng)
            data = rng.getrandbits(cfg.data_width) & self.data_mask(size)
            self.log_iteration(idx, self.random_count, "random write addr=0x%08x data=0x%x", addr, data)
            status, _ = await self.write_target_single_and_check(
                self.target,
                addr,
                data,
                size=size,
                wstrb=cfg.wstrb_bits and self.target_full_wstrb(self.target, size),
                context=f"random_write#{idx}",
            )
            self.status = status
            self.operation_count += 1

    async def run_write_security_gating(self) -> None:
        self.log_banner(f"{self.target} Write Security Gating")
        await self.reset_tap()
        cfg = self.target_cfg(self.target)
        size = cfg.default_size
        addr = DEFAULT_OTP_ADDR + 0x200
        data = 0xFACE_CAFE & self.data_mask(size)
        before = await self.target_activity_counts(self.target)
        await self.write_target_single_and_check(self.target, addr, data, context="gate.baseline")
        await self.expect_target_activity(
            self.target,
            before=before,
            read=False,
            context="gate.baseline",
        )
        # Two assert/release passes of the target's direct disable prove the
        # gate is repeatable, not a one-shot POR effect.
        for idx in (1, 2):
            bit_name = f"{cfg.dbg_disable_bit}_pass{idx}"
            self.log_step(idx + 1, "Gate %s write with %s (pass %d)",
                          self.target, cfg.dbg_disable_bit, idx)
            await self.disable_debug_bits(cfg.dbg_disable_bit)
            # Preload a sentinel at the gated-attempt address: the blocked
            # write must leave memory untouched, both while gated and after
            # the disable is released (a delayed replay would overwrite it).
            gate_addr = addr + (idx * cfg.beat_bytes)
            sentinel = 0x5EA1_0000 | idx
            self.write_target_mem_int(self.target, gate_addr, sentinel, size)
            raw = pack_single_op(
                DtpJtag2AxiOp.WRITE,
                gate_addr,
                data ^ idx,
                wstrb=self.target_full_wstrb(self.target, size),
                size=size,
                target=cfg,
            )
            await self.write_tdr(cfg.single_op_reg, raw)
            await self.expect_no_target_activity(self.target, 8, context=f"gate.{bit_name}.no_axi")
            self.assert_equal(
                f"gate.{bit_name}.sentinel",
                self.read_target_mem_int(self.target, gate_addr, size),
                sentinel,
            )
            await self.enable_all_debug()
            await self.wait_sys_cycles(8)
            self.assert_equal(
                f"gate.{bit_name}.sentinel_post_release",
                self.read_target_mem_int(self.target, gate_addr, size),
                sentinel,
            )
            before = await self.target_activity_counts(self.target)
            status, _ = await self.write_target_single_and_check(
                self.target,
                addr + (idx * 0x20),
                data ^ (idx << 8),
                context=f"gate.{bit_name}.restore",
            )
            await self.expect_target_activity(
                self.target,
                before=before,
                read=False,
                context=f"gate.{bit_name}.restore",
            )
            self.status = status
            self.operation_count += 1

    async def run_single_write_read(self) -> None:
        self.log_banner(f"{self.target} SINGLE_OP Single Write-Read")
        await self.reset_tap()
        addr = DEFAULT_OTP_ADDR + 0x300
        data = DEFAULT_OTP_DATA
        write_status, _ = await self.write_target_single_and_check(
            self.target,
            addr,
            data,
            context="single_wr_rd.write",
        )
        read_status, rdata = await self.read_target_single_and_check(
            self.target,
            addr,
            data,
            context="single_wr_rd.read",
        )
        self.status = read_status if read_status != DtpJtag2AxiStatus.SUCCESS else write_status
        self.operation_count += 2
        self.log.info("single_wr_rd target=%s rdata=0x%08x", self.target, rdata)

    async def _series_write_values(self, base: int, values: list[int], *, increment: bool) -> None:
        cfg = self.target_cfg(self.target)
        size = cfg.default_size
        await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.WRITE, base, size=size, target=self.target)
        for idx, data in enumerate(values):
            before = await self.target_activity_counts(self.target)
            if increment:
                await self.series_data_incr(data, size=size, target=self.target, back_to_rti=True)
            else:
                await self.series_data_no_incr(data, size=size, target=self.target, back_to_rti=True)
            await self.wait_for_target_activity(
                self.target,
                before=before,
                read=False,
                context=f"series_write_values.axi#{idx}",
            )

    async def run_series_write_read_incr(self) -> None:
        self.log_banner(f"{self.target} Series Write-Read Incrementing")
        await self.reset_tap()
        rng = self.rng(f"{self.target}.series_read_incr")
        cfg = self.target_cfg(self.target)
        size = cfg.default_size
        stride = cfg.beat_bytes
        beats = max(2, min(self.random_count, 6))
        base = self.random_target_aligned_addr(self.target, rng)
        values = [rng.getrandbits(cfg.data_width) & self.data_mask(size) for _ in range(beats)]
        await self._series_write_values(base, values, increment=True)
        for idx, exp in enumerate(values):
            addr = base + idx * stride
            await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.READ, addr, size=size, target=self.target)
            before = await self.target_activity_counts(self.target)
            await self.series_data_incr(0, size=size, target=self.target, back_to_rti=True)
            await self.wait_for_target_activity(
                self.target,
                before=before,
                read=True,
                context=f"series_wr_rd_incr.read_axi#{idx}",
            )
            raw = await self.series_data_incr(0, size=size, target=self.target, back_to_rti=True)
            obs, _ = self.unpack_series_value(raw, size)
            self.assert_equal(f"series_wr_rd_incr.rdata#{idx}", obs, exp, f"addr=0x{addr:x}")
            self.operation_count += 1
        _, _, _, _, status = await self.read_series_ctrl(size=size, target=self.target)
        self.status = status

    async def run_series_write_read_no_incr(self) -> None:
        self.log_banner(f"{self.target} Series Write-Read No-Increment")
        await self.reset_tap()
        rng = self.rng(f"{self.target}.series_read_no_incr")
        cfg = self.target_cfg(self.target)
        size = cfg.default_size
        beats = max(2, min(self.random_count, 6))
        addr = self.random_target_aligned_addr(self.target, rng)
        values = [rng.getrandbits(cfg.data_width) & self.data_mask(size) for _ in range(beats)]
        await self._series_write_values(addr, values, increment=False)
        expected = values[-1]
        for idx in range(1, beats + 1):
            await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.READ, addr, size=size, target=self.target)
            before = await self.target_activity_counts(self.target)
            await self.series_data_no_incr(0, size=size, target=self.target, back_to_rti=True)
            await self.wait_for_target_activity(
                self.target,
                before=before,
                read=True,
                context=f"series_wr_rd_no_incr.read_axi#{idx}",
            )
            raw = await self.series_data_no_incr(0, size=size, target=self.target, back_to_rti=True)
            obs, _ = self.unpack_series_value(raw, size)
            self.assert_equal(f"series_wr_rd_no_incr.rdata#{idx}", obs, expected)
            self.operation_count += 1
        _, addr_after, _, _, status = await self.read_series_ctrl(size=size, target=self.target)
        self.assert_equal("series_wr_rd_no_incr.addr_after", addr_after, addr)
        self.status = status

    async def run_series_write_read_incr_with_error(self) -> None:
        self.log_banner(f"{self.target} Series Write-Read With Error-Status Mode")
        await self.reset_tap()
        rng = self.rng(f"{self.target}.series_read_with_status")
        cfg = self.target_cfg(self.target)
        size = cfg.default_size
        stride = cfg.beat_bytes
        base = self.random_target_aligned_addr(self.target, rng)
        increments = [1, 0, 1, 1]
        expected_by_addr = {}
        addr = base
        await self.jtag2axi_series_ctrl(
            DtpJtag2AxiOp.WRITE,
            base,
            size=size,
            target=self.target,
            back_to_rti=True,
        )
        for idx, inc in enumerate(increments, start=1):
            data = rng.getrandbits(cfg.data_width) & self.data_mask(size)
            before = await self.target_activity_counts(self.target)
            await self.series_data_with_status(
                data,
                size=size,
                increment=inc,
                target=self.target,
                back_to_rti=True,
            )
            await self.wait_for_target_activity(
                self.target,
                before=before,
                read=False,
                context=f"series_wr_rd_status.write_axi#{idx}",
            )
            expected_by_addr[addr] = data
            addr += stride if inc else 0
        addr = base
        for idx, inc in enumerate(increments, start=1):
            await self.jtag2axi_series_ctrl(
                DtpJtag2AxiOp.READ,
                addr,
                size=size,
                target=self.target,
                back_to_rti=True,
            )
            before = await self.target_activity_counts(self.target)
            await self.series_data_with_status(
                0,
                size=size,
                increment=inc,
                target=self.target,
                back_to_rti=True,
            )
            await self.wait_for_target_activity(
                self.target,
                before=before,
                read=True,
                context=f"series_wr_rd_status.read_axi#{idx}",
            )
            raw_data, status_bit = await self.series_data_with_status(
                0,
                size=size,
                increment=0,
                target=self.target,
                back_to_rti=True,
            )
            self.assert_equal(f"series_wr_rd_status.status_bit#{idx}", status_bit, 0)
            self.assert_equal(f"series_wr_rd_status.rdata#{idx}", raw_data, expected_by_addr[addr])
            addr += stride if inc else 0
            self.operation_count += 1
        _, addr_after, _, _, status = await self.read_series_ctrl(size=size, target=self.target)
        self.assert_equal("series_wr_rd_status.addr_after", addr_after, addr)
        self.status = status

    async def run_read_random_ops(self) -> None:
        self.log_banner(f"{self.target} SINGLE_OP Randomized Reads")
        await self.reset_tap()
        rng = self.rng(f"{self.target}.random_read_ops")
        cfg = self.target_cfg(self.target)
        size = cfg.default_size
        for idx in range(1, self.random_count + 1):
            addr = self.random_target_aligned_addr(self.target, rng)
            data = rng.getrandbits(cfg.data_width) & self.data_mask(size)
            self.write_target_mem_int(self.target, addr, data, size)
            self.log_iteration(idx, self.random_count, "random read addr=0x%08x data=0x%x", addr, data)
            status, _ = await self.read_target_single_and_check(
                self.target,
                addr,
                data,
                size=size,
                context=f"random_read#{idx}",
            )
            self.status = status
            self.operation_count += 1

    async def run_read_security_gating(self) -> None:
        self.log_banner(f"{self.target} Read Security Gating")
        await self.reset_tap()
        cfg = self.target_cfg(self.target)
        size = cfg.default_size
        addr = DEFAULT_OTP_ADDR + 0x400
        data = 0xABCD_EF01 & self.data_mask(size)
        self.write_target_mem_int(self.target, addr, data, size)
        before = await self.target_activity_counts(self.target)
        status, _ = await self.read_target_single_and_check(
            self.target,
            addr,
            data,
            context="read_gate.baseline",
        )
        await self.expect_target_activity(
            self.target,
            before=before,
            read=True,
            context="read_gate.baseline",
        )
        self.status = status
        # Two assert/release passes of the target's direct disable prove the
        # gate is repeatable, not a one-shot POR effect.
        for idx in (1, 2):
            bit_name = f"{cfg.dbg_disable_bit}_pass{idx}"
            self.log_step(idx + 1, "Gate %s read with %s (pass %d)",
                          self.target, cfg.dbg_disable_bit, idx)
            await self.disable_debug_bits(cfg.dbg_disable_bit)
            raw = pack_single_op(DtpJtag2AxiOp.READ, addr + (idx * cfg.beat_bytes), size=size, target=cfg)
            await self.write_tdr(cfg.single_op_reg, raw)
            await self.expect_no_target_activity(self.target, 8, context=f"read_gate.{bit_name}.no_axi")
            await self.enable_all_debug()
            before = await self.target_activity_counts(self.target)
            status, _ = await self.read_target_single_and_check(
                self.target,
                addr,
                data,
                context=f"read_gate.{bit_name}.restore",
            )
            await self.expect_target_activity(
                self.target,
                before=before,
                read=True,
                context=f"read_gate.{bit_name}.restore",
            )
            self.status = status
            self.operation_count += 1

    @staticmethod
    def unpack_series_value(raw: int, size: int) -> tuple[int, int]:
        from env.dtp_types import unpack_series_data
        return unpack_series_data(raw, size)

    async def body(self) -> None:
        await self.enable_all_debug()
        scenarios = {
            "single_write": self.run_single_write,
            "single_write_data_verify": self.run_single_write_data_verify,
            "series_write_incr": self.run_series_write_incr,
            "series_write_no_incr": self.run_series_write_no_incr,
            "series_write_incr_with_error": self.run_series_write_incr_with_error,
            "random_ops": self.run_random_ops,
            "write_security_gating": self.run_write_security_gating,
            "single_write_read": self.run_single_write_read,
            "series_write_read_incr": self.run_series_write_read_incr,
            "series_write_read_no_incr": self.run_series_write_read_no_incr,
            "series_write_read_incr_with_error": self.run_series_write_read_incr_with_error,
            "read_random_ops": self.run_read_random_ops,
            "read_security_gating": self.run_read_security_gating,
        }
        if self.target not in ("smc_otp", "sep_otp"):
            raise ValueError(f"unsupported OTP JTAG2AXI target {self.target!r}")
        if self.scenario not in scenarios:
            raise ValueError(f"unknown OTP JTAG2AXI scenario {self.scenario!r}")
        await scenarios[self.scenario]()
        await self.enable_all_debug()
        self.log_summary(
            "OTP AXI-Lite JTAG2AXI scenario complete",
            target=self.target,
            scenario=self.scenario,
            operations=self.operation_count,
            status=DtpJtag2AxiStatus(self.status).name,
        )
