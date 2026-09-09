# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""I3C block TB environment package.

Holds the reusable layers the test modules build on: the register/AXI-Lite API
(``i3c_api``), the testbench and controller/target construction helpers
(``i3c_test_base``), and the constrained-random generators
(``constrained_random`` for the IP-agnostic primitives, ``i3c_rand`` for the
I3C domain layer).

Tests import through the submodule path, for example::

    from env.i3c_test_base import make_env, bring_up_and_assign
"""
