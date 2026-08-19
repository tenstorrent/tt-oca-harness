# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Mako template rendering for fabric generation."""
from pathlib import Path
from typing import Dict, Any, Optional
from io import StringIO

from mako.runtime import Context
from mako.lookup import TemplateLookup

from ..config.schema import FabricConfig
from .conversion_graph import generate_fabric_chains
from .template_context import build_render_context


class FabricRenderer:
    """Renders fabric SystemVerilog from configuration and templates."""

    def __init__(self, config: FabricConfig, template_dir: Optional[Path] = None):
        self.config = config
        self.template_dir = template_dir or Path(__file__).parent.parent / "templates"
        self.lookup = TemplateLookup(directories=[str(self.template_dir)])

        # Generate conversion chains
        self.conversion_chains = generate_fabric_chains(config)

        # Generate context
        self.context = self._build_context()

    def _build_context(self) -> Dict[str, Any]:
        """Build the template rendering context."""
        # Compute xbar dimensions
        xbar_data_width = max(
            self.config.protocols[inp.protocol].data_width
            for inp in self.config.inputs
        )
        xbar_addr_width = max(
            self.config.protocols[inp.protocol].addr_width
            for inp in self.config.inputs
        )

        max_input_id_width = self.config.get_max_input_id_width()
        connectivity_matrix = self.config.get_connectivity_matrix()

        derived = build_render_context(
            self.config,
            self.conversion_chains,
            xbar_data_width=xbar_data_width,
            xbar_addr_width=xbar_addr_width,
            max_input_id_width=max_input_id_width,
            connectivity_matrix=connectivity_matrix,
        )

        return {
            'config': self.config,
            'fabric_name': self.config.name,
            'inputs': self.config.inputs,
            'outputs': self.config.outputs,
            'protocols': self.config.protocols,
            'fabric': self.config.fabric,
            'num_inputs': len(self.config.inputs),
            'num_outputs': len(self.config.outputs),
            'num_rules': self.config.get_total_address_rules(),
            'max_input_id_width': max_input_id_width,
            'xbar_output_id_width': self.config.get_xbar_output_id_width(),
            'xbar_data_width': xbar_data_width,
            'xbar_addr_width': xbar_addr_width,
            'connectivity_matrix': connectivity_matrix,
            'conversion_chains': self.conversion_chains,
            'get_input_protocol': self.config.get_input_protocol,
            'get_output_protocol': self.config.get_output_protocol,
            **derived,
        }

    def render_template(self, template_name: str, extra_context: Optional[Dict] = None) -> str:
        """
        Render a template with the fabric context.

        Args:
            template_name: Name of the template file (e.g., "fabric_top.sv.mako")
            extra_context: Additional context to merge

        Returns:
            Rendered template string
        """
        template = self.lookup.get_template(template_name)
        ctx = self.context.copy()
        if extra_context:
            ctx.update(extra_context)

        buf = StringIO()
        mako_ctx = Context(buf, **ctx)
        template.render_context(mako_ctx)
        return buf.getvalue()

    def render_fabric(self) -> str:
        """Render the complete fabric module."""
        return self.render_template("fabric_top.sv.mako")

    def render_package(self) -> str:
        """Render the fabric package with typedefs."""
        return self.render_template("fabric_pkg.sv.mako")

    def write_output(self, output_dir: Path) -> Dict[str, Path]:
        """
        Write all generated files to the output directory.

        Args:
            output_dir: Directory to write files to

        Returns:
            Dictionary mapping file types to written paths
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        written_files = {}

        # Write package
        pkg_path = output_dir / f"{self.config.name}_pkg.sv"
        pkg_content = self.render_package()
        pkg_path.write_text(pkg_content)
        written_files['package'] = pkg_path

        # Write main fabric module
        fabric_path = output_dir / f"{self.config.name}.sv"
        fabric_content = self.render_fabric()
        fabric_path.write_text(fabric_content)
        written_files['fabric'] = fabric_path

        return written_files
