# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Discriminate the Xcelium SYS_OUT write hang: AW vs W at both ends.

After the outbound filter is programmed pass-all, one JTAG AXI write is issued
at the SYS_OUT responder window (0x0200_0000). A clocked sticky observer records
whether AW/W/B ever handshook on the JTAG ingress and on the SYS_OUT boundary.

Healthy path: write completes and every channel handshook. The four-state
hang this test discriminates is AW-at-SYS_OUT without W-at-SYS_OUT after JTAG
W was accepted. Those two outcomes are different assertion texts so a bare
timeout cannot be mistaken for the split.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ReadOnly, RisingEdge, Timer
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp
from seq_lib._one_shot import _OneShot
from seq_lib.smc_output_fabric_vip_utils import (
    OUTPUT_FABRIC_ADDR,
    OUTPUT_FABRIC_DATA,
    output_fabric_pass_all_cfg_seq,
)
from smc_base_test import smc_base_test

WRITE_TIMEOUT_NS = 50_000

_PAIRS = (
    ("jtag_aw", "jtag_axi_awvalid", "jtag_axi_awready"),
    ("jtag_w", "jtag_axi_wvalid", "jtag_axi_wready"),
    ("jtag_b", "jtag_axi_bvalid", "jtag_axi_bready"),
    ("sys_aw", "tb_output_axi_awvalid", "tb_output_axi_awready"),
    ("sys_w", "tb_output_axi_wvalid", "tb_output_axi_wready"),
    ("sys_b", "tb_output_axi_bvalid", "tb_output_axi_bready"),
)


class _HandshakeWatch:
    def __init__(self) -> None:
        self.stop = False
        self.hs = {name: False for name, _, _ in _PAIRS}
        self.saw_x = {name: False for name, _, _ in _PAIRS}


async def _watch_handshakes(dut, watch: _HandshakeWatch) -> None:
    # The SYS_OUT responder drives READY from cocotb in the clock-edge delta
    # cycles, so a posedge-only sample can miss W even when the write completes;
    # a 1 ns poll in the read-only phase sees every handshake.
    while not watch.stop:
        await Timer(1, unit="ns")
        await ReadOnly()
        for name, v_name, r_name in _PAIRS:
            v = getattr(dut, v_name).value
            r = getattr(dut, r_name).value
            if (not v.is_resolvable) or (not r.is_resolvable):
                watch.saw_x[name] = True
                continue
            if (int(v) & 1) and (int(r) & 1):
                watch.hs[name] = True


def _fmt_watch(watch: _HandshakeWatch) -> str:
    bits = " ".join(f"{n}={int(watch.hs[n])}" for n, _, _ in _PAIRS)
    xs = ",".join(n for n, hit in watch.saw_x.items() if hit) or "none"
    return f"{bits} saw_x={xs}"


@pyuvm.test()
class smc_sys_out_aw_w_split_test(smc_base_test):
    """One SYS_OUT write; fail specifically on AW-without-W at the boundary."""

    required_evidence = ("CHK-SYS-OUT-WR-COMPLETE",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        dut = cocotb.top
        cfg_seq = output_fabric_pass_all_cfg_seq("sys_out_aw_w_split_cfg")
        await self.start_seq(cfg_seq, self.env.sys_axi_agent.sequencer)
        assert cfg_seq.accesses == 6, f"filter pass-all wrote {cfg_seq.accesses} CSRs, want 6"
        cocotb.log.info("STEP S1: outbound+inbound filter pass-all completed (6 CSR writes)")

        watch = _HandshakeWatch()
        watcher = cocotb.start_soon(_watch_handshakes(dut, watch))

        item = SmcSysAxiItem(f"jtag_sys_out_write_0x{OUTPUT_FABRIC_ADDR:x}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = OUTPUT_FABRIC_ADDR
        item.length = 8
        item.wdata = OUTPUT_FABRIC_DATA
        item.allow_timeout = True
        item.timeout_ns = WRITE_TIMEOUT_NS
        await _OneShot(item, "jtag_sys_out_write_os").start(self.env.jtag_axi_agent.sequencer)

        watch.stop = True
        await RisingEdge(dut.clk_smc_i)
        await watcher

        snap = _fmt_watch(watch)
        cocotb.log.info(
            f"SYS-OUT-AW-W-SPLIT: timed_out={int(item.timed_out)} {snap} "
            f"addr={OUTPUT_FABRIC_ADDR:#x}"
        )

        x_on_sys = [n for n in ("sys_aw", "sys_w", "sys_b") if watch.saw_x[n]]
        assert not x_on_sys, f"SYS-OUT-X: handshake line X/Z on {x_on_sys}; {snap}"

        if not item.timed_out:
            assert watch.hs["sys_aw"] and watch.hs["sys_w"] and watch.hs["sys_b"], (
                f"write completed but SYS_OUT missed a channel; {snap}"
            )
            assert watch.hs["jtag_aw"] and watch.hs["jtag_w"] and watch.hs["jtag_b"], (
                f"write completed but JTAG ingress missed a channel; {snap}"
            )
            cocotb.log.info(
                f"CHK-SYS-OUT-WR-COMPLETE: JTAG write {OUTPUT_FABRIC_ADDR:#x} "
                f"OKAY; SYS_OUT aw/w/b all handshook ({snap})"
            )
            return

        if watch.hs["sys_aw"] and not watch.hs["sys_w"]:
            raise AssertionError(
                f"SYS-OUT-AW-WITHOUT-W: JTAG write @ {OUTPUT_FABRIC_ADDR:#x} "
                f"timed out after {WRITE_TIMEOUT_NS} ns; SYS_OUT AW handshook, "
                f"W never did, B never did; JTAG ingress "
                f"aw={int(watch.hs['jtag_aw'])} w={int(watch.hs['jtag_w'])} "
                f"b={int(watch.hs['jtag_b'])}; {snap}"
            )
        raise AssertionError(
            f"SYS-OUT-WRITE-TIMEOUT: JTAG write @ {OUTPUT_FABRIC_ADDR:#x} "
            f"timed out after {WRITE_TIMEOUT_NS} ns without the AW-without-W "
            f"split; {snap}"
        )
