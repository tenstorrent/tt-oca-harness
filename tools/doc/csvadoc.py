#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
Convert CSV files to AsciiDoc table format.

This script reads a CSV file and converts it to an AsciiDoc table format,
suitable for documentation. It handles empty cells, special characters, and
allows customization of table attributes and title.
"""

import argparse
import csv
import os
import sys
from typing import List, Optional


def escape_asciidoc(text: str) -> str:
    r"""
    Escape special AsciiDoc characters in table cells.

    AsciiDoc special characters that need escaping in table cells:
    - | (pipe) - needs to be escaped as \|
    - \n (newlines) - can be preserved but may need handling
    """
    if not text:
        return ""
    # Escape pipe characters
    text = text.replace("|", "\\|")
    return text


def read_csv_file(csv_path: str) -> tuple[List[str], List[List[str]]]:
    """
    Read CSV file and return headers and rows.

    Args:
        csv_path: Path to CSV file

    Returns:
        Tuple of (headers, rows) where headers is a list of column names
        and rows is a list of lists containing cell values
    """
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            headers = next(reader)
            rows = list(reader)
            return headers, rows
    except FileNotFoundError:
        print(f"Error: CSV file '{csv_path}' not found.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error reading CSV file '{csv_path}': {e}", file=sys.stderr)
        sys.exit(1)


def generate_asciidoc_table(
    headers: List[str],
    rows: List[List[str]],
    title: Optional[str] = None,
    table_attrs: Optional[str] = None,
    cols_spec: Optional[str] = None,
) -> str:
    """
    Generate AsciiDoc table from headers and rows.

    Args:
        headers: List of column header names
        rows: List of data rows (each row is a list of cell values)
        title: Optional table title (without the leading dot)
        table_attrs: Optional table attributes (e.g., "[.small,stretch]")
        cols_spec: Optional column specification (e.g., "[%autowidth,options=\"header\",frame=all,grid=all]")

    Returns:
        AsciiDoc table as a string
    """
    num_cols = len(headers)

    # Build output lines
    lines = []

    # Add table attributes if provided
    if table_attrs:
        lines.append(table_attrs)

    # Add table title if provided
    if title:
        lines.append(f".{title}")

    # Add column specification if provided
    if cols_spec:
        lines.append(cols_spec)

    # Start table
    lines.append("|===")

    # Add header row
    header_line = "|" + " |".join(escape_asciidoc(str(h)) for h in headers)
    lines.append(header_line)

    # Add blank line after header (optional, for readability)
    lines.append("")

    # Add data rows
    for row in rows:
        # Pad row if it has fewer columns than headers
        padded_row = row + [""] * (num_cols - len(row))
        # Truncate row if it has more columns than headers
        padded_row = padded_row[:num_cols]

        # Build row line
        row_line = "|" + " |".join(escape_asciidoc(str(cell)) for cell in padded_row)
        lines.append(row_line)

    # End table
    lines.append("|===")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Convert CSV file to AsciiDoc table format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic conversion
  csvadoc.py input.csv -o output.adoc

  # With custom title and attributes
  csvadoc.py input.csv -o output.adoc --title "My Table" \\
    --table-attrs "[.small,stretch]" \\
    --cols-spec '[%autowidth,options="header",frame=all,grid=all]'

  # Auto-generate title from filename
  csvadoc.py gpio_requirements.csv -o gpio_table.adoc --auto-title
        """,
    )

    parser.add_argument("input_csv", help="Input CSV file path")

    parser.add_argument("-o", "--output", help="Output AsciiDoc file path (default: stdout)")

    parser.add_argument(
        "-t",
        "--title",
        help="Table title (without leading dot). If not specified, no title is added.",
    )

    parser.add_argument(
        "--auto-title",
        action="store_true",
        help="Auto-generate title from CSV filename (removes extension and converts to title case)",
    )

    parser.add_argument("--table-attrs", help='Table attributes (e.g., "[.small,stretch]")')

    parser.add_argument(
        "--cols-spec",
        help="Column specification (e.g., '[%autowidth,options=\"header\",frame=all,grid=all]')",
    )

    parser.add_argument(
        "--columns",
        help='Comma-separated list of column header names to include (e.g., "Requirement ID,Category,Requirement Description")',
    )

    parser.add_argument(
        "--id-prefix",
        help="Keep only rows whose first column value starts with this prefix (filters separator/empty rows)",
    )

    args = parser.parse_args()

    # Read CSV
    headers, rows = read_csv_file(args.input_csv)

    # Filter rows by id-prefix
    if args.id_prefix:
        rows = [row for row in rows if row and row[0].startswith(args.id_prefix)]

    # Select specific columns
    if args.columns:
        selected = [c.strip() for c in args.columns.split(",")]
        indices = []
        for col_name in selected:
            if col_name not in headers:
                print(
                    f"Error: column '{col_name}' not found in CSV headers: {headers}",
                    file=sys.stderr,
                )
                sys.exit(1)
            indices.append(headers.index(col_name))
        headers = [headers[i] for i in indices]
        rows = [[row[i] if i < len(row) else "" for i in indices] for row in rows]

    # Determine title
    title = args.title
    if args.auto_title and not title:
        # Generate title from filename
        base_name = os.path.splitext(os.path.basename(args.input_csv))[0]
        # Convert to title case (simple version)
        title = base_name.replace("_", " ").replace("-", " ").title()

    # Generate AsciiDoc table
    asciidoc = generate_asciidoc_table(
        headers, rows, title=title, table_attrs=args.table_attrs, cols_spec=args.cols_spec
    )

    # Write output
    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(asciidoc)
            print(f"Successfully converted '{args.input_csv}' to '{args.output}'")
        except Exception as e:
            print(f"Error writing output file '{args.output}': {e}", file=sys.stderr)
            sys.exit(1)
    else:
        # Write to stdout
        print(asciidoc)


if __name__ == "__main__":
    main()
