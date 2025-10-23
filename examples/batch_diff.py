#!/usr/bin/env python3
"""
Batch compare all files in two directories.

Usage:
    python batch_diff.py old_dir/ new_dir/
"""

import sys
from pathlib import Path
from redlines import Redlines


def batch_compare(dir1: Path, dir2: Path, pattern: str = "*.txt") -> list[dict]:
    """
    Compare all matching files in two directories.

    Args:
        dir1: First directory path
        dir2: Second directory path
        pattern: Glob pattern for files to compare (default: *.txt)

    Returns:
        List of comparison results
    """
    results = []

    for file1 in sorted(dir1.glob(pattern)):
        if not file1.is_file():
            continue

        file2 = dir2 / file1.relative_to(dir1)

        if not file2.exists():
            results.append({
                "file": str(file1.relative_to(dir1)),
                "status": "missing_in_dir2",
                "changes": None
            })
            continue

        try:
            source = file1.read_text(encoding="utf-8")
            test = file2.read_text(encoding="utf-8")

            diff = Redlines(source, test)
            stats = diff.stats()

            results.append({
                "file": str(file1.relative_to(dir1)),
                "status": "compared",
                "changes": stats.total_changes,
                "change_ratio": stats.change_ratio,
                "insertions": stats.insertions,
                "deletions": stats.deletions,
                "replacements": stats.replacements,
                "chars_net_change": stats.chars_net_change
            })

        except Exception as e:
            results.append({
                "file": str(file1.relative_to(dir1)),
                "status": "error",
                "error": str(e)
            })

    return results


def print_results(results: list[dict]) -> None:
    """Print comparison results in a formatted table."""
    print(f"\nBatch Comparison Results")
    print("=" * 80)

    # Summary
    total_files = len(results)
    compared = sum(1 for r in results if r["status"] == "compared")
    with_changes = sum(1 for r in results if r.get("changes", 0) > 0)
    errors = sum(1 for r in results if r["status"] == "error")
    missing = sum(1 for r in results if r["status"] == "missing_in_dir2")

    print(f"\nSummary:")
    print(f"  Total files: {total_files}")
    print(f"  Compared: {compared}")
    print(f"  With changes: {with_changes}")
    print(f"  Errors: {errors}")
    print(f"  Missing: {missing}")

    # Detailed results for files with changes
    if with_changes > 0:
        print(f"\nFiles with changes:")
        print("-" * 80)
        print(f"{'File':<40} {'Changes':<10} {'Ratio':<10} {'Net Change'}")
        print("-" * 80)

        for result in results:
            if result.get("changes", 0) > 0:
                file = result["file"]
                changes = result["changes"]
                ratio = f"{result['change_ratio']:.1%}"
                net = f"{result['chars_net_change']:+d}"
                print(f"{file:<40} {changes:<10} {ratio:<10} {net}")

    # Files without changes
    unchanged = [r for r in results if r.get("changes") == 0]
    if unchanged:
        print(f"\nUnchanged files: {len(unchanged)}")
        for result in unchanged:
            print(f"  ✓ {result['file']}")

    # Errors
    error_results = [r for r in results if r["status"] == "error"]
    if error_results:
        print(f"\nErrors:")
        for result in error_results:
            print(f"  ✗ {result['file']}: {result['error']}")

    # Missing files
    missing_results = [r for r in results if r["status"] == "missing_in_dir2"]
    if missing_results:
        print(f"\nMissing in second directory:")
        for result in missing_results:
            print(f"  ? {result['file']}")


def main():
    if len(sys.argv) < 3:
        print("Usage: python batch_diff.py <dir1> <dir2> [pattern]")
        print("\nExample:")
        print("  python batch_diff.py old/ new/")
        print("  python batch_diff.py old/ new/ '*.md'")
        sys.exit(1)

    dir1 = Path(sys.argv[1])
    dir2 = Path(sys.argv[2])
    pattern = sys.argv[3] if len(sys.argv) > 3 else "*.txt"

    if not dir1.is_dir():
        print(f"Error: {dir1} is not a directory")
        sys.exit(1)
    if not dir2.is_dir():
        print(f"Error: {dir2} is not a directory")
        sys.exit(1)

    print(f"Comparing directories:")
    print(f"  Directory 1: {dir1}")
    print(f"  Directory 2: {dir2}")
    print(f"  Pattern: {pattern}")

    results = batch_compare(dir1, dir2, pattern)
    print_results(results)


if __name__ == "__main__":
    main()
