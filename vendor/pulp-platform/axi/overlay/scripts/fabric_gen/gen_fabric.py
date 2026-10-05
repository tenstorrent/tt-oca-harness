#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
AXI Fabric Generator

Generates AXI-based interconnect fabrics from YAML configuration files.

Key Design Principle:
  Width conversion BEFORE protocol downgrade to preserve AXI size field semantics.

  AXI -> APB path:
    1. AXI (width) -> AXI (downsized) -> AXI-Lite -> APB

Usage:
  python gen_fabric.py config.yaml [--output-dir OUTPUT_DIR] [--validate-only] [--debug]
"""
import argparse
import os
import sys
from pathlib import Path


def setup_path():
    """Add fabric_gen parent to Python path for imports."""
    fabric_gen_dir = Path(__file__).resolve().parent
    parent_dir = fabric_gen_dir.parent
    if str(parent_dir) not in sys.path:
        sys.path.insert(0, str(parent_dir))


setup_path()

# Import from package (setup_path ensures this works)
from fabric_gen.config.parser import load_config, validate_config  # noqa: E402
from fabric_gen.generator.render import FabricRenderer  # noqa: E402


class Colors:
    """ANSI color codes for terminal output."""

    CODES = {
        'bold': '1', 'dim': '2',
        'red': '31', 'green': '32', 'yellow': '33', 'cyan': '36',
    }

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def __getattr__(self, name: str):
        if name in self.CODES:
            code = self.CODES[name]
            return lambda text: f"\033[{code}m{text}\033[0m" if self.enabled else text
        raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")


def main():
    parser = argparse.ArgumentParser(
        description="Generate AXI fabric from YAML configuration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        "config_path",
        type=Path,
        help="Path to YAML configuration file"
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=Path,
        default=Path(__file__).parent / "output",
        help="Output directory for generated files (default: ./output)"
    )
    parser.add_argument(
        "--validate-only", "-v",
        action="store_true",
        help="Only validate configuration, don't generate output"
    )
    parser.add_argument(
        "--debug", "-d",
        action="store_true",
        help="Print debug information"
    )
    parser.add_argument(
        "--show-chains",
        action="store_true",
        help="Show conversion chains for each output"
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored output"
    )

    args = parser.parse_args()

    # Setup colors (auto-disable if not a TTY or NO_COLOR env is set)
    use_color = (
        not args.no_color
        and sys.stdout.isatty()
        and os.environ.get("NO_COLOR") is None
    )
    c = Colors(enabled=use_color)

    if not args.config_path.exists():
        print(f"{c.red('Error:')} Configuration file not found: {args.config_path}")
        sys.exit(1)

    try:
        # Load and validate configuration
        config = load_config(args.config_path)

        # Run validation
        warnings = validate_config(config)
        for warning in warnings:
            print(f"{c.yellow('Warning:')} {warning}")

        if args.debug:
            print(f"\n{c.dim('Configuration details:')}")
            print(f"  {c.dim('Protocols:')} {list(config.protocols.keys())}")
            print(f"  {c.dim('Max input ID width:')} {config.get_max_input_id_width()}")
            print(f"  {c.dim('Xbar output ID width:')} {config.get_xbar_output_id_width()}")
            print(f"  {c.dim('Total address rules:')} {config.get_total_address_rules()}")

        # Show conversion chains if requested
        if args.show_chains or args.debug:
            from fabric_gen.generator.conversion_graph import generate_fabric_chains
            chains = generate_fabric_chains(config)
            print(f"\n{c.bold('Conversion chains:')}")
            for name, chain in chains.items():
                print(f"  {c.cyan(name)}:")
                for step in chain.steps:
                    print(f"    {c.dim('→')} {step.conversion_type.value}: "
                          f"{step.input_protocol.data_width}-bit {step.input_protocol.protocol_type.value} "
                          f"{c.dim('→')} "
                          f"{step.output_protocol.data_width}-bit {step.output_protocol.protocol_type.value}")
            if not chains:
                print(f"  {c.dim('(No protocol conversions needed)')}")

        if args.validate_only:
            print(f"\n{c.green('Validation successful!')}")
            sys.exit(0)

        # Generate fabric
        print(f"\nGenerating fabric to: {c.cyan(str(args.output_dir))}")
        renderer = FabricRenderer(config)
        written_files = renderer.write_output(args.output_dir)

        print(f"\n{c.bold('Generated files:')}")
        for file_type, file_path in written_files.items():
            print(f"  {file_type}: {c.cyan(str(file_path))}")

        print(f"\n{c.green('Generation complete!')}")

    except Exception as e:
        print(f"\n{c.red('Error:')} {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
