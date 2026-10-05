# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Protocol type definitions and typedef generation."""
import dataclasses
import textwrap
from dataclasses import dataclass

from ..config.schema import ProtocolType, PROTOCOL_HIERARCHY


@dataclass
class Protocol:
    """Protocol state for tracking conversions."""
    protocol_type: ProtocolType
    data_width: int
    addr_width: int
    id_width: int = 0
    user_width: int = 1
    max_read_txns: int = 8
    max_write_txns: int = 8

    @property
    def strb_width(self) -> int:
        """Return strobe width (data_width / 8)."""
        return self.data_width // 8

    @property
    def has_id(self) -> bool:
        """Return True if protocol supports transaction IDs."""
        return self.protocol_type == ProtocolType.AXI4 and self.id_width > 0

    @property
    def has_user(self) -> bool:
        """Return True if protocol supports user signals."""
        return self.protocol_type == ProtocolType.AXI4 and self.user_width > 0

    @property
    def hierarchy_level(self) -> int:
        """Return the protocol hierarchy level."""
        return PROTOCOL_HIERARCHY[self.protocol_type]

    def can_convert_to(self, target: 'Protocol') -> bool:
        """Check if this protocol can be converted to target."""
        return self.hierarchy_level >= target.hierarchy_level

    def render_addr_typedef(self, prefix: str) -> str:
        """Render SystemVerilog typedef for address type."""
        return f"typedef logic [{self.addr_width-1}:0] {prefix}_addr_t;"

    def render_data_typedef(self, prefix: str) -> str:
        """Render SystemVerilog typedef for data type."""
        return f"typedef logic [{self.data_width-1}:0] {prefix}_data_t;"

    def render_strb_typedef(self, prefix: str) -> str:
        """Render SystemVerilog typedef for strobe type."""
        return f"typedef logic [{self.strb_width-1}:0] {prefix}_strb_t;"

    def render_id_typedef(self, prefix: str) -> str:
        """Render SystemVerilog typedef for ID type."""
        if not self.has_id:
            return ""
        return f"typedef logic [{self.id_width-1}:0] {prefix}_id_t;"

    def render_user_typedef(self, prefix: str) -> str:
        """Render SystemVerilog typedef for user type."""
        if not self.has_user:
            return ""
        return f"typedef logic [{self.user_width-1}:0] {prefix}_user_t;"

    TYPEDEF_RENDERERS = {
        ProtocolType.AXI4: '_render_full_axi_typedefs',
        ProtocolType.AXI4_LITE: '_render_axi_lite_typedefs',
        ProtocolType.APB4: '_render_apb_typedefs',
    }

    def render_axi_channel_typedefs(self, prefix: str) -> str:
        """Render AXI channel typedefs using macros, indented for package body."""
        renderer = self.TYPEDEF_RENDERERS.get(self.protocol_type, '_render_apb_typedefs')
        return textwrap.indent(getattr(self, renderer)(prefix), '  ')

    def _render_full_axi_typedefs(self, prefix: str) -> str:
        """Render full AXI4 channel typedefs."""
        lines = [
            f"// AXI4 typedefs for {prefix}",
            self.render_addr_typedef(prefix),
            self.render_data_typedef(prefix),
            self.render_strb_typedef(prefix),
            self.render_id_typedef(prefix),
            self.render_user_typedef(prefix),
            "",
            f"`AXI_TYPEDEF_AW_CHAN_T({prefix}_aw_chan_t, {prefix}_addr_t, {prefix}_id_t, {prefix}_user_t)",
            f"`AXI_TYPEDEF_W_CHAN_T({prefix}_w_chan_t, {prefix}_data_t, {prefix}_strb_t, {prefix}_user_t)",
            f"`AXI_TYPEDEF_B_CHAN_T({prefix}_b_chan_t, {prefix}_id_t, {prefix}_user_t)",
            f"`AXI_TYPEDEF_AR_CHAN_T({prefix}_ar_chan_t, {prefix}_addr_t, {prefix}_id_t, {prefix}_user_t)",
            f"`AXI_TYPEDEF_R_CHAN_T({prefix}_r_chan_t, {prefix}_data_t, {prefix}_id_t, {prefix}_user_t)",
            f"`AXI_TYPEDEF_REQ_T({prefix}_req_t, {prefix}_aw_chan_t, {prefix}_w_chan_t, {prefix}_ar_chan_t)",
            f"`AXI_TYPEDEF_RESP_T({prefix}_resp_t, {prefix}_b_chan_t, {prefix}_r_chan_t)",
        ]
        return "\n".join(filter(None, lines))

    def _render_axi_lite_typedefs(self, prefix: str) -> str:
        """Render AXI4-Lite channel typedefs."""
        lines = [
            f"// AXI4-Lite typedefs for {prefix}",
            self.render_addr_typedef(prefix),
            self.render_data_typedef(prefix),
            self.render_strb_typedef(prefix),
            "",
            f"`AXI_LITE_TYPEDEF_AW_CHAN_T({prefix}_aw_chan_t, {prefix}_addr_t)",
            f"`AXI_LITE_TYPEDEF_W_CHAN_T({prefix}_w_chan_t, {prefix}_data_t, {prefix}_strb_t)",
            f"`AXI_LITE_TYPEDEF_B_CHAN_T({prefix}_b_chan_t)",
            f"`AXI_LITE_TYPEDEF_AR_CHAN_T({prefix}_ar_chan_t, {prefix}_addr_t)",
            f"`AXI_LITE_TYPEDEF_R_CHAN_T({prefix}_r_chan_t, {prefix}_data_t)",
            f"`AXI_LITE_TYPEDEF_REQ_T({prefix}_req_t, {prefix}_aw_chan_t, {prefix}_w_chan_t, {prefix}_ar_chan_t)",
            f"`AXI_LITE_TYPEDEF_RESP_T({prefix}_resp_t, {prefix}_b_chan_t, {prefix}_r_chan_t)",
        ]
        return "\n".join(filter(None, lines))

    def _render_apb_typedefs(self, prefix: str) -> str:
        """Render APB4 typedefs."""
        lines = [
            f"// APB4 typedefs for {prefix}",
            self.render_addr_typedef(prefix),
            self.render_data_typedef(prefix),
            self.render_strb_typedef(prefix),
            "",
            "typedef struct packed {",
            f"  {prefix}_addr_t     paddr;",
            "  axi_pkg::prot_t     pprot;",
            "  logic               psel;",
            "  logic               penable;",
            "  logic               pwrite;",
            f"  {prefix}_data_t     pwdata;",
            f"  {prefix}_strb_t     pstrb;",
            f"}} {prefix}_req_t;",
            "",
            "typedef struct packed {",
            "  logic               pready;",
            f"  {prefix}_data_t     prdata;",
            "  logic               pslverr;",
            f"}} {prefix}_resp_t;",
        ]
        return "\n".join(lines)

    def copy(self, **kwargs) -> 'Protocol':
        """Create a copy with optional field overrides."""
        return dataclasses.replace(self, **kwargs)
