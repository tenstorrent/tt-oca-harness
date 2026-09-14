# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
Independent I3C bus partner for the controller DUT.

`cocotbext_i3c.I3CTarget` does not decode CCCs: it waits out a CCC frame and
clears the intercepted header, so the directed phase that follows trips
`wait_header`'s assertion when it addresses the target. This subclass adds the
dynamic-address CCCs, which is what the controller needs before any private
transfer.

Read data comes from the model's memory buffer and the read terminates after the
last queued byte, so queueing fewer bytes than the controller requests produces a
genuine short read with no register-level arming.
"""

from cocotb.triggers import Timer

from .cocotbext_i3c_compat import I3C_RSVD_BYTE, I3cHeader, I3cState, I3CTarget

CCC_SETDASA = 0x87
CCC_SETNEWDA = 0x88

# Both carry the new dynamic address in bits [7:1] of a single data byte.
_ADDR_ASSIGN_CCC = (CCC_SETDASA, CCC_SETNEWDA)


class VipI3cTarget(I3CTarget):
    """I3C target model that accepts SETDASA / SETNEWDA over the bus."""

    def __init__(self, *, static_addr=None, **kwargs):
        super().__init__(address=static_addr, **kwargs)
        self.static_addr = static_addr
        self.dynamic_addr = None
        self._pending_ccc = None

    async def recv_ccc(self):
        ccc, next_state = await super().recv_ccc()
        if next_state == I3cState.CCC_DATA and ccc in _ADDR_ASSIGN_CCC:
            self._pending_ccc = ccc
        return ccc, next_state

    async def wait_header(self):
        """Decode the address header.

        Accepts two sequences the base class rejects: a directed CCC phase, whose
        preceding header handle_message has already cleared, and a private transfer
        opened directly with the dynamic address and no reserved byte. Neither is
        required to follow a RESERVED, READ or WRITE header.
        """
        self.state = I3cState.ADDR
        addr_header = await self.recv(bits_num=8)
        addr, is_read = addr_header >> 1, addr_header & 0x1
        self.log.info("TARGET:::Address: 0x%02X RnW: %d", addr, is_read)

        if addr == I3C_RSVD_BYTE:
            await self.ack()
            self.header = I3cHeader.RESERVED
        elif addr == self.address:
            await self.ack()
            self.header = I3cHeader.READ if is_read else I3cHeader.WRITE
        else:
            self.header = I3cHeader.NON_APPLICABLE
            # The CCC was directed at some other device.
            self._pending_ccc = None

    async def handle_write(self):
        if self._pending_ccc is None:
            return await super().handle_write()

        ccc, self._pending_ccc = self._pending_ccc, None
        payload = []
        next_state = None
        while not next_state:
            self.state = I3cState.DATA_WR
            data, next_state = await self.recv_byte(is_data=True, ack=False, check_for_stop=True)
            if next_state != I3cState.STOP:
                payload.append(data & 0xFF)
        self.state = next_state

        if payload:
            self.dynamic_addr = payload[0] >> 1
            self.address = self.dynamic_addr
            self.log.info(
                "TARGET:::CCC 0x%02X assigned dynamic address 0x%02X", ccc, self.dynamic_addr
            )
        else:
            self.log.warning("TARGET:::CCC 0x%02X carried no data byte", ccc)

        return next_state

    async def wait_dynamic_addr(self, timeout_ns=100_000, interval_ns=200):
        """Bounded wait for an address-assignment CCC to take effect.

        The controller's response descriptor can land before the model has finished
        decoding the directed data phase that carries the address.
        """
        for _ in range(int(timeout_ns // interval_ns)):
            if self.dynamic_addr is not None:
                return self.dynamic_addr
            await Timer(interval_ns, "ns")
        return None

    def load_read_data(self, data):
        """Queue the bytes the next private read returns, discarding any leftovers.

        The read ends after the last queued byte, so a queue shorter than the
        controller's requested length is what creates a short read.
        """
        self._mem.clear()
        if data:
            self._mem.write(list(data), len(data))

    def received_data(self):
        """Bytes captured from private writes, consuming them from the buffer."""
        count = self._mem.len
        return bytes(self._mem.read(count)) if count > 0 else b""
