<!-- SPDX-License-Identifier: CC-BY-4.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# Upstream reference figures

These figures describe upstream cores. The surrounding SEP text
specifies the OCAH integration differences. Source revisions match the
`opentitan` and `adams-bridge` revisions in `Bender.yml` at import.
The imported images retain their upstream Apache-2.0 license; they are
exceptions to the default documentation license. See the repository `LICENSE`
and `NOTICE` for license text and attribution.

OpenTitan: copyright lowRISC contributors, Apache-2.0.
Source: https://github.com/tenstorrent/tt-opentitan/tree/d1ce369cb357a7a4718c75f11567742a78a7ed07

| Local file | Upstream path |
| --- | --- |
| `opentitan_aes.svg` | `hw/ip/aes/doc/aes_block_diagram.svg` |
| `opentitan_hmac.svg` | `hw/ip/hmac/doc/hmac_block_diagram.svg` |
| `opentitan_kmac.svg` | `hw/ip/kmac/doc/kmac-block-diagram.svg` |
| `opentitan_otbn.svg` | `hw/ip/otbn/doc/otbn_blockarch.svg` |
| `opentitan_dma.svg` | `hw/ip/dma/doc/block_diagram.svg` |

Adams Bridge: copyright Adams Bridge contributors, Apache-2.0.
Source: https://github.com/chipsalliance/adams-bridge/tree/e59eba955eac2a1adcb059f250641ede78e304be

| Local file | Upstream path |
| --- | --- |
| `adams_bridge_mldsa.png` | `docs/images/MLDSA/image3.png` |
| `adams_bridge_mlkem.png` | `docs/images/MLKEM/AdamsBridge_MLKEM.png` |

The OTBN SVG omits one empty Inkscape `flowRoot` element, which has no visible
content and is unsupported by the PDF renderer. HMAC and KMAC have explicit
width and height matching their view boxes so the image viewer opens at a useful
size. These changes preserve rendered pixels; all other figures are unmodified.
