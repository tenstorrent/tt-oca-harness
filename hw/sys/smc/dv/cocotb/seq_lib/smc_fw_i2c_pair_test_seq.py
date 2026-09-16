# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C_0 and I2C_1 talk to each other under firmware; the bench decodes the wire.

The images built on this sequence pair one instance as controller and the
other as target and move data between them with the CPU driving both sides.
Their byte compares, FIFO-level checks and interrupt lifecycles are read from
the two instances' CSRs by the firmware and graded there.

What the bench adds is the wire. With +smc_i2c_shared_bus the I2C0/1/2 pads
share one resolved open-drain bus, so the transfer the firmware describes has
to appear on tb_i2c0_scl/sda as START, address, direction, acknowledge, data
bytes, STOP. `SmcFwI2cWireMonitor` decodes that passively, and after the PASS
word the sequence checks the decoded frames against floors the image implies:
so many frames to the target address in a given direction, so many data bytes.
A PASS word without that traffic -- an image that short-circuited, a pad mux
left disabled, a target that never acknowledged -- fails here.

Floors, not exact counts: the driver splits long transfers and retries are
legal, so the wire can carry more frames than the minimum, never fewer. For a
write the bytes counted are those the target acknowledged; for a read they are
the bytes the target clocked out, since the controller NACKs the last one by
design.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb

from .smc_fw_i2c_wire_monitor import SmcFwI2cWireMonitor
from .smc_fw_image_boot_seq import smc_fw_image_boot_seq


@dataclass(frozen=True)
class WireFloor:
    addr7: int
    #: True: reads only, False: writes only, None: either direction.
    read: bool | None
    min_frames: int = 1
    min_data_bytes: int = 0
    #: True: only frames whose address byte was ACKed count; False: only NACKed
    #: ones (no target answers); None: both.
    addr_acked: bool | None = True

    def describe(self) -> str:
        rw = "any" if self.read is None else ("R" if self.read else "W")
        ack = "any" if self.addr_acked is None else ("ACK" if self.addr_acked else "NACK")
        return (
            f"addr=0x{self.addr7:02x} dir={rw} addr_ack={ack} "
            f"frames>={self.min_frames} bytes>={self.min_data_bytes}"
        )


class smc_fw_i2c_pair_test_seq(smc_fw_image_boot_seq):
    """Boot an I2C_0<->I2C_1 image with the wire decoder armed, then grade the wire."""

    floors: tuple[WireFloor, ...] = ()

    def __init__(
        self,
        name: str,
        *,
        tag: str | None = None,
        poll_iterations: int | None = None,
        floors: tuple[WireFloor, ...] | None = None,
    ) -> None:
        super().__init__(name)
        if tag is not None:
            self.tag = tag
        if poll_iterations is not None:
            self.poll_iterations = poll_iterations
        if floors is not None:
            self.floors = floors
        self.wire: SmcFwI2cWireMonitor | None = None
        self.wire_ok = False

    async def before_boot(self) -> None:
        assert "smc_i2c_shared_bus" in cocotb.plusargs, (
            f"{type(self).__name__} needs +smc_i2c_shared_bus: without it I2C_1's pads are "
            f"not on the bus I2C_0 drives and the image's transfers cannot complete"
        )
        self.wire = SmcFwI2cWireMonitor()

    async def after_pass(self) -> None:
        assert self.wire is not None
        self.wire.stop()
        cocotb.log.info("I2C0 wire summary: %s", self.wire.summary())
        for f in self.wire.frames:
            cocotb.log.info("I2C0 wire frame %s", f)
        for floor in self.floors:
            frames = [
                f
                for f in self.wire.frames_to(floor.addr7, read=floor.read)
                if floor.addr_acked is None or f.addr_acked == floor.addr_acked
            ]
            data_bytes = sum(f.data_bytes(acked_only=not bool(f.read)) for f in frames)
            assert len(frames) >= floor.min_frames and data_bytes >= floor.min_data_bytes, (
                f"wire floor not met ({floor.describe()}): saw {len(frames)} matching frames "
                f"carrying {data_bytes} data bytes; {self.wire.summary()}"
            )
            cocotb.log.info(
                "CHK-FW-I2C-WIRE-TRAFFIC: %s -> %d frames, %d data bytes decoded on "
                "tb_i2c0_scl/sda",
                floor.describe(),
                len(frames),
                data_bytes,
            )
        self.wire_ok = True
