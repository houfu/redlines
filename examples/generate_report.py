#!/usr/bin/env python3
"""
Generate HTML diff report for comparing two directories.

Usage:
    python generate_report.py old_dir/ new_dir/ report.html
"""

import sys
from pathlib import Path
from redlines import Redlines
from datetime import datetime


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Diff Report - {title}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            color: #333;
            background-color: #f5f5f5;
            padding: 20px;
        }}

        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background-color: white;
            padding: 30px;
            box-shadow: 0 0 10px rgba(0,0,0,0.1);
        }}

        h1 {{
            color: #2c3e50;
            margin-bottom: 10px;
        }}

        .metadata {{
            color: #7f8c8d;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 2px solid #ecf0f1;
        }}

        .summary {{
            background-color: #ecf0f1;
            padding: 20px;
            margin-bottom: 30px;
            border-radius: 5px;
        }}

        .summary h2 {{
            color: #34495e;
            margin-bottom: 15px;
        }}

        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
        }}

        .summary-item {{
            background-color: white;
            padding: 15px;
            border-radius: 3px;
        }}

        .summary-item .label {{
            color: #7f8c8d;
            font-size: 0.9em;
            margin-bottom: 5px;
        }}

        .summary-item .value {{
            font-size: 1.8em;
            font-weight: bold;
            color: #2c3e50;
        }}

        .file {{
            margin-bottom: 40px;
            border: 1px solid #ddd;
            border-radius: 5px;
            overflow: hidden;
        }}

        .file-header {{
            background-color: #34495e;
            color: white;
            padding: 15px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}

        .file-header h3 {{
            margin: 0;
            font-size: 1.1em;
        }}

        .file-stats {{
            background-color: #f8f9fa;
            padding: 15px 20px;
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            border-bottom: 1px solid #ddd;
        }}

        .stat {{
            display: flex;
            flex-direction: column;
        }}

        .stat-label {{
            font-size: 0.85em;
            color: #7f8c8d;
            margin-bottom: 3px;
        }}

        .stat-value {{
            font-size: 1.2em;
            font-weight: bold;
        }}

        .diff-content {{
            padding: 20px;
            font-family: 'Courier New', monospace;
            line-height: 1.8;
            background-color: #fafafa;
            overflow-x: auto;
        }}

        del {{
            background-color: #ffecec;
            color: #c0392b;
            text-decoration: line-through;
            padding: 2px 4px;
        }}

        ins {{
            background-color: #e8f5e9;
            color: #27ae60;
            text-decoration: underline;
            padding: 2px 4px;
        }}

        .no-changes {{
            padding: 20px;
            text-align: center;
            color: #27ae60;
            background-color: #e8f5e9;
        }}

        .badge {{
            display: inline-block;
            padding: 4px 8px;
            border-radius: 3px;
            font-size: 0.85em;
            font-weight: bold;
        }}

        .badge-success {{
            background-color: #27ae60;
            color: white;
        }}

        .badge-warning {{
            background-color: #f39c12;
            color: white;
        }}

        .footer {{
            margin-top: 40px;
            padding-top: 20px;
            border-top: 2px solid #ecf0f1;
            text-align: center;
            color: #7f8c8d;
            font-size: 0.9em;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Diff Report</h1>
        <div class="metadata">
            <p><strong>Generated:</strong> {timestamp}</p>
            <p><strong>Comparing:</strong> {dir1} vs {dir2}</p>
        </div>

        <div class="summary">
            <h2>Summary</h2>
            <div class="summary-grid">
                <div class="summary-item">
                    <div class="label">Total Files</div>
                    <div class="value">{total_files}</div>
                </div>
                <div class="summary-item">
                    <div class="label">Files with Changes</div>
                    <div class="value">{files_with_changes}</div>
                </div>
                <div class="summary-item">
                    <div class="label">Total Changes</div>
                    <div class="value">{total_changes}</div>
                </div>
                <div class="summary-item">
                    <div class="label">Avg Change Ratio</div>
                    <div class="value">{avg_change_ratio}</div>
                </div>
            </div>
        </div>

        {file_sections}

        <div class="footer">
            <p>Generated by redlines - <a href="https://github.com/houfu/redlines">https://github.com/houfu/redlines</a></p>
        </div>
    </div>
</body>
</html>
"""


def generate_file_section(filename: str, stats: dict, diff_html: str) -> str:
    """Generate HTML for a single file comparison."""
    if stats["total_changes"] == 0:
        status_badge = '<span class="badge badge-success">No Changes</span>'
        diff_section = '<div class="no-changes">Files are identical</div>'
    else:
        status_badge = f'<span class="badge badge-warning">{stats["total_changes"]} Changes</span>'
        diff_section = f'<div class="diff-content">{diff_html}</div>'

    return f"""
        <div class="file">
            <div class="file-header">
                <h3>{filename}</h3>
                {status_badge}
            </div>
            <div class="file-stats">
                <div class="stat">
                    <span class="stat-label">Insertions</span>
                    <span class="stat-value" style="color: #27ae60;">{stats['insertions']}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Deletions</span>
                    <span class="stat-value" style="color: #c0392b;">{stats['deletions']}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Replacements</span>
                    <span class="stat-value" style="color: #f39c12;">{stats['replacements']}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Change Ratio</span>
                    <span class="stat-value">{stats['change_ratio']}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Net Change</span>
                    <span class="stat-value">{stats['chars_net_change']:+d} chars</span>
                </div>
            </div>
            {diff_section}
        </div>
    """


def generate_report(dir1: Path, dir2: Path, output: Path, pattern: str = "*.txt") -> None:
    """Generate HTML diff report comparing two directories."""
    results = []
    total_changes = 0
    total_change_ratio = 0.0

    print(f"Scanning {dir1} for files matching '{pattern}'...")

    for file1 in sorted(dir1.glob(pattern)):
        if not file1.is_file():
            continue

        file2 = dir2 / file1.relative_to(dir1)
        if not file2.exists():
            print(f"  ⚠ {file1.relative_to(dir1)} - missing in second directory")
            continue

        try:
            source = file1.read_text(encoding="utf-8")
            test = file2.read_text(encoding="utf-8")

            diff = Redlines(source, test, markdown_style="none")
            stats = diff.stats()

            results.append({
                "file": str(file1.relative_to(dir1)),
                "stats": {
                    "total_changes": stats.total_changes,
                    "insertions": stats.insertions,
                    "deletions": stats.deletions,
                    "replacements": stats.replacements,
                    "change_ratio": f"{stats.change_ratio:.1%}",
                    "chars_net_change": stats.chars_net_change,
                },
                "diff": diff.output_markdown
            })

            total_changes += stats.total_changes
            total_change_ratio += stats.change_ratio

            status = "✓" if stats.total_changes == 0 else f"△ {stats.total_changes} changes"
            print(f"  {status} {file1.relative_to(dir1)}")

        except Exception as e:
            print(f"  ✗ {file1.relative_to(dir1)} - error: {e}")

    if not results:
        print("No files to compare!")
        return

    # Generate file sections
    file_sections = "\n".join([
        generate_file_section(r["file"], r["stats"], r["diff"])
        for r in results
    ])

    # Calculate summary stats
    files_with_changes = sum(1 for r in results if r["stats"]["total_changes"] > 0)
    avg_change_ratio = f"{(total_change_ratio / len(results)):.1%}" if results else "0%"

    # Generate HTML
    html = HTML_TEMPLATE.format(
        title=f"{dir1.name} vs {dir2.name}",
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        dir1=dir1,
        dir2=dir2,
        total_files=len(results),
        files_with_changes=files_with_changes,
        total_changes=total_changes,
        avg_change_ratio=avg_change_ratio,
        file_sections=file_sections
    )

    output.write_text(html, encoding="utf-8")
    print(f"\n✓ Report generated: {output}")
    print(f"  Total files: {len(results)}")
    print(f"  Files with changes: {files_with_changes}")
    print(f"  Total changes: {total_changes}")


def main():
    if len(sys.argv) < 4:
        print("Usage: python generate_report.py <dir1> <dir2> <output.html> [pattern]")
        print("\nExample:")
        print("  python generate_report.py old/ new/ report.html")
        print("  python generate_report.py old/ new/ report.html '*.md'")
        sys.exit(1)

    dir1 = Path(sys.argv[1])
    dir2 = Path(sys.argv[2])
    output = Path(sys.argv[3])
    pattern = sys.argv[4] if len(sys.argv) > 4 else "*.txt"

    if not dir1.is_dir():
        print(f"Error: {dir1} is not a directory")
        sys.exit(1)
    if not dir2.is_dir():
        print(f"Error: {dir2} is not a directory")
        sys.exit(1)

    generate_report(dir1, dir2, output, pattern)


if __name__ == "__main__":
    main()
