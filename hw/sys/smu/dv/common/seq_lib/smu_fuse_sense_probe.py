# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Edge and eFuse-command observers for the SMU fuse-sense boundary ports.

The fuse-sense phase runs while the base test is still in ``bring_up`` -- the
eFuse shadow registers leave reset with the SMC primary reset and the sense
starts there -- so the observers have to be armed before the bring-up sequence
rather than at the start of ``run_scenario``. ``arm()`` starts them and returns
immediately; the leaf calls it from its own ``bring_up`` override ahead of
``super().bring_up()``.

Every rising edge is recorded, not just the first. The bring-up pre-drives
``rst_cold_ni`` high for two clk_ref cycles before asserting it, so a reset
observable can rise once during that pre-drive and once at the real release,
and a first-edge-only observer would time the pre-drive.

The eFuse shim command ports carry ``fuse_command_req_t`` /
``fuse_command_resp_t`` (hw/ip/efuse/rtl/svh/efuse_typedef.svh). Both structs
are packed with ``valid`` as the last member, so ``valid`` is bit 0 of the
packed net.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time

from seq_lib.smu_compose_helpers import hier, sample
from seq_lib.smu_tb_pins import tb_pin

_VALID_BIT = 0


class SmuFuseSenseProbe:
    """Rising-edge times and eFuse command counts across the fuse-sense phase.

    ``edge_signals`` maps a report name to a 1-bit handle. ``command_nets``
    maps a report name to a ``(request, response)`` pair of packed command
    nets.
    """

    def __init__(self, test, edge_signals: dict, command_nets: dict) -> None:
        self.test = test
        self.dut = cocotb.top
        self.log = test.logger
        self.rises: dict[str, list[int]] = {name: [] for name in edge_signals}
        self.req_pulses: dict[str, int] = {name: 0 for name in command_nets}
        self.resp_words: dict[str, int] = {name: 0 for name in command_nets}
        self.first_req_ps: dict[str, int | None] = {name: None for name in command_nets}
        self._edge_signals = dict(edge_signals)
        self._command_nets = dict(command_nets)
        self._tasks: list = []

    def arm(self) -> None:
        for name, handle in self._edge_signals.items():
            self._tasks.append(cocotb.start_soon(self._watch_rises(handle, name)))
        for name, pair in self._command_nets.items():
            self._tasks.append(cocotb.start_soon(self._watch_commands(name, *pair)))

    def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()

    async def _watch_rises(self, handle, name: str) -> None:
        while True:
            await RisingEdge(handle)
            self.rises[name].append(get_sim_time("ps"))

    async def _watch_commands(self, name: str, req, resp) -> None:
        prev_req = 0
        prev_resp = 0
        while True:
            await RisingEdge(self.dut.clk_smu_i)
            now_req = (sample(req, f"{name} req", allow_xz=True) >> _VALID_BIT) & 1
            now_resp = (sample(resp, f"{name} resp", allow_xz=True) >> _VALID_BIT) & 1
            if now_req and not prev_req:
                self.req_pulses[name] += 1
                if self.first_req_ps[name] is None:
                    self.first_req_ps[name] = get_sim_time("ps")
            if now_resp and not prev_resp:
                self.resp_words[name] += 1
            prev_req = now_req
            prev_resp = now_resp

    async def wait_for_rise(self, name: str, clk, *, timeout_cycles: int, step_cycles: int) -> int:
        """Block until ``name`` has a recorded rising edge; return its time in ps.

        The edge itself is timed by the observer task, so the poll only has to
        notice that it happened -- hence ``step_cycles`` rather than a
        per-cycle loop across the thousands of cycles a full sense takes.
        """
        for _ in range(max(1, timeout_cycles // step_cycles)):
            if self.rises[name]:
                return self.rises[name][0]
            await ClockCycles(clk, step_cycles)
        raise AssertionError(f"TIMEOUT {name} never rose within {timeout_cycles} cycles")

    def first_rise(self, name: str) -> int:
        edges = self.rises[name]
        if not edges:
            raise AssertionError(f"{name} never rose")
        return edges[0]

    def last_rise(self, name: str) -> int:
        edges = self.rises[name]
        if not edges:
            raise AssertionError(f"{name} never rose")
        return edges[-1]


def smc_command_nets(dut) -> tuple:
    """The SMC eFuse shim command request/response pair at the SMU boundary."""
    wrapper = tb_pin(dut, "u_dut")
    return (
        hier(wrapper, "smc_efuse_shim_command_req"),
        hier(wrapper, "smc_efuse_shim_command_resp"),
    )


def sep_command_nets(dut) -> tuple:
    """The SEP eFuse shim command request/response pair at the SMU boundary."""
    wrapper = tb_pin(dut, "u_dut")
    return (
        hier(wrapper, "sep_efuse_shim_command_req"),
        hier(wrapper, "sep_efuse_shim_command_resp"),
    )
