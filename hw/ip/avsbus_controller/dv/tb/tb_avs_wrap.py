# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
AVSBus Controller V1.3.1 Basic Sanity Test

Simple test to verify compilation and basic register read/write functionality.
"""

import cocotb
from basic_sanity import basic_sanity_test
from cocotb.triggers import with_timeout


@cocotb.test()
async def basic_sanity(dut):
    """Basic sanity test for register read/write functionality"""
    await with_timeout(basic_sanity_test(dut), 10000, "ns")
