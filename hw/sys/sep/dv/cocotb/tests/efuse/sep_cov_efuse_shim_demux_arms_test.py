# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Both arms of the eFuse-shim demux, across AXI IDs and outstanding depth.

``u_efuse_shim_demux`` (``hw/sys/sep/rtl/sep.sv``) is an ``axi_demux`` on the
crossbar ``sep_external`` master port. ``ext_demux_decode`` selects arm 1, the
eFuse shim CSR window, for the generated
``SEP_EXTERNAL_EFUSE_SHIM_CTRL_REG_MAP`` aperture, and arm 0, every other
``sep_external`` address, which leaves SEP and is terminated by the extension
error slave with DECERR. Both arms answer, and
``sep_address_map_test`` already establishes that the CPU-LSU bus reaches each
of them. What no test presents is the demux' multi-ID, multi-outstanding
logic: its per-ID AW and AR counters have only ever held ID 0 at depth one,
and ``AxLEN`` is zero on every port of both crossbars.

The stimulus alternates between the two arms while sweeping the AXI ID field,
holds several transactions outstanding, and drives multi-beat INCR bursts.

Two masters, both real DUT ports:

* CPU-LSU (``s_axi``), whose ID field is 3 bits wide. Its leg is one access at
  a time, so it runs through the agent sequencer. A DECERR on this bus is
  otherwise a decode bug, so the arm-0 accesses are marked ``allow_error`` and
  the expected count is armed on the monitor, and handed back when a probe did
  not produce one.
* SMN-inbound external (``m_axi``), whose ID field is 6 bits wide and whose
  monitor tallies DECERR without failing. The wide ID sweep and the bursts
  run there, driven at the VIP master directly: the sequencer retires one item
  at a time, so nothing would overlap.

``+skip_fuse_sense`` leaves the shadow array at zero, so ``SYS_DIS`` bit 0
(``SEP_DBG``) is clear, ``feat_ctrl.sep_debug`` is 1 and the inbound filter
passes the external master. No disable vector is programmed.
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import sym
from seq_lib.sep_cov_efuse_iface_seq import cov_master
from seq_lib.sep_cov_remap_filter_seq import cov_read_seq, cov_write_seq

# Arm 1: the generated shim window. Arm 0: everything else in the external
# aperture, which the extension error slave terminates.
SHIM_BASE = sym("SEP_EXTERNAL_EFUSE_SHIM_CTRL_REG_MAP_BASE_ADDR")
SHIM_SIZE = sym("SEP_EXTERNAL_EFUSE_SHIM_CTRL_REG_MAP_SIZE")

# Arm-0 offsets from the shim base, spread across the aperture so the demux
# select is driven from several address bits rather than one. All are past the
# shim window and inside the external region.
EXTERNAL_OFFSETS = (0x0000_0100, 0x0001_0000, 0x0100_0000, 0x0F00_0000, 0x1000_0000)

LSU_ID_BITS = 3
EXT_ID_BITS = 6

# Outstanding depth the overlap leg presents. The demux is built with
# MaxTrans = 4, so more than four in flight is where its per-ID counters stop
# being a pass-through.
OUTSTANDING = 6

_ACCESS_TIMEOUT_NS = 20_000
RESP_DECERR = 3


@pyuvm.test()
class sep_cov_efuse_shim_demux_arms_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more."""

    stimulus_only = True

    def _arm0_addr(self, index: int) -> int:
        return SHIM_BASE + EXTERNAL_OFFSETS[index % len(EXTERNAL_OFFSETS)]

    async def _lsu_access(self, *, write: bool, addr: int, axi_id: int, decerr: bool) -> None:
        """One single-beat CPU-LSU access through the agent.

        An arm-0 address is answered by the extension error slave, so the item
        carries ``allow_error`` and the monitor is credited one DECERR beat.
        The credit is speculative: one left standing would absorb the next
        unexpected DECERR on this bus, so it is handed back when the access did
        not produce one.
        """
        mon = getattr(self.env, "axi_monitor", None)
        if decerr and mon is not None:
            mon.arm_expected_decerr(1)
        if write:
            seq = cov_write_seq(addr, 0x5A5A_0000 | axi_id, axi_id=axi_id, allow_error=decerr)
        else:
            seq = cov_read_seq(addr, axi_id=axi_id, allow_error=decerr)
        await self.start_seq(seq)
        if decerr and mon is not None and seq.resp_code != RESP_DECERR:
            mon.release_expected_decerr(1)

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        rng = SepSeededRng(self.random_seed())

        # Leg 1: alternate the two arms on the CPU-LSU bus, one AXI ID per
        # access, reads and writes, over the whole 3-bit ID field.
        for axi_id in range(1 << LSU_ID_BITS):
            await self._lsu_access(write=False, addr=SHIM_BASE, axi_id=axi_id, decerr=False)
            await self._lsu_access(
                write=False, addr=self._arm0_addr(axi_id), axi_id=axi_id, decerr=True
            )
            await self._lsu_access(write=True, addr=SHIM_BASE, axi_id=axi_id, decerr=False)
            await self._lsu_access(
                write=True, addr=self._arm0_addr(axi_id + 1), axi_id=axi_id, decerr=True
            )
        self.logger.info(
            "[cov] CPU-LSU leg done: %d IDs x (shim arm, external arm) x (read, write)",
            1 << LSU_ID_BITS,
        )

        ext = cov_master(self, "m_axi")
        if ext is None:
            self.logger.info(
                "[cov] no VIP master behind env.ext_axi_agent.driver; the wide-ID "
                "and multi-beat legs are not driven in this build"
            )
            return

        # Leg 2: the external master, whose ID field is 6 bits. Several reads
        # in flight at once, alternating arms, so the demux' per-ID AR counter
        # holds more than one ID at a time.
        for base_id in range(0, 1 << EXT_ID_BITS, OUTSTANDING):
            ids = [(base_id + k) & ((1 << EXT_ID_BITS) - 1) for k in range(OUTSTANDING)]
            tasks = [
                cocotb.start_soon(
                    ext.read_bytes_result(
                        SHIM_BASE if (k % 2 == 0) else self._arm0_addr(k),
                        4,
                        size=2,
                        id=axi_id,
                        check_response=False,
                        timeout_ns=_ACCESS_TIMEOUT_NS,
                        allow_timeout=True,
                    )
                )
                for k, axi_id in enumerate(ids)
            ]
            for task in tasks:
                await task
        self.logger.info(
            "[cov] external read leg done: %d IDs, %d outstanding per group",
            1 << EXT_ID_BITS,
            OUTSTANDING,
        )

        # Leg 3: multi-beat INCR bursts on both arms, so the demux' beat
        # counter and W-channel last-beat logic move. The beat count and the ID
        # are a seeded choice, so a failing leaf replays with
        # `--stage sim --seed N`.
        beat_counts = (2, 4, 8)
        for k in range(8):
            beats = beat_counts[rng.randrange(len(beat_counts))]
            axi_id = rng.randrange(1 << EXT_ID_BITS)
            addr = SHIM_BASE if (k % 2 == 0) else self._arm0_addr(k)
            await ext.read_bytes_result(
                addr,
                4 * beats,
                size=2,
                id=axi_id,
                check_response=False,
                timeout_ns=_ACCESS_TIMEOUT_NS,
                allow_timeout=True,
            )
            await ext.write_bytes_result(
                addr,
                bytes((0xA5 + i) & 0xFF for i in range(4 * beats)),
                size=2,
                id=axi_id,
                check_response=False,
                timeout_ns=_ACCESS_TIMEOUT_NS,
                allow_timeout=True,
            )
        self.logger.info("[cov] external multi-beat leg done: 8 read/write burst pairs")
