# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_smc_smoke_test (SMU_ALL_003).

DV-CARD:          SMU_ALL_003   ANCHOR: smu_smc_smoke_test

Owns:
  SMC-FAB-DUAL-NET.S2 — local peripherals/config registers use AXI4-Lite LP
  SMC-FAB-DUAL-NET.S3 — both networks carry 64-bit data without truncation

Bare tb_top SEP=0: hierarchical CONNECTIVITY observe only (no Force/deposit).

Independent expects from pinned hw/sys/smc/doc/fabric.adoc
  §Network Characteristics / §AXI Common Signal Widths / §AXI ID Widths /
  §Traffic Subordinates (AXI4-Lite Low-Performance rows) @ffc8cdcc…
"""

from __future__ import annotations

from seq_lib.smu_tb_pins import smc_primary_reset

import time

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge


class smu_smc_smoke_test_seq:
    """SMU_ALL_003: SMC dual-network LP dest + SPEC 64-bit data observe."""

    BOUND_CYCLES = 2000
    SETTLE_CYCLES = 32
    # Bounded waits: primary release (S1) + dest attachment settle (S2).
    EXPECTED_TIMEOUT_PATHS = 2

    # Pinned SPEC field widths (fabric.adoc) — never RTL typedef totals.
    SPEC_DATA_WIDTH = 64
    SPEC_ADDR_LOCAL = 32
    SPEC_USER_WIDTH = 12
    SPEC_ID_LOCAL_FABRIC_SLV = 6  # Local / Output fabric (slave side)
    # SPEC also documents some AXI4-Lite peripheral paths at 32-bit data.
    SPEC_PERIPH_LITE_DATA = 32

    # AMBA AXI4 channel fixed field widths (protocol, not DUT typedefs).
    _AXI4_LEN = 8
    _AXI4_SIZE = 3
    _AXI4_BURST = 2
    _AXI4_LOCK = 1
    _AXI4_CACHE = 4
    _AXI4_PROT = 3
    _AXI4_QOS = 4
    _AXI4_REGION = 4
    _AXI4_ATOP = 6
    _AXI4_LAST = 1
    _AXIL_PROT = 3

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self._step_ts: dict[str, float] = {}
        self._timeout_paths: list[str] = []

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark_step(self, step_id: str, detail: str) -> None:
        self._step_ts[step_id] = time.monotonic()
        self._log(f"STEP {step_id}: {detail}")

    def _sample(self, signal, name: str) -> int:
        val = signal.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z sample on {name}: {val}")
        return int(val)

    def _require_child(self, parent, name: str):
        if not hasattr(parent, name):
            raise AssertionError(f"missing hierarchical child {name} under {parent}")
        return getattr(parent, name)

    def _nbits(self, signal, name: str) -> int:
        """Return signal bit-width; fail on missing/X handles."""
        if signal is None:
            raise AssertionError(f"width observe fail: {name} is None")
        n = getattr(signal, "n_bits", None)
        if n is None:
            try:
                n = len(signal)
            except TypeError as exc:
                raise AssertionError(f"width observe fail: cannot measure {name}") from exc
        if n <= 0:
            raise AssertionError(f"width observe fail: {name} n_bits={n}")
        _ = self._sample(signal, name)
        return int(n)

    @classmethod
    def _axil_req_bits(cls, addr_w: int, data_w: int) -> int:
        """AXI4-Lite req packed width from SPEC addr/data (pulp AXI_LITE layout).

        aw/ar = addr+prot; w = data+strb; plus aw/w/ar_valid + b/r_ready.
        """
        strb = data_w // 8
        return 2 * (addr_w + cls._AXIL_PROT) + data_w + strb + 5

    @classmethod
    def _axi4_req_bits(cls, addr_w: int, data_w: int, id_w: int, user_w: int) -> int:
        """AXI4 req packed width from SPEC field widths (pulp AXI_TYPEDEF layout)."""
        aw = (
            id_w
            + addr_w
            + cls._AXI4_LEN
            + cls._AXI4_SIZE
            + cls._AXI4_BURST
            + cls._AXI4_LOCK
            + cls._AXI4_CACHE
            + cls._AXI4_PROT
            + cls._AXI4_QOS
            + cls._AXI4_REGION
            + cls._AXI4_ATOP
            + user_w
        )
        w = data_w + (data_w // 8) + cls._AXI4_LAST + user_w
        ar = (
            id_w
            + addr_w
            + cls._AXI4_LEN
            + cls._AXI4_SIZE
            + cls._AXI4_BURST
            + cls._AXI4_LOCK
            + cls._AXI4_CACHE
            + cls._AXI4_PROT
            + cls._AXI4_QOS
            + cls._AXI4_REGION
            + user_w
        )
        return aw + 1 + w + 1 + 1 + ar + 1 + 1

    @classmethod
    def _derive_axil_data_width(cls, packed: int, addr_w: int) -> int:
        """Invert Lite packing: packed = 2*(addr+3) + data + data/8 + 5."""
        const = 2 * (addr_w + cls._AXIL_PROT) + 5
        rem = packed - const
        # rem = data + data/8 = 9*data/8 → data = rem*8/9
        if rem <= 0 or (rem * 8) % 9 != 0:
            raise AssertionError(
                f"AXI4-Lite packed={packed} not invertible to data width (addr={addr_w} rem={rem})"
            )
        data_w = (rem * 8) // 9
        if cls._axil_req_bits(addr_w, data_w) != packed:
            raise AssertionError(f"AXI4-Lite invert mismatch: packed={packed} → data={data_w}")
        return data_w

    @classmethod
    def _derive_axi4_data_width(cls, packed: int, addr_w: int, id_w: int, user_w: int) -> int:
        """Invert AXI4 packing for data width (strb = data/8)."""
        aw_wo_data = (
            id_w
            + addr_w
            + cls._AXI4_LEN
            + cls._AXI4_SIZE
            + cls._AXI4_BURST
            + cls._AXI4_LOCK
            + cls._AXI4_CACHE
            + cls._AXI4_PROT
            + cls._AXI4_QOS
            + cls._AXI4_REGION
            + cls._AXI4_ATOP
            + user_w
            + 1
        )
        ar = (
            id_w
            + addr_w
            + cls._AXI4_LEN
            + cls._AXI4_SIZE
            + cls._AXI4_BURST
            + cls._AXI4_LOCK
            + cls._AXI4_CACHE
            + cls._AXI4_PROT
            + cls._AXI4_QOS
            + cls._AXI4_REGION
            + user_w
            + 1
        )
        # packed = aw+1 + (data+strb+last+user)+1 + 1 + ar+1 + 1
        #        = aw_wo_data + data + data/8 + last + user + 1 + 1 + ar + 1
        const = aw_wo_data + cls._AXI4_LAST + user_w + 1 + 1 + ar + 1
        rem = packed - const
        if rem <= 0 or (rem * 8) % 9 != 0:
            raise AssertionError(
                f"AXI4 packed={packed} not invertible to data width "
                f"(addr={addr_w} id={id_w} user={user_w} rem={rem})"
            )
        data_w = (rem * 8) // 9
        if cls._axi4_req_bits(addr_w, data_w, id_w, user_w) != packed:
            raise AssertionError(f"AXI4 invert mismatch: packed={packed} → data={data_w}")
        return data_w

    async def _wait_eq(
        self,
        signal,
        expect: int,
        *,
        clk,
        bound: int,
        label: str,
    ) -> int:
        last = None
        for _ in range(bound):
            await RisingEdge(clk)
            last = self._sample(signal, label)
            if last == expect:
                self._timeout_paths.append(f"{label}: bound={bound} ok last={last}")
                return last
        self._timeout_paths.append(f"{label}: bound={bound} EXPIRED last={last}")
        raise AssertionError(f"TIMEOUT {label}: bound={bound} last_state={last} expect={expect}")

    def _resolve_dual_net_hierarchy(self, dut):
        """Walk bare SMU→SMC fabric dual-network instances (CONNECTIVITY)."""
        smu = self._require_child(dut, "u_dut")
        smc = self._require_child(smu, "u_smc")
        base = self._require_child(smc, "u_smc_base")
        fabric = self._require_child(base, "u_smc_fabric")
        local = self._require_child(fabric, "u_smc_local_fabric")
        hp_xbar = self._require_child(local, "u_smc_local_xbar")
        lp_cfg_xbar = self._require_child(local, "u_smc_internal_axi_lite_xbar")
        periphs = self._require_child(smc, "u_smc_peripherals")
        lp_periph_xbar = self._require_child(periphs, "u_smc_periph_axi_lite_xbar")
        return {
            "smu": smu,
            "smc": smc,
            "local_fabric": local,
            "hp_xbar": hp_xbar,
            "lp_cfg_xbar": lp_cfg_xbar,
            "lp_periph_xbar": lp_periph_xbar,
        }

    def _rst_handle(self, mod, label: str):
        if hasattr(mod, "rst_ni"):
            return mod.rst_ni
        if hasattr(mod, "rst_n"):
            return mod.rst_n
        raise AssertionError(f"{label} rst unobservable")

    async def run(self) -> None:
        dut = self.dut
        sb = self.test.env.scoreboard

        await self.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, self.SETTLE_CYCLES)

        # ------------------------------------------------------------------
        # S1 SETUP
        # ------------------------------------------------------------------
        self._mark_step(
            "S1",
            "SETUP: SEP=0 bare tb_top clocks/resets stable; resolve SMC "
            "dual-network hierarchy baseline",
        )
        primary = await self._wait_eq(
            smc_primary_reset(dut),
            1,
            clk=dut.clk_smu_i,
            bound=self.BOUND_CYCLES,
            label="s1_rst_primary_smc_release",
        )
        hier = self._resolve_dual_net_hierarchy(dut)
        self._log(
            "baseline dual-net hierarchy: "
            "u_smc_local_xbar + u_smc_internal_axi_lite_xbar + "
            "u_smc_periph_axi_lite_xbar present "
            f"(rst_primary_smc={primary})"
        )

        # ------------------------------------------------------------------
        # S2 SMC-FAB-DUAL-NET.S2 — dest=local_peripheral + dest=config_register
        # ------------------------------------------------------------------
        self._mark_step(
            "S2",
            "ACTION SMC-FAB-DUAL-NET.S2: observe AXI4-Lite LP destination "
            "attachments (GPIO local_peripheral + base_config config_register)",
        )
        self._log(
            "COVERAGE SMC-FAB-DUAL-NET.S2 cells: "
            "dest=local_peripheral dest=config_register net=AXI4-Lite"
        )

        lp_cfg = hier["lp_cfg_xbar"]
        lp_periph = hier["lp_periph_xbar"]
        cfg_rst = self._rst_handle(lp_cfg, "LP cfg xbar")
        per_rst = self._rst_handle(lp_periph, "LP periph xbar")

        # Destination-side attachments (Traffic Subordinates):
        #   local_peripheral → gpio_req_o (SPEC: UART/I2C/GPIO …)
        #   config_register  → smc_base_config_req_o (SPEC: fabric control /
        #                      filtering / remapping CSRs)
        gpio_req = self._require_child(lp_periph, "gpio_req_o")
        cfg_req = self._require_child(lp_cfg, "smc_base_config_req_o")

        expect_periph_lite = self._axil_req_bits(self.SPEC_ADDR_LOCAL, self.SPEC_PERIPH_LITE_DATA)
        expect_cfg_lite = self._axil_req_bits(self.SPEC_ADDR_LOCAL, self.SPEC_DATA_WIDTH)

        label = "s2_dest_attachment_settle"
        last_cfg_rst = last_per_rst = None
        gpio_bits = cfg_bits = None
        matched = False
        for _ in range(self.BOUND_CYCLES):
            await RisingEdge(dut.clk_smu_i)
            last_cfg_rst = self._sample(cfg_rst, "lp_cfg.rst")
            last_per_rst = self._sample(per_rst, "lp_periph.rst")
            try:
                gpio_bits = self._nbits(gpio_req, "dest.gpio_req_o")
                cfg_bits = self._nbits(cfg_req, "dest.smc_base_config_req_o")
            except AssertionError:
                continue
            if (
                last_cfg_rst == 1
                and last_per_rst == 1
                and gpio_bits == expect_periph_lite
                and cfg_bits == expect_cfg_lite
            ):
                matched = True
                self._timeout_paths.append(
                    f"{label}: bound={self.BOUND_CYCLES} ok "
                    f"last=cfg_rst={last_cfg_rst}/per_rst={last_per_rst}/"
                    f"gpio_bits={gpio_bits}/cfg_bits={cfg_bits}"
                )
                break
        if not matched:
            self._timeout_paths.append(
                f"{label}: bound={self.BOUND_CYCLES} EXPIRED "
                f"last=cfg_rst={last_cfg_rst}/per_rst={last_per_rst}/"
                f"gpio_bits={gpio_bits}/cfg_bits={cfg_bits}"
            )
            raise AssertionError(
                f"TIMEOUT {label}: bound={self.BOUND_CYCLES} "
                f"last_state=cfg_rst={last_cfg_rst}/per_rst={last_per_rst}/"
                f"gpio_bits={gpio_bits}/cfg_bits={cfg_bits} "
                f"expect_gpio={expect_periph_lite} expect_cfg={expect_cfg_lite}"
            )

        # Dual-network coexistence: HP AXI4 xbar still present.
        if hier["hp_xbar"] is None:
            raise AssertionError("HP AXI4 local xbar missing (not dual-net)")

        # Dest cells achieved: both subordinate attachments observed.
        dest_cells = 0
        if gpio_bits == expect_periph_lite:
            dest_cells += 1
            self._log(
                "DEST dest=local_peripheral path=gpio_req_o "
                f"axil_pack={gpio_bits} "
                f"(SPEC addr={self.SPEC_ADDR_LOCAL} "
                f"periph_data={self.SPEC_PERIPH_LITE_DATA})"
            )
        if cfg_bits == expect_cfg_lite:
            dest_cells += 1
            self._log(
                "DEST dest=config_register path=smc_base_config_req_o "
                f"axil_pack={cfg_bits} "
                f"(SPEC addr={self.SPEC_ADDR_LOCAL} "
                f"data={self.SPEC_DATA_WIDTH})"
            )
        if dest_cells != 2:
            raise AssertionError(f"SMC-FAB-DUAL-NET.S2 dest cells={dest_cells} expect=2")

        detail_s2 = (
            "net=AXI4-Lite "
            f"dest=local_peripheral=gpio_req_o(pack={gpio_bits}) "
            f"dest=config_register=smc_base_config_req_o(pack={cfg_bits}) "
            f"cfg_rst={last_cfg_rst} per_rst={last_per_rst}"
        )
        self._log(f"CHK-SMC-FAB-DUAL-NET-S2: PASS ({detail_s2})")
        sb.expect_eq(
            "CHK-SMC-FAB-DUAL-NET-S2 dest cell count",
            dest_cells,
            2,
            evidence="CHK-SMC-FAB-DUAL-NET-S2",
        )
        sb.expect_eq(
            "CHK-SMC-FAB-DUAL-NET-S2 local_peripheral gpio pack",
            gpio_bits,
            expect_periph_lite,
            evidence="CHK-SMC-FAB-DUAL-NET-S2",
        )
        sb.expect_eq(
            "CHK-SMC-FAB-DUAL-NET-S2 config_register pack",
            cfg_bits,
            expect_cfg_lite,
            evidence="CHK-SMC-FAB-DUAL-NET-S2",
        )

        # ------------------------------------------------------------------
        # S3 SMC-FAB-DUAL-NET.S3 — data-bus width 64 on both networks
        # ------------------------------------------------------------------
        self._mark_step(
            "S3",
            "ACTION SMC-FAB-DUAL-NET.S3: derive data-bus width from SPEC "
            "packing formula on AXI4 HP and AXI4-Lite LP nets",
        )
        self._log("COVERAGE SMC-FAB-DUAL-NET.S3 cells: net=AXI4,data=64 net=AXI4-Lite,data=64")

        local = hier["local_fabric"]
        if not hasattr(local, "input_axi_req_i"):
            raise AssertionError("unobservable AXI4 HP packed bus input_axi_req_i")
        if not hasattr(local, "axil_smc_base_config_req_o"):
            raise AssertionError("unobservable AXI4-Lite LP packed bus axil_smc_base_config_req_o")

        hp_packed = self._nbits(local.input_axi_req_i, "local_fabric.input_axi_req_i")
        lp_packed = self._nbits(
            local.axil_smc_base_config_req_o,
            "local_fabric.axil_smc_base_config_req_o",
        )

        # Independent expect: invert sampled packing with SPEC addr/id/user
        # to obtain the data-bus width (the FL quantity). Fail if != 64.
        hp_data = self._derive_axi4_data_width(
            hp_packed,
            self.SPEC_ADDR_LOCAL,
            self.SPEC_ID_LOCAL_FABRIC_SLV,
            self.SPEC_USER_WIDTH,
        )
        lp_data = self._derive_axil_data_width(lp_packed, self.SPEC_ADDR_LOCAL)

        if hp_data != self.SPEC_DATA_WIDTH:
            raise AssertionError(
                f"AXI4 HP data_width={hp_data} expect={self.SPEC_DATA_WIDTH} (packed={hp_packed})"
            )
        if lp_data != self.SPEC_DATA_WIDTH:
            raise AssertionError(
                f"AXI4-Lite LP data_width={lp_data} "
                f"expect={self.SPEC_DATA_WIDTH} (packed={lp_packed})"
            )

        # Secondary falsifier only: 32-bit Lite contrast must not equal LP64.
        expect_lite32 = self._axil_req_bits(self.SPEC_ADDR_LOCAL, self.SPEC_PERIPH_LITE_DATA)
        if lp_packed == expect_lite32:
            raise AssertionError("AXI4-Lite config network collapsed to 32-bit Lite packing")

        net_cells = 0
        if hp_data == self.SPEC_DATA_WIDTH:
            net_cells += 1
        if lp_data == self.SPEC_DATA_WIDTH:
            net_cells += 1
        if net_cells != 2:
            raise AssertionError(f"SMC-FAB-DUAL-NET.S3 net cells={net_cells} expect=2")

        detail_s3 = (
            f"net=AXI4,data={hp_data} "
            f"(input_axi_req_i packed={hp_packed} "
            f"formula←SPEC addr={self.SPEC_ADDR_LOCAL}/"
            f"id={self.SPEC_ID_LOCAL_FABRIC_SLV}/"
            f"user={self.SPEC_USER_WIDTH}) "
            f"net=AXI4-Lite,data={lp_data} "
            f"(axil_smc_base_config_req_o packed={lp_packed} "
            f"formula←SPEC addr={self.SPEC_ADDR_LOCAL})"
        )
        self._log(f"CHK-SMC-FAB-DUAL-NET-S3: PASS ({detail_s3})")
        sb.expect_eq(
            "CHK-SMC-FAB-DUAL-NET-S3 AXI4 data-bus width",
            hp_data,
            self.SPEC_DATA_WIDTH,
            evidence="CHK-SMC-FAB-DUAL-NET-S3",
        )
        sb.expect_eq(
            "CHK-SMC-FAB-DUAL-NET-S3 AXI4-Lite data-bus width",
            lp_data,
            self.SPEC_DATA_WIDTH,
            evidence="CHK-SMC-FAB-DUAL-NET-S3",
        )

        # ------------------------------------------------------------------
        # S4 TIMEOUT inventory
        # ------------------------------------------------------------------
        self._mark_step(
            "S4",
            "TIMEOUT: every bounded wait names finite bound + fail-on-expiry + last-state",
        )
        for line in self._timeout_paths:
            self._log(f"TIMEOUT-PATH {line}")
        n_paths = len(self._timeout_paths)
        if n_paths != self.EXPECTED_TIMEOUT_PATHS:
            raise AssertionError(
                f"CHK-TIMEOUT-PATHS count mismatch: got {n_paths} "
                f"expect {self.EXPECTED_TIMEOUT_PATHS}"
            )
        for i, line in enumerate(self._timeout_paths):
            if "bound=" not in line:
                raise AssertionError(f"CHK-TIMEOUT-PATHS[{i}] missing finite bound: {line}")
            if "ok last=" not in line and "EXPIRED last=" not in line:
                raise AssertionError(f"CHK-TIMEOUT-PATHS[{i}] missing last-state: {line}")
        chk_to = (
            "CHK-TIMEOUT-PATHS: every bounded wait names finite bound, "
            f"fail-on-expiry path, and last-state diagnostic "
            f"(paths={n_paths} expect={self.EXPECTED_TIMEOUT_PATHS} "
            f"bound={self.BOUND_CYCLES})"
        )
        self._log(chk_to)
        sb.expect_eq(
            "CHK-TIMEOUT-PATHS exact count+shape",
            n_paths,
            self.EXPECTED_TIMEOUT_PATHS,
            evidence="CHK-TIMEOUT-PATHS",
        )

        self._step_ts["PASS"] = time.monotonic()
        self._log("SMU_ALL_003 sequence complete (PASS term recorded for NONVAC fence)")

        order = ["S1", "S2", "S3", "S4", "PASS"]
        for step_id in order:
            if step_id not in self._step_ts:
                raise AssertionError(f"CHK-NONVAC missing step term: {step_id}")
        for a, b in zip(order, order[1:]):
            if self._step_ts[a] >= self._step_ts[b]:
                raise AssertionError(f"CHK-NONVAC order fail: {a} not before {b}")
        deltas_ns = [
            int((self._step_ts[b] - self._step_ts[a]) * 1e9) for a, b in zip(order, order[1:])
        ]
        positive_deltas = sum(1 for d in deltas_ns if d > 0)
        if positive_deltas != 4:
            raise AssertionError(
                f"CHK-NONVAC positive-delta count fail: {positive_deltas} deltas_ns={deltas_ns}"
            )
        self._log("CHK-NONVAC: ordered fence S1<S2<S3<S4<PASS all present")
        sb.expect_eq(
            "CHK-NONVAC positive step-delta count",
            positive_deltas,
            4,
            evidence="CHK-NONVAC",
        )
