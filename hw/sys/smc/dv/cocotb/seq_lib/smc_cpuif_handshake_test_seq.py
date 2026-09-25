# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Every PeakRDL register block's AXI-Lite front end, pipelined and skewed.

Each SMC register block is fronted by the same generated AXI-Lite interface. It
keeps up to two transactions in flight, alternates reads and writes, captures AW
and W in separate registers, and holds a response until BREADY or RREADY. Three
parts of that interface have been exercised on only one block --
`smc_sep_in_axi_flow_control_test` drives them, but only on the scratch
registers -- so on every other block they have never run:

* **An accept in the same cycle a response is acknowledged.** The in-flight
  counter increments on an accept and decrements on an acknowledge, and the
  cycle that does both is reachable only when a request is already waiting as
  the previous one's response goes out. Serial traffic never has one waiting.
  Each block here takes an outstanding group of interleaved reads and writes,
  so both the read-side and the write-side accept meet an acknowledge.
* **Write data ahead of its address.** `AxiTimingProfile` with `aw_delay` set
  presents W before AW, so the front end captures W with no AW to pair it with
  -- the `awvalid && wvalid` row with AW low. `cpu_ctrl` and `zeroer_ctrl` also
  take the opposite skew, AW ahead of W, which only those two had not seen.
* **A read arriving on a held write.** The front end dispatches a waiting read
  ahead of a waiting write when the last access was a write, so a read that
  reaches the block in the cycle it registers AW and W holds that write for one
  cycle. If the next write's AW is already behind it, AWREADY is seen low. Each
  block takes a pair of writes and a read with the read's arrival swept over
  twelve offsets, and a single write and a read over the same offsets, which
  lines a read accept up with a write's acknowledge.
* **Mixed groups against a held response.** Eight writes and a read against a
  held BREADY, and eight reads and a write against a held RREADY, queue the
  opposite access behind two unacknowledged ones.
* **A response held against a low ready.** `b_ready_delay` and `r_ready_delay`
  hold BREADY and RREADY low on SEP_IN, but the interconnect in front of each
  block buffers responses and keeps the block's own ready high until that
  buffer is full. So each block takes sixteen writes and then sixteen reads
  outstanding against a long hold, which backs the responses up far enough to
  drop the block's ready. Behind `smc_misc_wrap` and behind the straps window
  the path buffers more than that and the block's ready is never seen to drop;
  those blocks still take the traffic and are still held to the same checks,
  but that row is not claimed for them.

Every access targets one **probe register** per block, and every write carries
back the value that register just read. A probe is chosen so that neither
direction has a side effect: plain read-write fields, where a write of the
value already held changes nothing, or read-only fields, which a write does not
reach. The sequence checks that from the generated contract before it issues
anything -- no field of a probe may carry a read action, a modified-write
action or write-only access -- so a regenerated map cannot turn a probe into a
trigger unnoticed.

The claim for each block is the one a pipelined, skewed, backpressured manager
is owed: every read in every group returns the value the block held, every
write is answered, and the register holds that value at the end. A front end
that dropped, reordered or mis-paired one of the outstanding accesses, or that
mishandled W arriving alone, returns the wrong word or loses the write.

Three blocks need their own handling, and the card records each:

* `straps` is not in the SMC register map; `memmap.adoc` places `STRAPS_LO` at
  the adopter external window plus `0x5800`, and `straps.rdl` makes it
  `sw = r`, so it is a read-only probe reached by address.
* `uart_16550_dl` shares its address window with the main UART registers and
  is only decoded while `LCR.DLAB` is set, so its leg sets DLAB, probes `DLL`,
  and restores `LCR`.
* `uart_16550_main_wo` has no read side of its own -- reads at its addresses
  are the main block's `RBR` and `IIR` -- so it takes writes only, of `FCR = 0`,
  which at reset changes nothing; `IIR.FIFOS_ENABLED` is read afterwards to show
  the FIFOs were never turned on. Its read-side accept rows are not reachable
  from this port and are not claimed.
"""

from __future__ import annotations

import cocotb
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp
from ocah_axi_vip import AxiTimingProfile

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_log_engine_utils import (
    DLL_OFFSET,
    FCR_OFFSET,
    IIR_FIFOS_ENABLED,
    LCR_DLAB,
    uart_base,
    uart_reg,
)
from .smc_rdl_regmap import rdl_contract

# One probe per block: the register every access in that block's legs targets.
# Each is a plain read-write or read-only register with no side effect in
# either direction; `_check_probe` holds that against the generated contract.
_PROBES: tuple[tuple[str, str], ...] = (
    ("chip_config", "smc_misc_wrap/chip_config/VERSION_LO"),
    ("ndm_reset", "smc_misc_wrap/ndm_reset/NDMRESET_CLUSTER_COUNT"),
    ("scratch", "smc_misc_wrap/scratch_cold/SCRATCH[0]"),
    ("gpio_intf", "gpio_intf/ACCESS_FILTER"),
    ("avsbus_controller", "smc_avsbus_controller/AVS_CFG_0"),
    ("i2c", "smc_i2c_wrap/i2c/HOST_FIFO_CONFIG"),
    ("i2c_ctrl", "smc_i2c_wrap/i2c_ctrl_regs/I2C_CTRL[0]"),
    ("uart_log_engine_ctrl", "smc_uart_wrap/uart_log_engine_wrap/uart_log_engine_ctrl/CTRL"),
    ("uart_16550_main", "smc_uart_wrap/uart_log_engine_wrap/uart/SCR"),
    ("log_engine", "smc_uart_wrap/uart_log_engine_wrap/log_engine/LOG_REGION_SIZE"),
    ("telemetry_receiver", "smc_telemetry_receiver_wrap/telemetry_receiver/INTR_ENABLE"),
    ("system_timer_octs", "smc_system_timer_octs/TIMER_PRESET_LO"),
    ("dfx_ctrl_status", "dfx_ctrl/DEBUG_BUS_MUX"),
    ("smc_base_config", "smc_base_config/HANG_DET_SYS_AXI_TIMEOUT_THRESHOLD"),
    ("alias_remap", "smc_alias_remap/REGION/region_start"),
    ("output_remap", "smc_mmode_remap/REGION/region_attrs"),
    ("filter_ctrl", "smc_outbound_filter_ctrl/START_ADDR"),
    ("zeroer_ctrl", "zeroer_ctrl/DEST_ADDR"),
    ("cpu_ctrl", "smc_cpu_ctrl/SCRATCH[15]"),
    ("reset_unit", "smc_reset_unit/SS_CONFIG"),
    ("efuse_interface_ctrl", "efuse_interface_ctrl/EFUSE_READ_REQ_TIMEOUT"),
)

# The only two blocks whose front end had not seen AW ahead of W.
_AW_FIRST_BLOCKS = frozenset({"cpu_ctrl", "zeroer_ctrl"})

# memmap.adoc, "Captured GPIO Straps": STRAPS_LO at the adopter external window
# plus 0x5800. straps.rdl makes it `sw = r`.
_STRAPS_OFFSET = 0x5800

# Cycles each profiled channel is held back. Enough for the front end to
# register the leading channel before the trailing one arrives, and for the
# response to sit on a low ready for several cycles.
_SKEW = 4
_READY_HOLD = 32
# Responses queued behind a held ready. The block keeps two in flight and the
# interconnect in front of it buffers more, so a shallow group is absorbed
# before the block's own ready ever drops; this is deep enough to fill both.
_BP_DEPTH = 16

# Read-arrival offsets swept against a pair of writes (and a single write). The
# block holds a write it has registered for one cycle when a read reaches it at
# the same time and the last access was a write; the next write's AW then finds
# AWREADY low. Which offset lines the read up with that cycle depends on the
# path in front of each block, so every block takes the whole range.
_INTERLEAVE_OFFSETS = range(12)
# Mixed groups against a held response: the opposite access queues behind two
# unacknowledged ones.
_MIXED_DEPTH = 8

# Reads and writes in the outstanding group. Interleaved and more than two
# deep, so the front end has one waiting on each side as it acknowledges.
_GROUP_PAIRS = 3


def _item(
    label: str,
    op: SmcSysAxiOp,
    addr: int,
    width: int,
    *,
    wdata: int = 0,
    expected: int | None = None,
) -> SmcSysAxiItem:
    item = SmcSysAxiItem(f"{op.value}_{label}")
    item.op = op
    item.addr = addr
    item.length = width
    item.wdata = wdata
    item.expected = expected
    return item


class smc_cpuif_handshake_test_seq(SmcCsrSeq):
    """Pipeline, skew and backpressure every register block's front end."""

    def __init__(self, name: str = "smc_cpuif_handshake_test_seq") -> None:
        super().__init__(name)
        self.blocks = 0
        self.groups = 0

    # -- primitives ------------------------------------------------------

    @staticmethod
    def _check_probe(block: str, path: str) -> tuple[int, int]:
        # Instance 0 of every block. Several blocks are instantiated more than
        # once and have no unindexed address symbol, so the contract and the
        # instance-0 address both come from the IP-XACT view; the sweeps that
        # drive these blocks already hold that instance against the indexed map.
        reg = rdl_contract(path)
        for field in reg.fields:
            assert not field.read_action, (
                f"{block}: the probe {path} has field {field.name} with read action "
                f"{field.read_action}, so reading it changes state"
            )
            assert not field.modified_write, (
                f"{block}: the probe {path} has field {field.name} with modified-write "
                f"{field.modified_write}, so writing back its value is not a no-op"
            )
            assert field.access != "write-only", (
                f"{block}: the probe {path} has write-only field {field.name}, which a "
                f"read cannot return"
            )
        return reg.addr, reg.width_bytes

    async def _group(self, name: str, items: list[SmcSysAxiItem], timing=None) -> None:
        group = SmcSysAxiGroupItem(name, items, timing=timing)
        await self.start_item(group)
        await self.finish_item(group)
        self.accesses += len(items)
        self.groups += 1

    async def _legs(self, block: str, addr: int, width: int, *, reads: bool = True) -> None:
        """The three shapes on one probe, every write carrying back what it held."""
        held = await self.csr_read(f"{block}_HELD", addr, length=width) if reads else 0

        def rd(tag: str) -> SmcSysAxiItem:
            return _item(f"{block}_{tag}", SmcSysAxiOp.READ, addr, width, expected=held)

        def wr(tag: str) -> SmcSysAxiItem:
            return _item(f"{block}_{tag}", SmcSysAxiOp.WRITE, addr, width, wdata=held)

        pipelined: list[SmcSysAxiItem] = []
        for index in range(_GROUP_PAIRS):
            if reads:
                pipelined.append(rd(f"pipe_rd{index}"))
            pipelined.append(wr(f"pipe_wr{index}"))
        await self._group(f"{block}_pipelined", pipelined)

        await self._group(f"{block}_w_first", [wr("w_first")], AxiTimingProfile(aw_delay=_SKEW))
        if block in _AW_FIRST_BLOCKS:
            await self._group(
                f"{block}_aw_first", [wr("aw_first")], AxiTimingProfile(w_delay=_SKEW)
            )

        await self._group(
            f"{block}_bready_hold",
            [wr(f"bp_wr{index}") for index in range(_BP_DEPTH)],
            AxiTimingProfile(b_ready_delay=_READY_HOLD),
        )
        if reads:
            await self._group(
                f"{block}_rready_hold",
                [rd(f"bp_rd{index}") for index in range(_BP_DEPTH)],
                AxiTimingProfile(r_ready_delay=_READY_HOLD),
            )

        if reads:
            for offset in _INTERLEAVE_OFFSETS:
                await self._group(
                    f"{block}_wwr{offset}",
                    [wr(f"il_wr{offset}a"), wr(f"il_wr{offset}b"), rd(f"il_rd{offset}")],
                    AxiTimingProfile(ar_delay=offset),
                )
                await self._group(
                    f"{block}_wr{offset}",
                    [wr(f"ack_wr{offset}"), rd(f"ack_rd{offset}")],
                    AxiTimingProfile(ar_delay=offset),
                )
            await self._group(
                f"{block}_mixed_bready_hold",
                [wr(f"mx_wr{index}") for index in range(_MIXED_DEPTH)] + [rd("mx_rd")],
                AxiTimingProfile(b_ready_delay=_READY_HOLD),
            )
            await self._group(
                f"{block}_mixed_rready_hold",
                [rd(f"mx_rd{index}") for index in range(_MIXED_DEPTH)] + [wr("mx_wr")],
                AxiTimingProfile(r_ready_delay=_READY_HOLD),
            )

        if reads:
            after = await self.csr_read(f"{block}_AFTER", addr, length=width, expected=held)
            assert after == held, (
                f"{block}: the probe read 0x{held:x} before its legs and 0x{after:x} after; "
                f"every write carried back the value it held, so nothing may have moved"
            )
        self.blocks += 1

    # -- the special blocks ----------------------------------------------

    async def _straps_legs(self) -> None:
        addr = smc_addr("SMC_TOP_SMC_EXTERNAL_BASE_ADDR") + _STRAPS_OFFSET
        await self._legs("straps", addr, 4)

    async def _uart_dl_legs(self) -> None:
        lcr = uart_reg(0, "LCR")
        saved = await self.csr_read("UART_LCR_SAVED", lcr)
        await self.csr_write("UART_LCR_DLAB", lcr, saved | LCR_DLAB)
        await self._legs("uart_16550_dl", uart_base(0) + DLL_OFFSET, 4)
        await self.csr_write("UART_LCR_RESTORE", lcr, saved)
        await self.csr_read("UART_LCR_RESTORE_RB", lcr, expected=saved)

    async def _uart_main_wo_legs(self) -> None:
        # FCR = 0 is the reset of every FCR field, so each write changes nothing.
        await self._legs("uart_16550_main_wo", uart_base(0) + FCR_OFFSET, 4, reads=False)
        iir = await self.csr_read("UART_IIR_AFTER_WO", uart_reg(0, "IIR"))
        assert iir & IIR_FIFOS_ENABLED == 0, (
            f"IIR reads 0x{iir:x} with FIFOS_ENABLED set after writes of FCR = 0; every "
            f"one of them carried the reset value, so the FIFOs may not have turned on"
        )

    # -- body ------------------------------------------------------------

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        probes = [(block, *self._check_probe(block, path)) for block, path in _PROBES]
        assert len({addr for _b, addr, _w in probes}) == len(probes), (
            "two probes resolve to the same address"
        )

        for block, addr, width in probes:
            await self._legs(block, addr, width)
        await self._straps_legs()
        await self._uart_dl_legs()
        await self._uart_main_wo_legs()

        expected_blocks = len(_PROBES) + 3
        assert self.blocks == expected_blocks, f"{self.blocks} of {expected_blocks} blocks driven"
        sb = getattr(getattr(self, "env", None), "scoreboard", None)
        assert sb is not None, "no scoreboard on this sequence's env"
        assert sb.sys_axi_checks_seen >= self.accesses, (
            f"the scoreboard checked only {sb.sys_axi_checks_seen} SEP_IN AXI item(s) but "
            f"this sequence issued {self.accesses}, so the traffic never reached it"
        )

        cocotb.log.info(
            "CHK-CPUIF-PIPELINED: %d register blocks each took an outstanding group of "
            "interleaved reads and writes on a side-effect-free probe, deep enough that "
            "an accept met an acknowledge on both the read and the write side, and every "
            "read in every group returned the value the block held",
            self.blocks,
        )
        cocotb.log.info(
            "CHK-CPUIF-WRITE-SKEW: every block took a write with W presented %d cycles "
            "ahead of AW, and cpu_ctrl and zeroer_ctrl also one with AW ahead of W; each "
            "carried back the value the probe held and was answered, and the probe held "
            "it afterwards",
            _SKEW,
        )
        cocotb.log.info(
            "CHK-CPUIF-READY-BACKPRESSURE: every block answered %d outstanding writes "
            "with BREADY held low and, where it has a read side, %d outstanding reads with "
            "RREADY held low, %d cycles per response; every read returned the held value, "
            "and the probe of every block with a read side read the same value before and "
            "after all three shapes",
            _BP_DEPTH,
            _BP_DEPTH,
            _READY_HOLD,
        )
