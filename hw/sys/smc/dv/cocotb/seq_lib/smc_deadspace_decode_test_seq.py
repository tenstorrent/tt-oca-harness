# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Prove whether SMC register windows alias unmapped offsets onto live CSRs.

Related: GitHub #214 / QUAS-4750 (undefined-space aliasing) and SEP #228.
Golden legality is PeakRDL ``SIZE`` from ``smc_addr.h``, never the xbar window.
A dead write that wraps onto a live register is the defect under test.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb

from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

AXI_RESP_OKAY = 0
PAYLOAD = 0xA5A5A5A5
PAYLOAD_ZERO = 0x00000000
_RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR", None: "none"}


@dataclass(frozen=True)
class DeadspaceProbe:
    """One wrap candidate: ``dead_addr = live_addr + wrap_period``."""

    name: str
    live_addr: int
    wrap_period: int
    # I2C wrap range-checks SIZE; this probe should REFUSE if that decode holds.
    expect_refuse: bool = False

    @property
    def dead_addr(self) -> int:
        return self.live_addr + self.wrap_period


def _probes() -> tuple[DeadspaceProbe, ...]:
    return (
        DeadspaceProbe(
            "reset_unit_sync",
            smc_addr("SMC_TOP_SMC_RESET_UNIT_SYNC_REG_BASE_ADDR"),
            0x100,
        ),
        DeadspaceProbe(
            "system_timer_preset_lo",
            smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_LO_BASE_ADDR"),
            0x40,
        ),
        DeadspaceProbe(
            "base_config_hang_det_timeout",
            smc_addr(
                "SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SYS_AXI_TIMEOUT_THRESHOLD_BASE_ADDR"
            ),
            0x80,
        ),
        DeadspaceProbe(
            "outbound_filter0_start",
            smc_indexed_addr(
                "SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR", 0
            ),
            0x200,
        ),
        DeadspaceProbe(
            "alias_remap0_region_end",
            smc_indexed_addr(
                "SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_END_BASE_ADDR", 0
            ),
            0x100,
        ),
        DeadspaceProbe(
            "dfx_debug_ctrl",
            smc_addr("SMC_TOP_DFX_CTRL_DEBUG_CTRL_BASE_ADDR"),
            0x20,
        ),
        DeadspaceProbe(
            "avsbus_cfg0",
            smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_CFG_0_BASE_ADDR"),
            0x80,
        ),
        DeadspaceProbe(
            "zeroer_dest",
            smc_addr("SMC_TOP_ZEROER_CTRL_DEST_ADDR_BASE_ADDR"),
            0x20,
        ),
        DeadspaceProbe(
            "i2c0_intr_enable",
            smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR", 0),
            0x100,
            expect_refuse=True,
        ),
    )


class smc_deadspace_decode_test_seq(SmcCsrSeq):
    """Sweep wrap-period offsets past PeakRDL SIZE and watch live CSRs."""

    def __init__(self, name: str = "smc_deadspace_decode_test_seq") -> None:
        super().__init__(name)
        self.wrap_to_live: list[str] = []
        self.accepted_dead: list[str] = []
        self.refused: list[str] = []
        self.read_alias: list[str] = []

    async def _xfer(
        self,
        name: str,
        op: SmcSysAxiOp,
        addr: int,
        data: int = 0,
    ) -> SmcSysAxiItem:
        item = SmcSysAxiItem(name)
        item.op = op
        item.addr = addr
        item.length = 4
        item.wdata = data
        item.allow_error = True
        item.allow_timeout = False
        item.timeout_ns = 2000
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert not item.timed_out, (
            f"{name} @ 0x{addr:08x}: timed out (deadspace probe must complete)"
        )
        return item

    def _arm_monitor(self, probes: tuple[DeadspaceProbe, ...]) -> None:
        monitor = getattr(getattr(self, "env", None), "axi_monitor", None)
        if monitor is None:
            return
        monitor.expected_decerr_addrs.update(p.dead_addr for p in probes)

    def _log_proof(self, kind: str, probe: DeadspaceProbe, **fields: object) -> None:
        extra = " ".join(f"{k}={v}" for k, v in fields.items())
        cocotb.log.info(
            "DEADSPACE %s: %s live=0x%08x dead=0x%08x period=0x%x %s",
            kind,
            probe.name,
            probe.live_addr,
            probe.dead_addr,
            probe.wrap_period,
            extra,
        )

    async def _probe_one(self, probe: DeadspaceProbe) -> None:
        live_rd = await self._xfer(
            f"{probe.name}_live_rd", SmcSysAxiOp.READ, probe.live_addr
        )
        assert live_rd.resp_code == AXI_RESP_OKAY, (
            f"{probe.name}: live CSR 0x{probe.live_addr:08x} resp="
            f"{_RESP_NAME.get(live_rd.resp_code)} (block is not awake)"
        )
        before = live_rd.rdata & 0xFFFFFFFF

        dead_rd = await self._xfer(
            f"{probe.name}_dead_rd", SmcSysAxiOp.READ, probe.dead_addr
        )
        dead_rd_resp = _RESP_NAME.get(dead_rd.resp_code)
        if (
            dead_rd.resp_code == AXI_RESP_OKAY
            and (dead_rd.rdata & 0xFFFFFFFF) == before
            and before != 0
        ):
            proof = (
                f"{probe.name} dead 0x{probe.dead_addr:08x} read 0x{before:08x} "
                f"matching live 0x{probe.live_addr:08x} (resp OKAY)"
            )
            self.read_alias.append(proof)
            self._log_proof("READ-ALIAS", probe, rdata=f"0x{before:08x}")

        for payload in (PAYLOAD, PAYLOAD_ZERO):
            dead_wr = await self._xfer(
                f"{probe.name}_dead_wr_{payload:08x}",
                SmcSysAxiOp.WRITE,
                probe.dead_addr,
                payload,
            )
            wr_resp = _RESP_NAME.get(dead_wr.resp_code)
            after_rd = await self._xfer(
                f"{probe.name}_live_after_{payload:08x}",
                SmcSysAxiOp.READ,
                probe.live_addr,
            )
            after = after_rd.rdata & 0xFFFFFFFF
            if after != before:
                proof = (
                    f"{probe.name} dead 0x{probe.dead_addr:08x} wrote "
                    f"0x{payload:08x} resp={wr_resp} and CHANGED live "
                    f"0x{probe.live_addr:08x}: 0x{before:08x} -> 0x{after:08x}"
                )
                self.wrap_to_live.append(proof)
                self._log_proof(
                    "WRAP-TO-LIVE",
                    probe,
                    payload=f"0x{payload:08x}",
                    wr_resp=wr_resp,
                    before=f"0x{before:08x}",
                    after=f"0x{after:08x}",
                )
                restore = await self._xfer(
                    f"{probe.name}_restore",
                    SmcSysAxiOp.WRITE,
                    probe.live_addr,
                    before,
                )
                assert restore.resp_code == AXI_RESP_OKAY, (
                    f"{probe.name}: failed to restore live CSR after wrap"
                )
                return
            if dead_wr.resp_code == AXI_RESP_OKAY:
                proof = (
                    f"{probe.name} dead 0x{probe.dead_addr:08x} wrote "
                    f"0x{payload:08x} resp=OKAY (no live change)"
                )
                self.accepted_dead.append(proof)
                self._log_proof(
                    "ACCEPTED", probe, payload=f"0x{payload:08x}", wr_resp=wr_resp
                )
                return
            if payload == PAYLOAD_ZERO:
                proof = (
                    f"{probe.name} dead 0x{probe.dead_addr:08x} "
                    f"resp={wr_resp} (no live change)"
                )
                self.refused.append(proof)
                self._log_proof("REFUSED", probe, wr_resp=wr_resp)

    async def body(self) -> None:
        probes = _probes()
        self._arm_monitor(probes)
        await self.wait_fuse_sense_done()

        sentinel = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
        await self.csr_read("ALIVE_SENTINEL_BASELINE", sentinel)

        for probe in probes:
            await self._probe_one(probe)

        await self.csr_read("ALIVE_SENTINEL_RECOVERY", sentinel)

        cocotb.log.info(
            "DEADSPACE SUMMARY: wrap_to_live=%d read_alias=%d accepted=%d refused=%d",
            len(self.wrap_to_live),
            len(self.read_alias),
            len(self.accepted_dead),
            len(self.refused),
        )
        for line in self.wrap_to_live:
            cocotb.log.error("DEADSPACE PROOF WRAP-TO-LIVE: %s", line)
        for line in self.read_alias:
            cocotb.log.error("DEADSPACE PROOF READ-ALIAS: %s", line)

        i2c = next(p for p in probes if p.expect_refuse)
        i2c_refused = any(i2c.name in row for row in self.refused)
        i2c_wrapped = any(i2c.name in row for row in self.wrap_to_live)
        i2c_accepted = any(i2c.name in row for row in self.accepted_dead)
        if i2c_wrapped:
            cocotb.log.error(
                "DEADSPACE I2C wrap still aliases; i2c_wrap SIZE check did not hold"
            )
        elif i2c_refused:
            cocotb.log.info(
                "DEADSPACE I2C: 0x%08x refused (i2c_wrap range-check held)",
                i2c.dead_addr,
            )

        assert not self.wrap_to_live and not self.read_alias, (
            "SMC deadspace aliased live registers "
            f"(wrap_to_live={len(self.wrap_to_live)} "
            f"read_alias={len(self.read_alias)}): "
            + " | ".join(self.wrap_to_live + self.read_alias)
        )
        assert i2c_refused and not i2c_accepted and not i2c_wrapped, (
            "SMC deadspace expect_refuse probe did not refuse "
            f"(refused={i2c_refused} accepted={i2c_accepted} wrapped={i2c_wrapped})"
        )
