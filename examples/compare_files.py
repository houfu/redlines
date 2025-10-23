#!/usr/bin/env python3
"""
Basic file comparison example.

Usage:
    python compare_files.py old_file.txt new_file.txt
"""

import sys
from pathlib import Path
from redlines import Redlines


def compare_files(file1: str, file2: str) -> None:
    """Compare two files and display results."""
    # Read files
    try:
        source = Path(file1).read_text(encoding="utf-8")
        test = Path(file2).read_text(encoding="utf-8")
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except UnicodeDecodeError as e:
        print(f"Encoding error: {e}")
        print("Files must be UTF-8 encoded")
        sys.exit(1)

    # Compare
    diff = Redlines(source, test)
    stats = diff.stats()

    # Display results
    print(f"Comparing: {file1} vs {file2}")
    print("=" * 60)
    print(f"\nStatistics:")
    print(f"  Total changes: {stats.total_changes}")
    print(f"  Insertions: {stats.insertions}")
    print(f"  Deletions: {stats.deletions}")
    print(f"  Replacements: {stats.replacements}")
    print(f"  Change ratio: {stats.change_ratio:.1%}")
    print(f"  Characters added: {stats.chars_added}")
    print(f"  Characters deleted: {stats.chars_deleted}")
    print(f"  Net change: {stats.chars_net_change:+d} characters")

    if stats.levenshtein_distance is not None:
        print(f"  Levenshtein distance: {stats.levenshtein_distance}")

    if stats.total_changes > 0:
        print(f"\nDiff (markdown):")
        print("-" * 60)
        print(diff.output_markdown)
    else:
        print("\nNo changes detected - files are identical")


def main():
    if len(sys.argv) != 3:
        print("Usage: python compare_files.py <file1> <file2>")
        print("\nExample:")
        print("  python compare_files.py old_version.txt new_version.txt")
        sys.exit(1)

    compare_files(sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    main()
