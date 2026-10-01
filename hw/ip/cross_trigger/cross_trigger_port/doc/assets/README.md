<!-- SPDX-License-Identifier: CC-BY-4.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# Cross-trigger timing diagram

Edit `p2p_timing_diagram.json5` and regenerate the SVG with Node.js/npm:

```sh
cd hw/ip/cross_trigger/cross_trigger_port/doc/assets
npx --yes wavedrom@3.7.0 --input p2p_timing_diagram.json5 > p2p_timing_diagram.svg
```

The four signal rows describe pad-level timing. Wire arrows show propagation;
domain delays include input synchronization and local logic. The source response
interval runs from acknowledgment arriving at the source to the source clearing
its request. The spacing is illustrative and does not specify clock counts.
