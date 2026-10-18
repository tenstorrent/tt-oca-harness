# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Run one shard of a long leaf: a group of its independent trials.

A long randomized leaf draws its whole plan from the seed and then runs trials that
each start from their own reset, or from the same register state. The regression can
run such a leaf as several shards in parallel. ``+sep_shard=<k>`` selects shard k:
the leaf still draws the whole plan, runs only the trials of group k, and requires
only the evidence of group k. Every check of the leaf is in exactly one group, so
the shards together grade every check the whole leaf grades. Without the plusarg the
leaf runs every group, as before.
"""

from __future__ import annotations

import cocotb


def sep_shard(test, evidence: dict[int, tuple[str, ...]]) -> int | None:
    """The shard of this run, or None for the whole leaf.

    ``evidence`` maps each shard to the CHK IDs it grades. With a shard selected,
    ``test.required_evidence`` becomes that shard's IDs. A shard outside
    ``evidence`` fails the leaf before any stimulus.
    """
    raw = cocotb.plusargs.get("sep_shard")
    if raw is None:
        return None
    try:
        shard = int(raw) if isinstance(raw, str) else None
    except ValueError:
        shard = None
    if shard not in evidence:
        raise AssertionError(f"+sep_shard={raw!r}: the shards of this leaf are {sorted(evidence)}")
    covered = {check for checks in evidence.values() for check in checks}
    missing = [check for check in test.required_evidence if check not in covered]
    if missing:
        raise AssertionError(f"shard map leaves {missing} in no shard")
    test.required_evidence = evidence[shard]
    test.logger.info(
        "SHARD %d of %s: required=%s", shard, sorted(evidence), ",".join(evidence[shard])
    )
    return shard
