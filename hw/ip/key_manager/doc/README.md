<!-- SPDX-License-Identifier: CC-BY-4.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# Key Manager packet diagrams

`packets.json` defines the packet layouts used by `firmware.adoc`. Each word
lists fields in descending bit order and covers bits 31 through 0 exactly once.
Word offsets are relative to the message or payload being illustrated;
ellipsis rows represent variable-length data. Identical layouts share an SVG.

From the repository root, regenerate the committed diagrams with:

```sh
python3 tools/doc/packet_diagrams.py hw/ip/key_manager/doc/packets.json
```

Check that the SVGs match their source without modifying files:

```sh
python3 tools/doc/packet_diagrams.py hw/ip/key_manager/doc/packets.json --check
python3 -m unittest discover -s tools/doc/tests
```

The renderer rejects missing, overlapping, and out-of-order bits. It emits
proportional fields, boundary bit numbers, SVG titles, and complete text
descriptions. Keep the corresponding image alternative text in `firmware.adoc`
in sync when changing a layout. The regular documentation staging flow copies
the SVGs for both HTML and PDF; readers need no diagram rendering service.
