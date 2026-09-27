#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Write a packer config that is another config plus a named set of field overrides.

A negative boot testcase needs an image that differs from a booting image in
exactly one manifest field. Copying the whole config and editing the field gives
two files that drift apart, and a drifted copy still packs -- it just stops being
the golden image's sibling, which is the property the testcase argues from. Here
the derived config is regenerated from the base on every build, so the override
list IS the difference.

An override whose value already equals the base's is refused: that is either a
mistyped path or a field that no longer needs overriding, and both would produce
an image identical to the golden one under a negative testcase's name.
"""

from __future__ import annotations

import argparse
import sys

from ruamel.yaml import YAML


def _apply(config, dotted: str, value) -> None:
    """Set one dotted path, allowing numeric indices into existing sequences."""
    path = dotted.split(".")
    node = config
    for i, component in enumerate(path[:-1]):
        if isinstance(node, list):
            try:
                node = node[int(component)]
            except (ValueError, IndexError):
                raise SystemExit(
                    f"derive_pack_config: '{dotted}' has no sequence item "
                    f"'{'.'.join(path[: i + 1])}'"
                ) from None
        elif hasattr(node, "get") and component in node:
            node = node[component]
        else:
            raise SystemExit(
                f"derive_pack_config: '{dotted}' has no '{'.'.join(path[: i + 1])}' "
                f"in the base config; a derived config may override fields, not "
                f"invent sections"
            )
    leaf = path[-1]
    if isinstance(node, list):
        try:
            index = int(leaf)
            old_value = node[index]
        except (ValueError, IndexError):
            raise SystemExit(
                f"derive_pack_config: '{dotted}' has no sequence item '{leaf}'"
            ) from None
        if old_value == value:
            raise SystemExit(
                f"derive_pack_config: '{dotted}' is already {value!r} in the base "
                f"config, so this override changes nothing and the derived image would "
                f"be the base image"
            )
        node[index] = value
        return
    if leaf in node and node[leaf] == value:
        raise SystemExit(
            f"derive_pack_config: '{dotted}' is already {value!r} in the base "
            f"config, so this override changes nothing and the derived image would "
            f"be the base image"
        )
    node[leaf] = value


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", required=True, help="config to derive from")
    ap.add_argument("--out", required=True, help="derived config to write")
    ap.add_argument(
        "--set-str",
        action="append",
        default=[],
        metavar="PATH=VALUE",
        help="set a dotted path to a string value",
    )
    ap.add_argument(
        "--set-int",
        action="append",
        default=[],
        metavar="PATH=VALUE",
        help="set a dotted path to an integer value (0x accepted)",
    )
    args = ap.parse_args(argv)

    if not args.set_str and not args.set_int:
        raise SystemExit("derive_pack_config: no override given; use --set-str/--set-int")

    yaml = YAML()
    yaml.preserve_quotes = True
    with open(args.base, encoding="utf-8") as fh:
        config = yaml.load(fh)

    for item in args.set_str:
        dotted, _, raw = item.partition("=")
        _apply(config, dotted, raw)
    for item in args.set_int:
        dotted, _, raw = item.partition("=")
        _apply(config, dotted, int(raw, 0))

    with open(args.out, "w", encoding="utf-8") as fh:
        yaml.dump(config, fh)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
