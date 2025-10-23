#!/usr/bin/env python3
"""
CI/CD integration example for checking documentation changes.

This script compares files between two git branches and generates a summary
suitable for CI/CD pipelines.

Usage:
    python ci_check.py <base_branch> <file_pattern>

Example:
    python ci_check.py main "*.md"
    python ci_check.py develop "docs/**/*.txt"
"""

import sys
import subprocess
import tempfile
from pathlib import Path
from redlines import Redlines


def get_file_content(branch: str, filepath: str) -> str | None:
    """Get file content from a git branch."""
    try:
        result = subprocess.run(
            ["git", "show", f"{branch}:{filepath}"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout
    except subprocess.CalledProcessError:
        return None


def get_changed_files(base_branch: str, pattern: str = "*") -> list[str]:
    """Get list of changed files matching pattern."""
    try:
        # Get list of changed files between base branch and current HEAD
        result = subprocess.run(
            ["git", "diff", "--name-only", base_branch, "HEAD"],
            capture_output=True,
            text=True,
            check=True
        )
        all_files = result.stdout.strip().split("\n")

        # Filter by pattern if needed
        if pattern == "*":
            return [f for f in all_files if f]

        # Simple pattern matching
        if "*" in pattern:
            extension = pattern.split("*")[-1]
            return [f for f in all_files if f.endswith(extension)]

        return [f for f in all_files if f == pattern]

    except subprocess.CalledProcessError as e:
        print(f"Error getting changed files: {e}")
        return []


def check_file_changes(base_branch: str, files: list[str]) -> dict:
    """Check changes for all files."""
    results = {
        "total_files": 0,
        "files_with_changes": 0,
        "total_changes": 0,
        "files": []
    }

    for filepath in files:
        # Check if file exists in current branch
        current_path = Path(filepath)
        if not current_path.exists():
            # File was deleted
            results["files"].append({
                "path": filepath,
                "status": "deleted",
                "changes": 0
            })
            continue

        # Get base version
        base_content = get_file_content(base_branch, filepath)

        if base_content is None:
            # New file
            results["files"].append({
                "path": filepath,
                "status": "new",
                "changes": 0
            })
            continue

        # Compare versions
        try:
            current_content = current_path.read_text(encoding="utf-8")
            diff = Redlines(base_content, current_content)
            stats = diff.stats()

            results["total_files"] += 1

            if stats.total_changes > 0:
                results["files_with_changes"] += 1
                results["total_changes"] += stats.total_changes

            results["files"].append({
                "path": filepath,
                "status": "modified",
                "changes": stats.total_changes,
                "insertions": stats.insertions,
                "deletions": stats.deletions,
                "replacements": stats.replacements,
                "change_ratio": stats.change_ratio,
                "chars_net_change": stats.chars_net_change
            })

        except Exception as e:
            results["files"].append({
                "path": filepath,
                "status": "error",
                "error": str(e)
            })

    return results


def print_results(results: dict) -> None:
    """Print results in a CI-friendly format."""
    print("\n" + "=" * 70)
    print("DOCUMENTATION CHANGE REPORT")
    print("=" * 70)

    print(f"\n📊 Summary:")
    print(f"  Files analyzed: {results['total_files']}")
    print(f"  Files with changes: {results['files_with_changes']}")
    print(f"  Total changes: {results['total_changes']}")

    # Group files by status
    new_files = [f for f in results["files"] if f["status"] == "new"]
    modified_files = [f for f in results["files"] if f["status"] == "modified" and f["changes"] > 0]
    unchanged_files = [f for f in results["files"] if f["status"] == "modified" and f["changes"] == 0]
    deleted_files = [f for f in results["files"] if f["status"] == "deleted"]
    error_files = [f for f in results["files"] if f["status"] == "error"]

    if new_files:
        print(f"\n✨ New files ({len(new_files)}):")
        for file in new_files:
            print(f"  + {file['path']}")

    if modified_files:
        print(f"\n📝 Modified files with changes ({len(modified_files)}):")
        for file in modified_files:
            print(f"  △ {file['path']}")
            print(f"      Changes: {file['changes']} ({file['change_ratio']:.1%})")
            print(f"      +{file['insertions']} -{file['deletions']} ↻{file['replacements']}")
            print(f"      Net: {file['chars_net_change']:+d} characters")

    if unchanged_files:
        print(f"\n✓ Unchanged files ({len(unchanged_files)}):")
        for file in unchanged_files:
            print(f"  ✓ {file['path']}")

    if deleted_files:
        print(f"\n🗑️  Deleted files ({len(deleted_files)}):")
        for file in deleted_files:
            print(f"  - {file['path']}")

    if error_files:
        print(f"\n❌ Errors ({len(error_files)}):")
        for file in error_files:
            print(f"  ✗ {file['path']}: {file['error']}")

    print("\n" + "=" * 70)


def generate_github_summary(results: dict) -> str:
    """Generate GitHub Actions job summary markdown."""
    summary = "## 📄 Documentation Changes\n\n"

    summary += f"- **Files analyzed:** {results['total_files']}\n"
    summary += f"- **Files with changes:** {results['files_with_changes']}\n"
    summary += f"- **Total changes:** {results['total_changes']}\n\n"

    modified_files = [f for f in results["files"] if f["status"] == "modified" and f["changes"] > 0]

    if modified_files:
        summary += "### Modified Files\n\n"
        summary += "| File | Changes | Ratio | Insertions | Deletions | Replacements |\n"
        summary += "|------|---------|-------|------------|-----------|-------------|\n"

        for file in modified_files:
            summary += f"| `{file['path']}` | {file['changes']} | {file['change_ratio']:.1%} | "
            summary += f"+{file['insertions']} | -{file['deletions']} | ↻{file['replacements']} |\n"

    return summary


def main():
    if len(sys.argv) < 2:
        print("Usage: python ci_check.py <base_branch> [file_pattern]")
        print("\nExample:")
        print("  python ci_check.py main")
        print("  python ci_check.py main '*.md'")
        print("  python ci_check.py develop 'docs/**/*.txt'")
        sys.exit(1)

    base_branch = sys.argv[1]
    pattern = sys.argv[2] if len(sys.argv) > 2 else "*"

    print(f"Comparing changes against branch: {base_branch}")
    print(f"File pattern: {pattern}")

    # Get changed files
    changed_files = get_changed_files(base_branch, pattern)

    if not changed_files:
        print("\n✓ No files changed matching pattern")
        sys.exit(0)

    print(f"Found {len(changed_files)} changed file(s)")

    # Check changes
    results = check_file_changes(base_branch, changed_files)

    # Print results
    print_results(results)

    # Generate GitHub Actions summary if running in GitHub Actions
    if "GITHUB_STEP_SUMMARY" in subprocess.os.environ:
        summary_file = subprocess.os.environ["GITHUB_STEP_SUMMARY"]
        summary = generate_github_summary(results)
        Path(summary_file).write_text(summary, encoding="utf-8")
        print(f"\n📝 GitHub Actions summary written to {summary_file}")

    # Exit with appropriate code
    if results["files_with_changes"] > 0:
        print("\n✓ Documentation changes detected")
        sys.exit(0)  # Changes detected
    else:
        print("\n✓ No documentation changes")
        sys.exit(0)  # No changes (still success)


if __name__ == "__main__":
    main()
