# SPDX-License-Identifier: Apache-2.0
"""Zeroer datapath payload check through the output-fabric responder."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles

from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_csr_seq_utils import SmcCsrSeq

# Generated PeakRDL map (hw/sys/smc/regs/gen/py/smc_reg.py).
_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    SMC_INBOUND_FILTER_CTRL_0__END_ADDR_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_0__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_0__START_ADDR_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_0__END_ADDR_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_0__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_0__START_ADDR_REG_ADDR,
    ZEROER_CTRL_CTRL_STATUS_REG_ADDR,
    ZEROER_CTRL_DEST_ADDR_REG_ADDR,
    ZEROER_CTRL_SIZE_REG_ADDR,
)

ZEROER_DEST_ADDR = ZEROER_CTRL_DEST_ADDR_REG_ADDR
ZEROER_SIZE = ZEROER_CTRL_SIZE_REG_ADDR
ZEROER_CTRL_STATUS = ZEROER_CTRL_CTRL_STATUS_REG_ADDR

INBOUND0_FILTER_CONFIG = SMC_INBOUND_FILTER_CTRL_0__FILTER_CONFIG_REG_ADDR
INBOUND0_START = SMC_INBOUND_FILTER_CTRL_0__START_ADDR_REG_ADDR
INBOUND0_END = SMC_INBOUND_FILTER_CTRL_0__END_ADDR_REG_ADDR
OUTBOUND0_FILTER_CONFIG = SMC_OUTBOUND_FILTER_CTRL_0__FILTER_CONFIG_REG_ADDR
OUTBOUND0_START = SMC_OUTBOUND_FILTER_CTRL_0__START_ADDR_REG_ADDR
OUTBOUND0_END = SMC_OUTBOUND_FILTER_CTRL_0__END_ADDR_REG_ADDR
PASS_ALL_CONFIG = 0x0100_3013

OUTPUT_FABRIC_ADDR = 0x0200_0000
OUTPUT_FABRIC_NEIGHBOUR_ADDR = OUTPUT_FABRIC_ADDR + 8
OUTPUT_FABRIC_MODEL_REGION = "zeroer_output_fabric"
OUTPUT_FABRIC_MODEL_SIZE = 0x1000
ZEROER_POISON = bytes.fromhex("a0a1a2a3a4a5a6a7")
ZEROER_NEIGHBOUR_POISON = bytes.fromhex("b0b1b2b3b4b5b6b7")
ZEROER_EXPECTED = bytes(len(ZEROER_POISON))
ZEROER_WAIT_CYCLES = 200


def _sample_output_write_count() -> int:
    sig = cocotb.top.tb_output_axi_write_count
    assert sig.value.is_resolvable, (
        "tb_output_axi_write_count is not resolvable (X/Z)"
    )
    return int(sig.value)


def _coverage_report_dirs() -> list[Path]:
    """Prefer run logs/coverage dirs so Skill 2 can find the artifact beside the kept log."""
    candidates: list[Path] = []
    env_dir = os.environ.get("SMC_DV_RUN_LOGDIR")
    if env_dir:
        candidates.append(Path(env_dir))
    results = os.environ.get("COCOTB_RESULTS_FILE")
    if results:
        # .../<item>/results/results.xml → .../<item>/logs and .../<item>/coverage
        item_dir = Path(results).resolve().parent.parent
        candidates.append(item_dir / "logs")
        candidates.append(item_dir / "coverage")
    cwd = Path.cwd()
    candidates.append(cwd / "logs")
    candidates.append(cwd / "coverage")
    candidates.append(cwd)
    # Deduplicate while preserving order.
    seen: set[Path] = set()
    out: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            out.append(resolved)
    return out


def _emit_functional_coverage_report(cells_hit: list[str]) -> Path:
    """Write FL-required functional-coverage-report for WRITE-STREAM.S1 cells."""
    payload = {
        "artifact_type": "functional-coverage-report",
        "feature_key": "SMC-ZEROER-WRITE-STREAM.S1",
        "method": "DIRECTED",
        "seed": int(os.environ.get("SEED", "1") or "1"),
        "required_cells": [
            "zeroer-region-zeroed",
            "zeroer-neighbours-untouched",
        ],
        "cells_hit": cells_hit,
        "satisfied": set(cells_hit)
        >= {"zeroer-region-zeroed", "zeroer-neighbours-untouched"},
    }
    text = json.dumps(payload, indent=2) + "\n"
    written: list[Path] = []
    for out_dir in _coverage_report_dirs():
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / "functional-coverage-report.json"
            out_path.write_text(text, encoding="utf-8")
            written.append(out_path)
        except OSError:
            continue
    if not written:
        raise AssertionError("failed to write functional-coverage-report.json")
    return written[0]


class smc_zeroer_dma_timeout_test_seq(SmcCsrSeq):
    """Program zeroer and verify that output-fabric bytes are actually cleared."""

    def __init__(self, name: str = "smc_zeroer_dma_timeout_test_seq") -> None:
        super().__init__(name)
        self.checked_bytes = 0
        self.model_checks = 0

    def _ensure_model_region(self) -> None:
        if OUTPUT_FABRIC_MODEL_REGION not in self.memory_model.regions:
            self.memory_model.add_region(
                OUTPUT_FABRIC_MODEL_REGION,
                OUTPUT_FABRIC_ADDR,
                OUTPUT_FABRIC_MODEL_SIZE,
            )

    async def _program_output_fabric_pass_all(self) -> None:
        await self.csr_write("INBOUND0_START_PASS_ALL", INBOUND0_START, 0x0, length=8)
        await self.csr_write("INBOUND0_END_PASS_ALL", INBOUND0_END,
                             0x00FF_FFFF_FFFF_FFFF, length=8)
        await self.csr_write("INBOUND0_FILTER_CONFIG_PASS_ALL", INBOUND0_FILTER_CONFIG,
                             PASS_ALL_CONFIG, length=8)
        await self.csr_write("OUTBOUND0_START_PASS_ALL", OUTBOUND0_START, 0x0, length=8)
        await self.csr_write("OUTBOUND0_END_PASS_ALL", OUTBOUND0_END,
                             0x00FF_FFFF_FFFF_FFFF, length=8)
        await self.csr_write("OUTBOUND0_FILTER_CONFIG_PASS_ALL", OUTBOUND0_FILTER_CONFIG,
                             PASS_ALL_CONFIG, length=8)

    async def _write_bytes(self, addr: int, data: bytes) -> None:
        assert self.env is not None, "sequence env is not initialized"
        item_name = f"jtag_output_preload_0x{addr:x}"
        item = SmcSysAxiItem(item_name)
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = len(data)
        item.wdata = int.from_bytes(data, "little")
        await _OneShot(item, f"{item_name}_os").start(self.env.jtag_axi_agent.sequencer)

    async def _read_bytes(self, addr: int, length: int) -> bytes:
        assert self.env is not None, "sequence env is not initialized"
        item_name = f"jtag_output_readback_0x{addr:x}"
        item = SmcSysAxiItem(item_name)
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = length
        await _OneShot(item, f"{item_name}_os").start(self.env.jtag_axi_agent.sequencer)
        return item.rdata.to_bytes(length, "little")

    async def _wait_for_zeroer_write(self, expected_count: int) -> None:
        for _ in range(ZEROER_WAIT_CYCLES):
            write_count = _sample_output_write_count()
            if write_count >= expected_count:
                return
            await ClockCycles(cocotb.top.clk_smc_i, 1)
        raise AssertionError(
            f"zeroer write count did not reach {expected_count}, "
            f"got {_sample_output_write_count()}"
        )

    async def body(self) -> None:
        cocotb.log.info(
            "STEP S1: SETUP pass-all filters; JTAG-preload poison "
            f"{ZEROER_POISON.hex()} at {OUTPUT_FABRIC_ADDR:#x} and neighbour "
            f"{ZEROER_NEIGHBOUR_POISON.hex()} at {OUTPUT_FABRIC_NEIGHBOUR_ADDR:#x}"
        )
        self._ensure_model_region()
        await self._program_output_fabric_pass_all()

        # Track poison in the VIP model for neighbour bookkeeping only; the
        # zeroed-region oracle is JTAG AXI readback vs ZEROER_EXPECTED, not
        # memory_model.expect after rewriting the model.
        self.memory_model.write(OUTPUT_FABRIC_ADDR, ZEROER_POISON,
                                region=OUTPUT_FABRIC_MODEL_REGION)
        self.memory_model.write(OUTPUT_FABRIC_NEIGHBOUR_ADDR, ZEROER_NEIGHBOUR_POISON,
                                region=OUTPUT_FABRIC_MODEL_REGION)
        await self._write_bytes(OUTPUT_FABRIC_ADDR, ZEROER_POISON)
        await self._write_bytes(OUTPUT_FABRIC_NEIGHBOUR_ADDR, ZEROER_NEIGHBOUR_POISON)
        preload_rb = await self._read_bytes(OUTPUT_FABRIC_ADDR, len(ZEROER_POISON))
        neighbour_preload = await self._read_bytes(
            OUTPUT_FABRIC_NEIGHBOUR_ADDR, len(ZEROER_NEIGHBOUR_POISON)
        )
        assert preload_rb == ZEROER_POISON
        assert neighbour_preload == ZEROER_NEIGHBOUR_POISON
        # Baseline AFTER JTAG preload so +2 cannot be satisfied by preload writes.
        start_writes = _sample_output_write_count()
        cocotb.log.info(
            "CHK-NONVAC: S1 JTAG preload readback confirms poison "
            f"{preload_rb.hex()} and neighbour {neighbour_preload.hex()} "
            f"were written and observed before trigger; "
            f"write-count baseline after preload={start_writes}"
        )

        cocotb.log.info(
            "STEP S2: program ZEROER_DEST_ADDR/SIZE from smc_reg map "
            f"(DEST@{ZEROER_DEST_ADDR:#x} SIZE@{ZEROER_SIZE:#x})"
        )
        await self.csr_write("ZEROER_DEST_ADDR", ZEROER_DEST_ADDR, OUTPUT_FABRIC_ADDR, length=8)
        await self.csr_write("ZEROER_SIZE", ZEROER_SIZE, len(ZEROER_POISON), length=8)
        cocotb.log.info(
            "CHK-ZEROER-REGION-DECODE: csr_write ZEROER_DEST_ADDR@"
            f"{ZEROER_DEST_ADDR:#x}={OUTPUT_FABRIC_ADDR:#x} and ZEROER_SIZE@"
            f"{ZEROER_SIZE:#x}={len(ZEROER_POISON)} both OKAY "
            "(addresses from smc_reg ZEROER_CTRL_*_REG_ADDR)"
        )

        cocotb.log.info(
            "STEP S3: trigger ZEROER_CTRL_STATUS=1; wait writes; readback zeros"
        )
        # The zeroer FSM starts on the INT_EN field write side effect.
        await self.csr_write("ZEROER_CTRL_STATUS_START", ZEROER_CTRL_STATUS, 0x1, length=8)
        # One AXI write clears the 8-byte DEST region; neighbour is untouched.
        await self._wait_for_zeroer_write(start_writes + 1)
        write_count = _sample_output_write_count()
        cocotb.log.info(
            "CHK-ZEROER-TRIGGER-STARTS: after DEST/SIZE set, "
            f"ZEROER_CTRL_STATUS_START@{ZEROER_CTRL_STATUS:#x}=0x1 caused "
            f"tb_output_axi_write_count {start_writes}->{write_count} "
            f"(post-preload baseline+1) within bound={ZEROER_WAIT_CYCLES} clk_smc_i"
        )

        actual = await self._read_bytes(OUTPUT_FABRIC_ADDR, len(ZEROER_EXPECTED))
        neighbour_after = await self._read_bytes(
            OUTPUT_FABRIC_NEIGHBOUR_ADDR, len(ZEROER_NEIGHBOUR_POISON)
        )
        assert actual == ZEROER_EXPECTED, (
            f"zeroer did not clear payload: got {actual.hex()}, expected {ZEROER_EXPECTED.hex()}"
        )
        assert neighbour_after == ZEROER_NEIGHBOUR_POISON, (
            "zeroer modified neighbour bytes outside configured region: "
            f"got {neighbour_after.hex()}, expected {ZEROER_NEIGHBOUR_POISON.hex()}"
        )
        assert write_count >= start_writes + 1, "zeroer write did not reach output responder"
        # Independent oracles: AXI readback vs ZEROER_EXPECTED / neighbour poison.
        # Do not rewrite memory_model then expect — that is a self-compare.
        self.checked_bytes = len(ZEROER_EXPECTED)
        self.model_checks = 0
        cells_hit = ["zeroer-region-zeroed", "zeroer-neighbours-untouched"]
        report_path = _emit_functional_coverage_report(cells_hit)
        cocotb.log.info(
            "CHK-ZEROER-REGION-ZEROED: JTAG readback at OUTPUT_FABRIC_ADDR "
            f"returns {actual.hex()} (8 zero bytes), replacing poison; "
            f"neighbour@{OUTPUT_FABRIC_NEIGHBOUR_ADDR:#x} still "
            f"{neighbour_after.hex()}; "
            f"tb_output_axi_write_count={write_count} >= post-preload baseline+1 "
            f"(baseline={start_writes}); "
            f"COV cells={cells_hit}; functional-coverage-report={report_path}"
        )
        cocotb.log.info("SMC_006 scenario PASS")
