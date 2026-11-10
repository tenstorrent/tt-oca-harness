# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AXI transactions open across a CPU-only core reset and a watchdog-entered warm reset.

Leg A holds core 0 in reset through CPU_CTRL RESET_CTRL while a SEP_IN and a
SYS_IN read of cluster memory are parked behind the bench's R holds. A core
held in reset does not isolate the cluster boundary, so the other cores' MMIO
accesses and L2 frontend traffic continue (cpu.adoc:256-258): the parked reads
complete with OKAY and RLAST, a non-cluster register answers OKAY on both
ports, and after the release every link answers a fresh access with OKAY.

Leg B pulses the SEP watchdog reset input. The watchdog reset term holds the
warm reset for 32 reference clock cycles after the input releases
(clk_rst.adoc:213-216), counted on the reference clock. SEP_IN reads of
SCRATCH_COLD and SYS_OUT writes stay open across the warm edge on cold-domain
targets; no SCRATCH_COLD_WARM access is open across it. Their outcome and the
post-release response codes are measured, never compared (ruling #3341).

The bench's own-domain checkers (u_cpu_mmio_uncore_rst_axi_sva on the cluster
uncore reset, u_misc_warm_axil_sva on the misc wrapper's warm reset) grade the
reset rules and flush their tracking on those resets; the ten primary-reset
checkers keep the open transactions tracked across both. Leg A leaves both
own-domain resets high: the MMIO port stays connected and its uncore-domain
checker keeps grading it while core 0 is held. Leg B takes both low. Rule fires
are $error lines in the simulator log. The bench's shadow of the own-domain
VALID_RESET_LOW conditions is read here so that the fires= field is a
measurement.

Every wait is a bounded count of clk_smc_i (or reference clock) edges; an expiry
fails the leaf with the last AW/W/AR/B/R handshake of the link and the reset
samples, classified on an INFO-CLASSIFY line.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import REGION_SIZE_RESET, cpu_ctrl_u32, smc_addr, smc_indexed_addr
from .smc_cpu_vip_utils import (
    CPU_CTRL_SCRATCH_0,
    CPU_FW_SUCCESS_MAGIC,
    check_cpu_firmware_boot_contract,
)
from .smc_output_fabric_vip_utils import OUTPUT_FABRIC_ADDR, output_fabric_pass_all_cfg_seq

RESET_CTRL = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_CTRL_BASE_ADDR")
CORE0_N = cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__CORE0_RESET_N_N0_SCAN_bm")
BASE_CONFIG_REG = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
# The CLINT lies outside the inbound aperture at the reset REGION_SIZE; 256 MiB covers it,
# as smc_clint_register_test widens it.
REGION_SIZE_256M = 0x1000_0000
SPM_BASE = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR")
SCRATCH_COLD_0 = smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 0)
SCRATCH_COLD_1 = smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 1)
SCRATCH_COLD_WARM_0 = smc_indexed_addr(
    "SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SCRATCH_BASE_ADDR", 0
)
CLINT_MSIP = tuple(
    smc_indexed_addr("SMC_TOP_SMC_CLUSTER_CLINT_MSIP_BASE_ADDR", hart) for hart in range(4)
)

# Cluster-memory words above the hello_world image and below the mailbox line.
SPM_OPEN_SEP = SPM_BASE + 0x8_0000
SPM_OPEN_SYS = SPM_BASE + 0x8_0008
SPM_PROBE = SPM_BASE + 0x8_0010
SPM_WORDS = {
    SPM_OPEN_SEP: 0x6A2A_0000_0000_0001,
    SPM_OPEN_SYS: 0x6A2A_0000_0000_0002,
    SPM_PROBE: 0x6A2A_0000_0000_0003,
}
SPM_PROBE_LEG_B = 0x6A2B_0000_0000_0003
SCRATCH_COLD_WORDS = (0x6B2B_0001, 0x6B2B_0002)
MISC_WARM_WORD = 0x6C2C_0001
SYS_OUT_WORDS = (0x6D2D_0000_0000_0001, 0x6D2D_0000_0000_0002, 0x6D2D_0000_0000_0003)

# The JTAG AXI ingress carries a 2-bit ID (smc_jtag_56_64_2_12_axi_req_t): JTAG_IN IDs stay in 0-3.
# Bench bounds in clk_smc_i edges (reference clock edges for REF_BOUND); none is a spec value.
PARK_BOUND = 4_000
RESET_BOUND = 4_000
TXN_BOUND = 40_000
BOOT_BOUND = 400_000
REF_BOUND = 4_000
FW_POLLS = 2_000
FW_POLL_GAP = 100
DRIVER_TIMEOUT_NS = 10_000_000

# AxPROT and AxCACHE of the SmcSysAxiItem path. The pass-all filter entries leave
# FILTER_CONFIG.allow_ns at 0, so they match only AxPROT[1] == 0 (filter_ctrl.rdl).
AX_PROT = 0
AX_ATTRS = {"lock": 0, "cache": 0b0011, "qos": 0}

# clk_rst.adoc:213-216: the watchdog reset term is held for 32 reference clock
# cycles after its sources release, and the warm reset is its AND.
WARM_HOLD_REF_CYCLES = 32

RESP_NAMES = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR", -1: "TIMEOUT"}

PRIMARY_INSTANCES = (
    "u_sys_in_axi_sva",
    "u_jtag_in_axi_sva",
    "u_sep_in_axi_sva",
    "u_sys_out_axi_sva",
    "u_cpu_front_axi_sva",
    "u_cpu_mmio_axi_sva",
    "u_otp_jtag_axil_sva",
    "u_dtp_csr_axil_sva",
    "u_log_engine_axil_sva",
    "u_periph_axil_sva",
)
OWN_DOMAIN_INSTANCES = ("u_cpu_mmio_uncore_rst_axi_sva", "u_misc_warm_axil_sva")

LINKS = ("SEP_IN", "SYS_IN", "JTAG_IN", "SYS_OUT", "CPU_MMIO", "CPU_FRONT")

STAGES = (
    "setup",
    "legA_open",
    "legA_assert",
    "legA_hold",
    "legA_release",
    "legB_open",
    "legB_enter",
    "legB_release",
    "reconcile",
)

_PIN_CHANNELS = {
    "aw": ("awvalid", "awready", ("awaddr", "awid", "awlen", "awburst")),
    "w": ("wvalid", "wready", ("wlast",)),
    "b": ("bvalid", "bready", ("bresp", "bid")),
    "ar": ("arvalid", "arready", ("araddr", "arid", "arlen", "arburst")),
    "r": ("rvalid", "rready", ("rresp", "rlast", "rid")),
}
_SYS_OUT_CHANNELS = {
    "aw": ("awvalid", "awready", ("awaddr",)),
    "w": ("wvalid", "wready", ()),
    "b": ("bvalid", "bready", ("bresp",)),
    "ar": ("arvalid", "arready", ("araddr",)),
    "r": ("rvalid", "rready", ("rresp",)),
}
_RESET_NETS = (
    "rst_primary_smc_clk_no",
    "tb_cpu_core_reset_n",
    "tb_cpu_uncore_reset_n",
    "tb_rst_warm_smc_clk_n",
    "misc_warm_rst_n",
)


def _sample(sig) -> str:
    value = sig.value
    if isinstance(value, int) or value.is_resolvable:
        return f"{int(value):#x}"
    return str(value)


def _int(sig, label: str) -> int:
    """Two-state `int` variables read back as a Python int; logic nets must be resolvable."""
    value = sig.value
    if isinstance(value, int):
        return value
    assert value.is_resolvable, f"{label} is X/Z: {value}"
    return int(value)


class _LinkWatch:
    """Last AW/W/AR/B/R handshake of one link, sampled on every clk_smc_i edge."""

    def __init__(self, link: str, prefix: str, channels: dict) -> None:
        self.link = link
        self.prefix = prefix
        self.channels = channels
        self.last: dict[str, str] = {ch: "none" for ch in channels}
        self.count: dict[str, int] = {ch: 0 for ch in channels}

    async def run(self) -> None:
        dut = cocotb.top
        sigs = {
            ch: (
                getattr(dut, f"{self.prefix}{valid}"),
                getattr(dut, f"{self.prefix}{ready}"),
                [(name, getattr(dut, f"{self.prefix}{name}")) for name in fields],
            )
            for ch, (valid, ready, fields) in self.channels.items()
        }
        while True:
            await RisingEdge(dut.clk_smc_i)
            await ReadOnly()
            for ch, (valid, ready, fields) in sigs.items():
                v, r = valid.value, ready.value
                if v.is_resolvable and r.is_resolvable and int(v) and int(r):
                    self.count[ch] += 1
                    body = " ".join(f"{name}={_sample(sig)}" for name, sig in fields)
                    self.last[ch] = f"{body} t={get_sim_time('ns')}ns".strip()

    def report(self) -> str:
        return " | ".join(f"{ch.upper()}[{self.last[ch]}]" for ch in self.channels)


class _Txn:
    """One transaction the leaf opened, its edge, and its outcome."""

    def __init__(self, link: str, kind: str, addr: int, axi_id: int, task) -> None:
        self.link = link
        self.kind = kind
        self.addr = addr
        self.axi_id = axi_id
        self.task = task
        self.opened_ns = get_sim_time("ns")
        self.edge = ""
        self.result = None

    @property
    def code(self) -> str:
        if self.result is None:
            return "UNANSWERED"
        return RESP_NAMES.get(self.result.resp, str(self.result.resp))


class smc_axi_partial_reset_open_txn_test_seq(output_fabric_pass_all_cfg_seq):
    """Leg A: core-only reset with reads open; leg B: watchdog warm reset with reads and writes open."""

    def __init__(self, name: str = "smc_axi_partial_reset_open_txn_test_seq") -> None:
        super().__init__(name)
        self.stamps: list[tuple[str, int]] = []
        self.chk_lines: list[str] = []
        self.waits = 0
        self.expired = 0
        self.open_txns: list[_Txn] = []
        self.watch: dict[str, _LinkWatch] = {}
        self.boot: dict[str, object] = {}
        self.leg_a_ok = 0
        self.leg_b_answered = 0
        self.leg_a_counts: dict[str, int] = {}
        self.leg_b_counts: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Bookkeeping
    # ------------------------------------------------------------------
    def _stage(self, stage: str) -> None:
        self.stamps.append((stage, int(get_sim_time("ns"))))
        cocotb.log.info("INFO-STAGE: %s at %d ns", stage, self.stamps[-1][1])

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self.chk_lines.append(chk_id)

    @staticmethod
    def _shadow(name: str) -> int:
        return _int(getattr(cocotb.top, name), name)

    def _own_edges(self) -> int:
        """Edges either own-domain checker spent with its reset low."""
        return self._shadow("axi_uncore_rst_edges") + self._shadow("axi_misc_warm_rst_edges")

    @staticmethod
    def _resets() -> str:
        dut = cocotb.top
        return " ".join(f"{n}={_sample(getattr(dut, n))}" for n in _RESET_NETS)

    def _evidence(self, link: str) -> str:
        watch = self.watch.get(link)
        handshakes = watch.report() if watch is not None else "no pin watch"
        return f"{link} last {handshakes}; resets {self._resets()}"

    def _expire(self, what: str, link: str, classification: str) -> AssertionError:
        self.expired += 1
        cocotb.log.info(
            "INFO-CLASSIFY: %s unanswered within its bound, classification=%s; %s",
            what,
            classification,
            self._evidence(link),
        )
        return AssertionError(
            f"{what} was not answered within its bound ({classification}); {self._evidence(link)}"
        )

    async def _wait_level(self, name: str, want: int, bound: int, link: str) -> int:
        self.waits += 1
        dut = cocotb.top
        sig = getattr(dut, name)
        for edge in range(bound + 1):
            value = sig.value
            if value.is_resolvable and int(value) == want:
                return edge
            await RisingEdge(dut.clk_smc_i)
        raise self._expire(
            f"{name} reaching {want} in {bound} clk_smc_i edges", link, "design-side"
        )

    async def _wait_advance(self, name: str, base: int, bound: int, link: str) -> int:
        self.waits += 1
        dut = cocotb.top
        for _ in range(bound + 1):
            now = self._shadow(name)
            if now > base:
                return now
            await RisingEdge(dut.clk_smc_i)
        raise self._expire(f"{name} advancing past {base} in {bound} edges", link, "design-side")

    async def _wait_txn(self, txn: _Txn, bound: int = TXN_BOUND) -> _Txn:
        self.waits += 1
        for _ in range(bound + 1):
            if txn.task.done():
                txn.result = await txn.task
                if txn.result.timed_out:
                    txn.result = None
                    break
                return txn
            await RisingEdge(cocotb.top.clk_smc_i)
        raise self._expire(
            f"{txn.link} {txn.kind} 0x{txn.addr:x} id={txn.axi_id} opened at {txn.opened_ns} ns "
            f"(edge {txn.edge or 'none'})",
            txn.link,
            "design-side",
        )

    # ------------------------------------------------------------------
    # Transactions through the AXI masters' event API (outside the sequencer,
    # so a transfer stays open while other accesses continue)
    # ------------------------------------------------------------------
    def _axi(self, link: str):
        agent = {
            "SEP_IN": self.env.sep_in_axi_agent,
            "SYS_IN": self.env.sys_in_axi_agent,
            "JTAG_IN": self.env.jtag_axi_agent,
        }[link]
        axi = agent.driver.axi
        assert axi is not None, f"{link}: the AXI master is not attached"
        return axi

    def _read(self, link: str, addr: int, axi_id: int, kind: str = "read") -> _Txn:
        task = cocotb.start_soon(
            self._axi(link).read_bytes_result(
                addr,
                8,
                size=3,
                id=axi_id,
                prot=AX_PROT,
                attrs=AX_ATTRS,
                check_response=False,
                timeout_ns=DRIVER_TIMEOUT_NS,
                allow_timeout=True,
            )
        )
        self.accesses += 1
        return _Txn(link, kind, addr, axi_id, task)

    def _write(self, link: str, addr: int, data: int, axi_id: int, kind: str = "write") -> _Txn:
        task = cocotb.start_soon(
            self._axi(link).write_bytes_result(
                addr,
                data.to_bytes(8, "little"),
                size=3,
                id=axi_id,
                prot=AX_PROT,
                attrs=AX_ATTRS,
                check_response=False,
                timeout_ns=DRIVER_TIMEOUT_NS,
                allow_timeout=True,
            )
        )
        self.accesses += 1
        return _Txn(link, kind, addr, axi_id, task)

    def _open(self, txn: _Txn) -> _Txn:
        self.open_txns.append(txn)
        cocotb.log.info(
            "INFO-OPEN: port=%s kind=%s id=%d addr=0x%x t=%d ns",
            txn.link,
            txn.kind,
            txn.axi_id,
            txn.addr,
            txn.opened_ns,
        )
        return txn

    async def _okay(self, txn: _Txn, expected: int | None = None) -> _Txn:
        await self._wait_txn(txn)
        assert txn.code == "OKAY", (
            f"{txn.link} {txn.kind} 0x{txn.addr:x} answered {txn.code}, want OKAY; "
            f"{self._evidence(txn.link)}"
        )
        if expected is not None:
            assert txn.result.data == expected, (
                f"{txn.link} read 0x{txn.addr:x} returned 0x{txn.result.data:x}, "
                f"want 0x{expected:x} (written by this leaf)"
            )
        if txn.kind == "read":
            assert len(txn.result.resp_list) == 1, (
                f"{txn.link} read 0x{txn.addr:x}: {len(txn.result.resp_list)} R beats for AxLEN 0"
            )
        return txn

    # ------------------------------------------------------------------
    # Probes of every link
    # ------------------------------------------------------------------
    def _mmio_base(self) -> tuple[int, int]:
        return self._shadow("cpu_mmio_rsp_okay"), self._shadow("cpu_mmio_rsp_err")

    async def _fw_progress(self, label: str, base: tuple[int, int]) -> tuple[int, int, str]:
        """Firmware PASS word (cleared before the reset) and the MMIO responses since `base`."""
        okay0, err0 = base
        last = None
        self.waits += 1
        for _ in range(FW_POLLS):
            await self._clk(FW_POLL_GAP)
            last = await self.csr_read(f"{label}_SCRATCH0_POLL", CPU_CTRL_SCRATCH_0)
            if last == CPU_FW_SUCCESS_MAGIC:
                break
        else:
            raise self._expire(
                f"CPU_MMIO firmware PASS store after {label} (last SCRATCH_0="
                f"{'none' if last is None else hex(last)}, mmio okay "
                f"{okay0}->{self._shadow('cpu_mmio_rsp_okay')})",
                "CPU_MMIO",
                "design-side",
            )
        okay = self._shadow("cpu_mmio_rsp_okay") - okay0
        err = self._shadow("cpu_mmio_rsp_err") - err0
        return okay, err, f"SCRATCH_0=0x{last:x} mmio_okay=+{okay} mmio_err=+{err}"

    async def _clk(self, n: int) -> None:
        for _ in range(n):
            await RisingEdge(cocotb.top.clk_smc_i)

    async def _probe_links(
        self, leg: str, spm_word: int, mmio_base: tuple[int, int]
    ) -> dict[str, str]:
        """One fresh access per link; returns the link -> code map."""
        codes: dict[str, str] = {}
        for link, axi_id in (("SEP_IN", 3), ("SYS_IN", 3), ("JTAG_IN", 3)):
            txn = await self._wait_txn(self._read(link, BASE_CONFIG_REG, axi_id))
            codes[link] = txn.code
        write0 = self._shadow("tb_output_axi_write_count")
        out = await self._wait_txn(self._write("JTAG_IN", OUTPUT_FABRIC_ADDR, spm_word, 2))
        await self._wait_advance("tb_output_axi_write_count", write0, TXN_BOUND, "SYS_OUT")
        codes["SYS_OUT"] = out.code
        front_w = await self._wait_txn(self._write("SEP_IN", SPM_PROBE, spm_word, 5))
        front_r = await self._wait_txn(self._read("SEP_IN", SPM_PROBE, 6))
        codes["CPU_FRONT"] = front_r.code if front_w.code == "OKAY" else f"write-{front_w.code}"
        if front_r.code == "OKAY" and front_r.result.data != spm_word:
            codes["CPU_FRONT"] = f"OKAY-data-0x{front_r.result.data:x}"
        okay, err, text = await self._fw_progress(leg, mmio_base)
        codes["CPU_MMIO"] = "OKAY" if okay > 0 and err == 0 else f"okay+{okay}/err+{err}"
        cocotb.log.info(
            "INFO-PROBE: %s fresh access per link %s; CPU_MMIO %s",
            leg,
            " ".join(f"{k}={v}" for k, v in codes.items()),
            text,
        )
        return codes

    async def _misc_leg(self, leg: str) -> str:
        warm0 = self._shadow("axi_hs_misc_warm")
        txn = await self._wait_txn(self._read("SEP_IN", SCRATCH_COLD_WARM_0, 7))
        warm = self._shadow("axi_hs_misc_warm") - warm0
        cocotb.log.info(
            "INFO-PROBE: %s misc leg SCRATCH_COLD_WARM read %s data=%s handshakes=+%d",
            leg,
            txn.code,
            "n/a" if txn.result is None else hex(txn.result.data),
            warm,
        )
        assert warm > 0, f"{leg}: the SCRATCH_COLD_WARM read reached no misc warm-leg handshake"
        return txn.code

    # ------------------------------------------------------------------
    # Body
    # ------------------------------------------------------------------
    async def body(self) -> None:
        dut = cocotb.top
        for link, prefix, channels in (
            ("SEP_IN", "s_axi_", _PIN_CHANNELS),
            ("SYS_IN", "sys_axi_", _PIN_CHANNELS),
            ("JTAG_IN", "jtag_axi_", _PIN_CHANNELS),
            ("SYS_OUT", "tb_output_axi_", _SYS_OUT_CHANNELS),
        ):
            self.watch[link] = _LinkWatch(link, prefix, channels)
            cocotb.start_soon(self.watch[link].run())

        # S2 SETUP
        self.boot = await check_cpu_firmware_boot_contract(self, require_image=True)
        assert self.boot.get("boot_checked") is True, f"firmware boot was not checked: {self.boot}"
        await self.program_inbound_pass_all()
        await self.program_outbound_pass_all()
        cocotb.log.info(
            "INFO-FILTER: inbound/outbound entry 0 pass-all, allow_ns=0 (matches AxPROT[1]=0 only); "
            "the open-transaction masters drive AxPROT=%d AxCACHE=0x%x as the SmcSysAxiItem path "
            "does, so a SYS_IN access with AxPROT[1]=1 matches no entry and answers DECERR",
            AX_PROT,
            AX_ATTRS["cache"],
        )
        reset_ctrl = await self.csr_read("RESET_CTRL_SETUP", RESET_CTRL, length=8)
        assert reset_ctrl & CORE0_N, f"core0_reset_n is not 1 at setup: RESET_CTRL=0x{reset_ctrl:x}"
        for addr, word in SPM_WORDS.items():
            await self.csr_write(f"SPM_PRELOAD_{addr:x}", addr, word, length=8)
        await self.csr_write("MISC_WARM_SETUP", SCRATCH_COLD_WARM_0, MISC_WARM_WORD)
        await self.csr_read("MISC_WARM_SETUP_RB", SCRATCH_COLD_WARM_0, expected=MISC_WARM_WORD)
        for i, word in enumerate(SCRATCH_COLD_WORDS):
            await self.csr_write(
                f"SCRATCH_COLD_{i}_SETUP", (SCRATCH_COLD_0, SCRATCH_COLD_1)[i], word
            )
        self._stage("setup")

        # S3 LEG A OPEN. The released core 0 restarts at its reset vector and
        # waits in __metal_synchronize_harts for harts 1-3; their MSIP bits are
        # set here, before the core reset, so no cluster request is made while
        # it is held. SCRATCH_0 is cleared so the PASS store after the release
        # is this run's.
        await self.csr_write("REGION_SIZE_256M", BASE_CONFIG_REG, REGION_SIZE_256M)
        await self.csr_read("REGION_SIZE_256M_RB", BASE_CONFIG_REG, expected=REGION_SIZE_256M)
        for hart in (1, 2, 3):
            await self.csr_write(f"MSIP{hart}_SET", CLINT_MSIP[hart], 1)
            await self.csr_read(f"MSIP{hart}_SET_RB", CLINT_MSIP[hart], expected=1)
        await self.csr_write("REGION_SIZE_RESTORE", BASE_CONFIG_REG, REGION_SIZE_RESET)
        await self.csr_read("REGION_SIZE_RESTORE_RB", BASE_CONFIG_REG, expected=REGION_SIZE_RESET)
        await self.csr_write("LEGA_SCRATCH0_CLEAR", CPU_CTRL_SCRATCH_0, 0)
        await self.csr_read("LEGA_SCRATCH0_CLEAR_RB", CPU_CTRL_SCRATCH_0, expected=0)
        dut.tb_sep_axi_r_hold.value = 1
        dut.tb_sys_axi_r_hold.value = 1
        open_a = [
            self._open(self._read("SEP_IN", SPM_OPEN_SEP, 1, "cluster-read")),
            self._open(self._read("SYS_IN", SPM_OPEN_SYS, 1, "cluster-read")),
        ]
        await self._wait_level("tb_sep_axi_r_raw_valid", 1, PARK_BOUND, "SEP_IN")
        await self._wait_level("tb_sys_axi_r_raw_valid", 1, PARK_BOUND, "SYS_IN")
        self._stage("legA_open")

        # S4 LEG A ASSERT
        edges0 = self._own_edges()
        front_held0 = self._shadow("axi_cpu_front_core_held_hs")
        hits0 = self._shadow("axi_own_rst_valid_hits")
        isolate_seen = {"req": 0, "mmio_isolated": 0, "uncore_low": 0}

        async def _isolate_monitor() -> None:
            while True:
                await RisingEdge(dut.clk_smc_i)
                if _int(dut.tb_cpu_isolate_req, "tb_cpu_isolate_req"):
                    isolate_seen["req"] = 1
                if _int(dut.tb_cpu_mmio_isolated, "tb_cpu_mmio_isolated"):
                    isolate_seen["mmio_isolated"] = 1
                if not _int(dut.tb_cpu_uncore_reset_n, "tb_cpu_uncore_reset_n"):
                    isolate_seen["uncore_low"] = 1

        iso_task = cocotb.start_soon(_isolate_monitor())
        await self.csr_write("RESET_CTRL_CORE0_LO", RESET_CTRL, reset_ctrl & ~CORE0_N, length=8)
        await self._wait_level("tb_cpu_core_reset_n", 0, RESET_BOUND, "CPU_MMIO")
        edge_ns = get_sim_time("ns")
        mmio_hs0 = self._shadow("axi_hs_cpu_mmio_uncore_rst")
        for txn in open_a:
            txn.edge = f"legA@{edge_ns}ns"
        pending = (
            _int(dut.tb_cpu_mmio_pending_aw, "tb_cpu_mmio_pending_aw"),
            _int(dut.tb_cpu_mmio_pending_w, "tb_cpu_mmio_pending_w"),
            _int(dut.tb_cpu_mmio_pending_ar, "tb_cpu_mmio_pending_ar"),
        )
        cocotb.log.info(
            "OBS-G2-CPU-RST-NET: legA edge t=%d ns %s; open at edge %s (observation; open: "
            "which reset is the AXI reset of each CPU port)",
            edge_ns,
            self._resets(),
            [(t.link, t.task.done()) for t in open_a],
        )
        cocotb.log.info(
            "OBS-G2-HELD-CORE-OWN-TXN: MMIO isolate pending aw/w/ar at the core reset edge = "
            "%d/%d/%d; open own transactions at the edge=%d (observation; open: the fate of a "
            "held core's open MMIO transaction; ruling #2449)",
            *pending,
            pending[0] + pending[2],
        )
        self._stage("legA_assert")

        # S5 LEG A HOLD
        dut.tb_sep_axi_r_hold.value = 0
        dut.tb_sys_axi_r_hold.value = 0
        for txn in open_a:
            await self._okay(txn, SPM_WORDS[txn.addr])
        fresh = [
            await self._okay(self._read("SEP_IN", BASE_CONFIG_REG, 2)),
            await self._okay(self._read("SYS_IN", BASE_CONFIG_REG, 2)),
        ]
        assert _int(dut.tb_cpu_core_reset_n, "tb_cpu_core_reset_n") == 0, (
            "core 0 left reset before the held-core checks finished"
        )
        iso_task.cancel()
        assert not any(isolate_seen.values()), (
            f"the MMIO port left the connected state during a core-only reset: {isolate_seen} "
            f"(cpu.adoc:256-258)"
        )
        self._chk(
            "CHK-G2-CORE-HELD-TRAFFIC",
            f"open_completed={len(open_a)} fresh_ok={len(fresh)} isolate_req=0 mmio_isolated=0 "
            f"uncore_reset_n=1 (SEP_IN/SYS_IN cluster reads opened before the core reset completed "
            f"OKAY with RLAST and their data; SMC_BASE_CONFIG answered OKAY on both ports while "
            f"core 0 was held; the MMIO port and its uncore reset stayed connected and high on "
            f"every edge of the hold)",
        )
        self._stage("legA_hold")

        # S6 LEG A RELEASE
        mmio_a = self._mmio_base()
        await self.csr_write("RESET_CTRL_CORE0_HI", RESET_CTRL, reset_ctrl | CORE0_N, length=8)
        await self._wait_level("tb_cpu_core_reset_n", 1, RESET_BOUND, "CPU_MMIO")
        front_held = self._shadow("axi_cpu_front_core_held_hs") - front_held0
        cocotb.log.info(
            "OBS-G2-FRONT-PORT-DOMAIN: u_cpu_front_axi_sva graded %d AW/AR handshakes while "
            "tb_cpu_core_reset_n was 0 (observation, evidence for which reset is the AXI reset "
            "of each CPU port)",
            front_held,
        )
        cocotb.log.info(
            "OBS-G2-CORE-HELD-MMIO: u_cpu_mmio_uncore_rst_axi_sva graded %d AW/AR handshakes "
            "while core 0 was held (observation)",
            self._shadow("axi_hs_cpu_mmio_uncore_rst") - mmio_hs0,
        )
        codes_a = await self._probe_links("LEGA", SPM_WORDS[SPM_PROBE], mmio_a)
        misc_a = await self._misc_leg("LEGA")
        bad_a = {k: v for k, v in codes_a.items() if v != "OKAY"}
        assert not bad_a and misc_a == "OKAY", (
            f"leg A fresh access not OKAY: {bad_a} misc={misc_a} (core-only reset leaves the "
            f"boundary connected, cpu.adoc:256-258)"
        )
        self.leg_a_ok = len(codes_a)
        self.leg_a_counts = {
            "edges": self._own_edges() - edges0,
            "hits": self._shadow("axi_own_rst_valid_hits") - hits0,
        }
        self._stage("legA_release")

        # S7 LEG B OPEN: cold-domain targets only; no SCRATCH_COLD_WARM access is open.
        await self.csr_write("LEGB_SCRATCH0_CLEAR", CPU_CTRL_SCRATCH_0, 0)
        await self.csr_read("LEGB_SCRATCH0_CLEAR_RB", CPU_CTRL_SCRATCH_0, expected=0)
        edges_b0 = self._own_edges()
        msr0 = self._shadow("cpu_mmio_msr_first_edges")
        hits_b0 = self._shadow("axi_own_rst_valid_hits")
        dut.tb_sep_axi_r_hold.value = 1
        dut.tb_output_axi_resp_hold.value = 1
        aw0 = self.watch["SYS_OUT"].count["aw"]
        open_b = [
            self._open(self._read("SEP_IN", SCRATCH_COLD_0, 1, "cold-read")),
            self._open(self._read("SEP_IN", SCRATCH_COLD_1, 2, "cold-read")),
            self._open(
                self._write("JTAG_IN", OUTPUT_FABRIC_ADDR, SYS_OUT_WORDS[0], 1, "sys-out-write")
            ),
            self._open(
                self._write("JTAG_IN", OUTPUT_FABRIC_ADDR + 8, SYS_OUT_WORDS[1], 2, "sys-out-write")
            ),
        ]
        await self._wait_level("tb_sep_axi_r_raw_valid", 1, PARK_BOUND, "SEP_IN")
        self.waits += 1
        for _ in range(PARK_BOUND):
            if self.watch["SYS_OUT"].count["aw"] >= aw0 + 1:
                break
            await RisingEdge(dut.clk_smc_i)
        else:
            raise self._expire(
                "the first SYS_OUT AW handshake of the leg B writes", "SYS_OUT", "design-side"
            )
        self._stage("legB_open")

        # S8 LEG B ENTER
        mmio_b = self._mmio_base()
        assert _int(dut.tb_rst_warm_smc_clk_n, "tb_rst_warm_smc_clk_n") == 1, (
            "warm reset already low"
        )
        dut.tb_sep_wdt_reset_n.value = 0
        await self._wait_level("tb_rst_warm_smc_clk_n", 0, RESET_BOUND, "SEP_IN")
        warm_ns = get_sim_time("ns")
        for txn in open_b:
            txn.edge = f"legB@{warm_ns}ns"
        cocotb.log.info(
            "OBS-G2-MISC-WARM-LEG: legB edge t=%d ns misc_warm_rst_n=%s tb_rst_warm_smc_clk_n=%s "
            "(observation; open: whether the warm scratch leg follows the warm or primary reset)",
            warm_ns,
            _sample(dut.misc_warm_rst_n),
            _sample(dut.tb_rst_warm_smc_clk_n),
        )
        open_at_warm = [
            (t.link, t.kind, hex(t.addr), "done" if t.task.done() else "open") for t in open_b
        ]
        cocotb.log.info("INFO-OPEN: at the warm edge %s; %s", open_at_warm, self._resets())
        await self._wait_level("misc_warm_rst_n", 0, RESET_BOUND, "SEP_IN")
        await self._wait_level("tb_cpu_uncore_reset_n", 0, RESET_BOUND, "CPU_MMIO")
        await self._clk(2)
        cocotb.log.info(
            "OBS-G2-MSR-FIRST-EDGE: CPU MMIO {AWVALID,WVALID,ARVALID} on the first edge that "
            "sampled the uncore reset low = %s (first-edge samples +%d) (observation, ruling #3170)",
            _sample(dut.cpu_mmio_msr_first_edge_valid),
            self._shadow("cpu_mmio_msr_first_edges") - msr0,
        )
        dut.tb_sep_wdt_reset_n.value = 1
        ref_cycles = 0
        self.waits += 1
        for _ in range(REF_BOUND):
            await RisingEdge(dut.clk_ref)
            if _int(dut.tb_rst_warm_smc_clk_n, "tb_rst_warm_smc_clk_n") == 1:
                break
            ref_cycles += 1
        else:
            raise self._expire(
                f"warm reset release in {REF_BOUND} reference clock edges", "SEP_IN", "design-side"
            )
        assert ref_cycles == WARM_HOLD_REF_CYCLES, (
            f"warm reset released {ref_cycles} reference clock cycles after tb_sep_wdt_reset_n "
            f"released, want {WARM_HOLD_REF_CYCLES} (clk_rst.adoc:213-216)"
        )
        self._chk(
            "CHK-G2-WARM-ENTRY",
            f"ref_cycles_after_release={ref_cycles} (want {WARM_HOLD_REF_CYCLES}, clk_rst.adoc:213-216; "
            f"tb_rst_warm_smc_clk_n asserted at {warm_ns} ns while tb_sep_wdt_reset_n was low)",
        )
        self._stage("legB_enter")

        # S9 LEG B RELEASE
        await self._wait_level("misc_warm_rst_n", 1, RESET_BOUND, "SEP_IN")
        dut.tb_sep_axi_r_hold.value = 0
        dut.tb_output_axi_resp_hold.value = 0
        for txn in open_b:
            await self._wait_txn(txn)
        cocotb.log.info(
            "OBS-G2-WARM-OPEN-TXN: %s; %s (observation; open: the fate of transactions open "
            "when a watchdog warm reset asserts; ruling #3341)",
            " ".join(f"{t.link}:{t.kind}:0x{t.addr:x}={t.code}" for t in open_b),
            self._resets(),
        )
        await self._wait_level("tb_cpu_cluster_isolate", 0, BOOT_BOUND, "CPU_FRONT")
        codes_b = await self._probe_links("LEGB", SPM_PROBE_LEG_B, mmio_b)
        cold = await self._wait_txn(self._read("SEP_IN", SCRATCH_COLD_0, 8))
        misc_b = await self._misc_leg("LEGB")
        cocotb.log.info(
            "OBS-G2-WARM-OPEN-TXN: legB post-release codes %s SCRATCH_COLD=%s misc_leg=%s "
            "(observation; open: whether the fabric serves new traffic after warm release)",
            " ".join(f"{k}={v}" for k, v in codes_b.items()),
            cold.code,
            misc_b,
        )
        self.leg_b_answered = len(codes_b)
        self.leg_b_counts = {
            "edges": self._own_edges() - edges_b0,
            "hits": self._shadow("axi_own_rst_valid_hits") - hits_b0,
        }
        assert self.leg_a_ok == len(LINKS) and self.leg_b_answered == len(LINKS)
        self._chk(
            "CHK-G2-LIVENESS",
            f"legA_ok={self.leg_a_ok} legB_answered={self.leg_b_answered} links={','.join(LINKS)} "
            f"(leg A codes all OKAY; leg B codes are OBS)",
        )
        track_b = {k: codes_b[k] for k in ("CPU_FRONT", "CPU_MMIO")} | {"MISC_LEG": misc_b}
        assert all(v == "OKAY" for v in track_b.values()), (
            f"leg B first fresh access on an own-domain or front link not OKAY: {track_b}"
        )
        self._chk(
            "CHK-G2-TRACK-CLEARED",
            "legA=ok legB=ok (first fresh access after each release on CPU_FRONT, CPU_MMIO and "
            "the misc warm leg answered OKAY; tracking rule fires are $error lines of the log)",
        )
        self._stage("legB_release")

        # S10 RECONCILE
        completed = [t for t in self.open_txns if t.result is not None]
        unanswered = [t for t in self.open_txns if t.result is None]
        for txn in unanswered:
            cocotb.log.info(
                "INFO-CLASSIFY: unanswered %s %s 0x%x edge=%s; %s",
                txn.link,
                txn.kind,
                txn.addr,
                txn.edge,
                self._evidence(txn.link),
            )
        n = len(self.open_txns)
        assert n > 0 and len(completed) + len(unanswered) == n
        assert not unanswered, (
            f"{len(unanswered)} transaction(s) open at a reset edge never answered"
        )
        self._chk(
            "CHK-G2-PRIMARY-RECONCILED",
            f"open_at_edges={n} completed={len(completed)} unanswered_recorded={len(unanswered)} "
            + " ".join(f"{t.link}:{t.kind}:{t.edge}={t.code}" for t in self.open_txns),
        )
        legs = (self.leg_a_counts, self.leg_b_counts)
        fires = self._shadow("axi_own_rst_valid_hits")
        if fires:
            cocotb.log.info(
                "INFO-CLASSIFY: %d own-domain VALID-in-reset sample(s) (legA +%d legB +%d), "
                "classification=design-side; %s",
                fires,
                legs[0]["hits"],
                legs[1]["hits"],
                self._resets(),
            )
        assert legs[0]["edges"] == 0, (
            f"an own-domain reset went low during the core-only leg: {legs} (cpu.adoc:256-258)"
        )
        assert legs[1]["edges"] > 0, f"the warm leg sampled no own-domain reset edge: {legs}"
        assert fires == 0, f"{fires} own-domain *_VALID_RESET_LOW condition sample(s)"
        self._chk(
            "CHK-G2-RESET-VALID-LOW",
            f"legA_edges=0 legB_edges={legs[1]['edges']} fires=0 (the core-only leg left the "
            f"uncore and misc warm resets high; the warm leg took both low with no VALID in reset)",
        )
        enabled = {}
        for inst in PRIMARY_INSTANCES + OWN_DOMAIN_INSTANCES:
            enabled[inst] = _int(getattr(dut, inst).en_i, f"{inst}.en_i")
        off = [k for k, v in enabled.items() if v != 1]
        assert len(enabled) == 12 and not off, f"checker instance(s) not enabled: {off}"
        self._chk(
            "CHK-G2-ALL-SILENT",
            f"instances={len(enabled)} fires={fires} (all en_i=1; own-domain VALID_RESET_LOW "
            f"shadow 0; every other rule fire is an $error line the log scan grades)",
        )
        self._stage("reconcile")

        # S11
        self._chk("CHK-TIMEOUT-PATHS", f"waits={self.waits} expired={self.expired}")
        assert self.expired == 0
        order = [s for s, _ in self.stamps]
        assert order == list(STAGES), f"stage order {order}, want {list(STAGES)}"
        # reconcile only evaluates what the earlier stages recorded, so it shares
        # legB_release's sim time; every stage that waits on the bench advances it.
        times = [t for _, t in self.stamps]
        assert all(b > a for a, b in zip(times[:-1], times[1:-1])) and times[-1] >= times[-2], (
            f"stage times not increasing: {times}"
        )
        cocotb.log.info(
            "CHK-NONVAC: %s",
            " -> ".join(f"{s}@{t}ns" for s, t in self.stamps),
        )
