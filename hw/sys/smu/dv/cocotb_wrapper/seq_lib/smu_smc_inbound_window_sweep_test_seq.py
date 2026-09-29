# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Inbound SMN traffic into the SMC peripheral windows, with every AxPROT and write ID.

The SMC local aperture is routed to its local alias and SYS_IN entries 0 and 1
pass every address, entry 0 for non-secure and entry 1 for secure traffic
(``hw/ip/axi_filter/doc/index.adoc``, "Match, Then Permit": the match on
``prot[1]`` is exact). The SMC peripheral crossbar then decodes each request
(``smc_periph_axi_lite_xbar.sv``).

S1: under each of the eight AxPROT encodings, ext_in reads the word at the base
    of the SMC external window, the external target above it, a cross-trigger
    port CONFIG register in the DTP control window, and eFuse MAP SPARE[0],
    and writes each word read back to it. Every access completes; the window
    base and DTP words read back unchanged. The eFuse controller's demux passes
    the address phase of each eFuse access to its bank-control port as well
    (``efuse_interface_controller.sv``).
S2: every AxSIZE, with each of address bits [6:0] set and cleared between
    accesses, reads and writes the external target; each completes.
S3: sixteen writes into the SMC SPM, each under its own AWID, are launched
    before the first response is taken while the master holds BREADY back;
    each is OKAY and every word reads back.
S4: sixty-four reads, alternately single and eight-beat INCR bursts, and
    sixty-four writes over sixteen IDs are launched together at the external
    target, and then at the DTP CONFIG word, before the first response is
    taken, with RREADY and BREADY held back; every one completes, and the DTP
    word written back is unchanged. A read and write-back of eFuse SPARE[0] at
    AxPROT 0 follow.
S5: holding the cool reset pin asserts the SMC primary reset, which also resets
    the SMU crossbar and ID converters (``smu.sv``), and releasing it releases
    the SMC.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, with_timeout
from ocah_axi_vip import RESP_OKAY, AxiTimingProfile, resp_name, worst_resp

from seq_lib.smu_addr_map import (
    SMC_CHIP_CONFIG_VERSION_LO,
    filter_ctrl_bm,
    filter_ctrl_field_reset_encode,
    smc_addr,
    smc_indexed_addr,
)
from seq_lib.smu_axi_helpers import AXI_TIMEOUT_NS, make_smu_axi_master
from seq_lib.smu_axi_in_burst_outstanding_test_seq import smu_axi_in_burst_outstanding_test_seq
from seq_lib.smu_boundary_regs import cross_trigger_network_indexed_addr, cross_trigger_u32
from seq_lib.smu_filter_helpers import PASS_ALL_END, await_smn_resp
from seq_lib.smu_jtag_helpers import J2A_STATUS_SUCCESS, jtag2axi_single_write
from seq_lib.smu_tb_pins import smc_primary_reset

WINDOW_BASE = smc_addr("SMC_TOP_SMC_EXTERNAL_BASE_ADDR")
EXTERNAL = WINDOW_BASE + 0x1000
DTP_CTP_CONFIG = (
    smc_addr("SMC_TOP_DTP_CTRL_REG_BASE_ADDR")
    + cross_trigger_network_indexed_addr("CROSS_TRIGGER_NETWORK_CTP_BASE_ADDR", 7)
    + cross_trigger_u32("CROSS_TRIGGER_PORT_CONFIG_BASE_ADDR")
)
SPM = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR") + 0x2000
EFUSE_SPARE0 = smc_indexed_addr("SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR", 0)
VERSION_LO = SMC_CHIP_CONFIG_VERSION_LO

_IN_CFG = "SMC_TOP_SMC_INBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR"
_IN_START = "SMC_TOP_SMC_INBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR"
_IN_END = "SMC_TOP_SMC_INBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR"
SECURE_ENTRY = 1
CFG_SECURE = (
    filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__READ_ALLOWED_bm")
    | filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__WRITE_ALLOWED_bm")
    | filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm")
    | filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ALLOW_BURST_bm")
    | filter_ctrl_field_reset_encode("DATA_BUS_WIDTH")
)

# (AxSIZE, byte offset from EXTERNAL) setting and clearing address bits [6:0].
SIZE_CELLS = ((2, 0), (0, 1), (1, 2), (2, 4), (3, 8), (2, 16), (2, 32), (2, 64), (0, 0x7F), (3, 0))
ID_TRAIN = 16
HELD_TRAIN = 64
# RREADY and BREADY stay low this long after each train starts
# (the VIP's pause countdown), then every response is taken.
HELD_HOLD_CYCLES = 20000
HELD_WAIT_NS = 4 * AXI_TIMEOUT_NS
COOL_RESET_HOLD_REF_CYCLES = 256
COOL_RESET_RELEASE_REF_CYCLES = 8192
TRAIN_HOLD_CYCLES = 600


class smu_smc_inbound_window_sweep_test_seq(smu_axi_in_burst_outstanding_test_seq):
    """ext_in into the SMC external, DTP and eFuse windows, and trains of distinct IDs."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.steps = {"S1": False, "S2": False, "S3": False, "S4": False, "S5": False}

    async def _ax(self, master, *, write: bool, addr: int, payload, label: str, **attrs):
        event = (master.init_write if write else master.init_read)(addr, payload, **attrs)
        try:
            await with_timeout(event.wait(), AXI_TIMEOUT_NS, "ns")
        except Exception as exc:
            raise AssertionError(f"TIMEOUT {label} addr=0x{addr:x} attrs={attrs}: {exc}") from exc
        raw = event.data
        return worst_resp(getattr(raw, "resp", None)), bytes(getattr(raw, "data", b""))

    async def _open_secure(self, jtag) -> None:
        for sym, value, tag in (
            (_IN_START, 0, "START"),
            (_IN_END, PASS_ALL_END, "END"),
            (_IN_CFG, CFG_SECURE, "CONFIG"),
        ):
            await self._j2a_wr(jtag, smc_indexed_addr(sym, SECURE_ENTRY), value, f"SECURE_{tag}")

    async def _j2a_wr(self, jtag, addr: int, data: int, name: str) -> None:
        status, _ = await jtag2axi_single_write(jtag, addr, data, require_complete=True)
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A WR {name} @0x{addr:x} status={status}")

    async def _prot_sweep(self, master, sb) -> None:
        observed, want = {}, {}
        for prot in range(8):
            for name, addr, stable in (
                ("base", WINDOW_BASE, True),
                ("external", EXTERNAL, False),
                ("dtp", DTP_CTP_CONFIG, True),
                ("efuse", EFUSE_SPARE0, False),
            ):
                resp_r, data = await self._ax(
                    master, write=False, addr=addr, payload=4, size=2, prot=prot, label=f"{name}r"
                )
                resp_w, _ = await self._ax(
                    master,
                    write=True,
                    addr=addr,
                    payload=data[:4] or bytes(4),
                    size=2,
                    prot=prot,
                    label=f"{name}w",
                )
                resp_c, after = await self._ax(
                    master, write=False, addr=addr, payload=4, size=2, prot=prot, label=f"{name}c"
                )
                key = f"{name}/prot{prot}"
                if stable:
                    observed[key] = (
                        resp_name(resp_r),
                        resp_name(resp_w),
                        resp_name(resp_c),
                        after[:4] == data[:4],
                    )
                    want[key] = (
                        resp_name(RESP_OKAY),
                        resp_name(RESP_OKAY),
                        resp_name(RESP_OKAY),
                        True,
                    )
                else:
                    observed[key] = "completed"
                    want[key] = "completed"
        self._log(f"CHK-SMC-WINDOW-PROT {observed}")
        sb.expect_eq("CHK-SMC-WINDOW-PROT", observed, want, evidence="CHK-SMC-WINDOW-PROT")
        self.steps["S1"] = True

    async def _size_sweep(self, master, sb) -> None:
        done = 0
        for size, off in SIZE_CELLS:
            nbytes = 1 << size
            await self._ax(
                master,
                write=True,
                addr=EXTERNAL + off,
                payload=bytes(nbytes),
                size=size,
                label=f"extw{off}",
            )
            await self._ax(
                master,
                write=False,
                addr=EXTERNAL + off,
                payload=nbytes,
                size=size,
                label=f"extr{off}",
            )
            done += 1
        self._log(f"CHK-SMC-WINDOW-EXTERNAL-SIZE completed={done} of {len(SIZE_CELLS)}")
        sb.expect_eq(
            "CHK-SMC-WINDOW-EXTERNAL-SIZE",
            done,
            len(SIZE_CELLS),
            evidence="CHK-SMC-WINDOW-EXTERNAL-SIZE",
        )
        self.steps["S2"] = True

    async def _awid_train(self, master, sb) -> None:
        words = [(0x7E57_0000_0000_0000 | i).to_bytes(8, "little") for i in range(ID_TRAIN)]
        master.driver.set_timing(AxiTimingProfile(b_ready_delay=TRAIN_HOLD_CYCLES))
        try:
            events = [
                master.init_write(SPM + 8 * i, words[i], size=3, id=16 * i + 5)
                for i in range(ID_TRAIN)
            ]
            for event in events:
                await with_timeout(event.wait(), AXI_TIMEOUT_NS, "ns")
        finally:
            master.driver.set_timing(AxiTimingProfile())
        bad = [i for i, e in enumerate(events) if worst_resp(e.data.resp) != RESP_OKAY]
        for i in range(ID_TRAIN):
            resp, data = await self._ax(
                master, write=False, addr=SPM + 8 * i, payload=8, size=3, label=f"rb{i}"
            )
            if resp != RESP_OKAY or data[:8] != words[i]:
                bad.append(("read", i))
        self._log(f"CHK-SMC-WINDOW-AWID-TRAIN mismatches={bad}")
        sb.expect_eq("CHK-SMC-WINDOW-AWID-TRAIN", bad, [], evidence="CHK-SMC-WINDOW-AWID-TRAIN")
        self.steps["S3"] = True

    async def _held_trains(self, master, sb) -> None:
        resp_dtp0, dtp_word = await self._ax(
            master, write=False, addr=DTP_CTP_CONFIG, payload=4, size=2, label="dtp0"
        )
        done = {}
        train_resps = {}
        try:
            for name, addr, word in (
                ("external", EXTERNAL, bytes(4)),
                ("dtp", DTP_CTP_CONFIG, dtp_word[:4]),
            ):
                master.driver.set_timing(
                    AxiTimingProfile(r_ready_delay=HELD_HOLD_CYCLES, b_ready_delay=HELD_HOLD_CYCLES)
                )
                reads = [
                    master.init_read(addr, 4 * (1 + (i % 2) * 7), size=2, id=16 * (i % 16) + 7)
                    for i in range(HELD_TRAIN)
                ]
                writes = [
                    master.init_write(addr, word, size=2, id=16 * (i % 16) + 9)
                    for i in range(HELD_TRAIN)
                ]
                for event in reads + writes:
                    await with_timeout(event.wait(), HELD_WAIT_NS, "ns")
                done[name] = len(reads) + len(writes)
                train_resps[name] = {
                    resp_name(worst_resp(getattr(event.data, "resp", None)))
                    for event in reads + writes
                }
        finally:
            master.driver.set_timing(AxiTimingProfile())
        resp_dtp1, after = await self._ax(
            master, write=False, addr=DTP_CTP_CONFIG, payload=4, size=2, label="dtp1"
        )
        resp_efuse1, efuse_word = await self._ax(
            master, write=False, addr=EFUSE_SPARE0, payload=4, size=2, label="efuse1"
        )
        await self._ax(
            master,
            write=True,
            addr=EFUSE_SPARE0,
            payload=efuse_word[:4] or bytes(4),
            size=2,
            label="efuse1w",
        )
        okay = resp_name(RESP_OKAY)
        observed = (
            done,
            after[:4] == dtp_word[:4],
            (resp_name(resp_dtp0), resp_name(resp_dtp1), resp_name(resp_efuse1)),
            train_resps["dtp"],
        )
        self._log(f"CHK-SMC-WINDOW-HELD-TRAIN {observed}")
        sb.expect_eq(
            "CHK-SMC-WINDOW-HELD-TRAIN",
            observed,
            ({"external": 2 * HELD_TRAIN, "dtp": 2 * HELD_TRAIN}, True, (okay, okay, okay), {okay}),
            evidence="CHK-SMC-WINDOW-HELD-TRAIN",
        )
        self.steps["S4"] = True

    async def _cool_reset(self, sb) -> None:
        dut = self.dut
        dut.tb_cool_reset_pin.value = 1
        await ClockCycles(dut.clk_ref_i, COOL_RESET_HOLD_REF_CYCLES)
        held_low = int(dut.obs_smc_rst_n_o.value)
        dut.tb_cool_reset_pin.value = 0
        released = 0
        for _ in range(COOL_RESET_RELEASE_REF_CYCLES):
            await ClockCycles(dut.clk_ref_i, 1)
            released = int(dut.obs_smc_rst_n_o.value)
            if released:
                break
        self._log(f"CHK-SMC-WINDOW-COOL-RESET held={held_low} released={released}")
        sb.expect_eq(
            "CHK-SMC-WINDOW-COOL-RESET",
            (held_low, released),
            (0, 1),
            evidence="CHK-SMC-WINDOW-COOL-RESET",
        )
        self.steps["S5"] = True

    async def run(self) -> None:
        dut = self.dut
        sb = self.test.env.scoreboard
        await self.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, 16)
        jtag = await self._open_window(sb)
        await self._open_secure(jtag)
        master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))
        await await_smn_resp(
            master, VERSION_LO, RESP_OKAY, clk=dut.clk_smu_i, label="window_sweep_ready"
        )
        await self._prot_sweep(master, sb)
        await self._size_sweep(master, sb)
        await self._awid_train(master, sb)
        await self._held_trains(master, sb)
        await self._cool_reset(sb)
        await ClockCycles(dut.clk_smu_i, 2)
        cocotb.log.info("window sweep complete")
