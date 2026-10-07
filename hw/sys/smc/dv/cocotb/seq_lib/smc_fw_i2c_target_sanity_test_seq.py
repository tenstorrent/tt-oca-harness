# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""i2c_target_sanity with the bench as the external host for its UNEXP_STOP step.

`fw/tests/i2c_target_sanity` (DV-TESTCASE-CONTRACT SMC_I2C_005, ENV c-fw) runs
I2C_0 as controller against I2C_1 as target through S1..S5 -- ADDR0 match, dual
address, ACQ write, TX read, TX stretch control -- all CPU-driven and CPU-graded.
Its S6 needs a host the OpenTitan controller cannot be: one that ends a read
with a STOP but no NACK, so the target raises UNEXP_STOP. The image disables
I2C_0, publishes 0xEBEDEBE3 in SCRATCH_1 and waits for INTR_STATE.UNEXP_STOP.

The bench is that host. A marker watcher on SCRATCH_1 sees the word and drives
the illegal read on the shared pads with SmcI2cMasterVip: START, 0x10 with the
read bit, one data byte, then the STOP inside that byte's acknowledge clock --
the host drives the ACK level, lets SCL rise, and releases SDA while SCL is
still high. That is the only place a STOP can land without a NACK before it:
once the acknowledge clock completes the target is already presenting its next
bit, so a host pull on SDA is a lost transfer to it rather than an unexpected
STOP, and a host that acknowledges every byte it reads ends against an empty TX
FIFO with the target stretching SCL (INTR_STATE.TX_STRETCH). The image preloads
two bytes (0x77, 0x88); the host reads the first, which is data the DUT clocked
out onto the wire, and the firmware's UNEXP_STOP check is the other half of the
same event.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import SimTimeoutError, Timer, with_timeout

from .smc_addr_map import smc_indexed_addr
from .smc_fw_i2c_pair_test_seq import WireFloor, smc_fw_i2c_pair_test_seq
from .smc_fw_scratch_marker_watch import MarkerStep, smc_fw_scratch_marker_watch
from .smc_i2c_protocol_vip import SmcI2cMasterVip

# step_s6_unexp_stop(): write_scratch(1, 0xEBEDEBE3) after releasing I2C_0.
S6_MARKER = 0xEBED_EBE3
TARGET_ADDR0 = 0x10
TARGET_ADDR1 = 0x20
TARGET_IDX = 1
_TARGET_DIAG_REGS = (
    "CTRL",
    "STATUS",
    "INTR_STATE",
    "TARGET_EVENTS",
    "TARGET_FIFO_STATUS",
    "TARGET_ACK_CTRL",
    "TARGET_TIMEOUT_CTRL",
)
# preload_tx(expect, 2) in step_s6_unexp_stop(); the host reads the first only.
S6_TX_PRELOAD = (0x77, 0x88)
S6_HOST_READS = S6_TX_PRELOAD[:1]
# The host read is ~30 bit times at 100 kHz; the bound is generous so a bus held
# low by some other pull fails here, naming the pull, instead of running into
# the firmware's own S6 bound.
S6_HOST_READ_BOUND_NS = 2_000_000
_BUS_SIGNALS = (
    "tb_i2c0_scl",
    "tb_i2c0_sda",
    "tb_i2c0_scl_dut_low",
    "tb_i2c1_scl_dut_low",
    "tb_i2c2_scl_dut_low",
    "tb_i2c0_scl_ext_low",
    "tb_i2c0_sda_dut_low",
    "tb_i2c1_sda_dut_low",
    "tb_i2c0_sda_ext_low",
)


def _bus_state() -> str:
    dut = cocotb.top
    return " ".join(f"{n}={int(getattr(dut, n).value)}" for n in _BUS_SIGNALS)


class smc_fw_i2c_target_sanity_test_seq(smc_fw_i2c_pair_test_seq):
    """Boot the target-sanity image and play the illegal-STOP host for S6."""

    tag = "I2C-TARGET-SANITY"
    # The image reaches PASS ~2.76 ms after release (~5500 polls at a 5 ns
    # clk_smc_i): S1..S5 at standard-mode bus speed, then the bench host's read
    # in S6. 50_000 is ~9x that.
    poll_iterations = 50_000
    floors = (
        WireFloor(TARGET_ADDR0, None, min_frames=2),
        WireFloor(TARGET_ADDR1, None, min_frames=1),
    )

    def __init__(self, name: str = "smc_fw_i2c_target_sanity_test_seq") -> None:
        super().__init__(name)
        self.watch: smc_fw_scratch_marker_watch | None = None
        self._watch_task = None
        self.vip_addr_acked: bool | None = None
        self.vip_bytes: tuple[int, ...] | None = None
        self.vip_read_ok = False

    async def before_boot(self) -> None:
        await super().before_boot()
        self.watch = smc_fw_scratch_marker_watch(
            "fw_i2c_target_sanity_s6_watch",
            [MarkerStep(S6_MARKER, self._illegal_stop_read)],
        )
        self.watch.cfg = self.cfg
        self.watch.env = self.env
        self._watch_task = cocotb.start_soon(self.watch.start(self.sequencer))

    async def _illegal_stop_read(self) -> None:
        cocotb.log.info("S6 host: bus before START: %s", _bus_state())
        try:
            await with_timeout(self._drive_illegal_stop_read(), S6_HOST_READ_BOUND_NS, "ns")
        except SimTimeoutError as exc:
            bus = _bus_state()
            raise AssertionError(
                f"S6 host read did not finish within {S6_HOST_READ_BOUND_NS} ns; bus: {bus}; "
                f"I2C_{TARGET_IDX} {await self._target_regs()}"
            ) from exc

    async def _drive_illegal_stop_read(self) -> None:
        vip = SmcI2cMasterVip(name="smc_fw_i2c_target_sanity_host")
        await vip.send_start()
        await Timer(1, "ns")
        cocotb.log.info("S6 host: bus after START: %s", _bus_state())
        nack = await vip.send_byte((TARGET_ADDR0 << 1) | 1)
        self.vip_addr_acked = nack == 0
        got: list[int] = []
        if self.vip_addr_acked:
            for _ in S6_HOST_READS:
                byte = 0
                for _bit in range(8):
                    byte = (byte << 1) | await vip.recv_bit()
                got.append(byte)
            await self._ack_then_stop(vip)
        else:
            await vip.send_stop()
        self.vip_bytes = tuple(got)
        cocotb.log.info(
            "S6 host: read 0x%02x addr_acked=%s bytes=%s then STOP without NACK; bus: %s",
            TARGET_ADDR0,
            self.vip_addr_acked,
            [f"0x{b:02x}" for b in got],
            _bus_state(),
        )
        await Timer(20, "us")
        cocotb.log.info("S6 host: target after STOP: %s", await self._target_regs())

    @staticmethod
    async def _ack_then_stop(vip: SmcI2cMasterVip) -> None:
        """Acknowledge the byte just read and STOP inside the same acknowledge clock.

        SmcI2cMasterVip has no primitive for this because no legal host does
        it; it is composed from the VIP's own pad pulls and stretch-aware wait so
        the bit timing matches the rest of the transaction.
        """
        vip._pull_sda(True)
        await Timer(vip._half_ns, "ns")
        vip._pull_scl(False)
        await vip._wait_scl_high()
        await Timer(vip._half_ns, "ns")
        vip._pull_sda(False)
        await Timer(vip._half_ns, "ns")
        vip._active = False

    async def _target_regs(self) -> str:
        regs = []
        for sym in _TARGET_DIAG_REGS:
            addr = smc_indexed_addr(f"SMC_TOP_SMC_I2C_WRAP_I2C_{sym}_BASE_ADDR", TARGET_IDX)
            regs.append(f"{sym}=0x{await self.csr_read(f'S6_DIAG_{sym}', addr):08x}")
        return " ".join(regs)

    async def after_pass(self) -> None:
        assert self.watch is not None and self._watch_task is not None
        self.watch.stop = True
        await self._watch_task
        assert self.watch.handled == [S6_MARKER], (
            f"S6 marker 0x{S6_MARKER:08x} was never seen in SCRATCH_1 "
            f"(handled={self.watch.handled}); the image reached PASS without the bench host"
        )
        assert self.vip_addr_acked, "target I2C_1 NACKed the bench host's address 0x10 in S6"
        assert self.vip_bytes == S6_HOST_READS, (
            f"bench host read {self.vip_bytes} from the target; expected the first of its "
            f"preloaded TX bytes {S6_TX_PRELOAD}"
        )
        self.vip_read_ok = True
        cocotb.log.info(
            "CHK-FW-I2C-TARGET-VIP-READ: bench host read %s from target 0x%02x (address ACKed), "
            "then STOP without NACK; firmware graded INTR_STATE.UNEXP_STOP on the same event",
            [f"0x{b:02x}" for b in self.vip_bytes],
            TARGET_ADDR0,
        )
        await super().after_pass()
