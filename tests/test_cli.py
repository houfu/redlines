"""Tests for the CLI commands."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from redlines.cli import cli


@pytest.fixture
def runner():
    """Create a CLI runner for testing."""
    return CliRunner()


@pytest.fixture
def temp_files(tmp_path):
    """Create temporary test files."""
    source = tmp_path / "source.txt"
    test = tmp_path / "test.txt"

    source.write_text("The quick brown fox jumps over the lazy dog.")
    test.write_text("The quick brown fox walks past the lazy dog.")

    return {"source": source, "test": test}


class TestTextCommand:
    """Tests for the text command."""

    def test_text_with_strings(self, runner):
        """Test text command with string arguments."""
        result = runner.invoke(
            cli,
            [
                "text",
                "The quick brown fox jumps over the lazy dog.",
                "The quick brown fox walks past the lazy dog.",
                "--quiet",
            ],
        )
        assert result.exit_code == 0
        # Should contain the redline text
        assert "jumps over" in result.output or "walks past" in result.output

    def test_text_with_files(self, runner, temp_files):
        """Test text command with file inputs."""
        result = runner.invoke(
            cli,
            ["text", str(temp_files["source"]), str(temp_files["test"]), "--quiet"],
        )
        assert result.exit_code == 0

    def test_text_no_changes(self, runner):
        """Test text command with no changes (exit code 1)."""
        result = runner.invoke(cli, ["text", "Hello world", "Hello world", "--quiet"])
        assert result.exit_code == 1

    def test_text_with_changes(self, runner):
        """Test text command with changes (exit code 0)."""
        result = runner.invoke(
            cli, ["text", "Hello world", "Hello there", "--quiet"]
        )
        assert result.exit_code == 0

    def test_text_file_not_found(self, runner):
        """Test text command with non-existent file."""
        # Should treat non-existent path as a string literal, not fail
        result = runner.invoke(cli, ["text", "nonexistent.txt", "test", "--quiet"])
        assert result.exit_code in [0, 1]  # Depends on whether there are changes


class TestSimpleTextCommand:
    """Tests for the simple_text command."""

    def test_simple_text_with_strings(self, runner):
        """Test simple_text command with string arguments."""
        result = runner.invoke(
            cli,
            [
                "simple-text",
                "The quick brown fox jumps over the lazy dog.",
                "The quick brown fox walks past the lazy dog.",
            ],
        )
        assert result.exit_code == 0

    def test_simple_text_with_files(self, runner, temp_files):
        """Test simple_text command with file inputs."""
        result = runner.invoke(
            cli, ["simple-text", str(temp_files["source"]), str(temp_files["test"])]
        )
        assert result.exit_code == 0

    def test_simple_text_no_changes(self, runner):
        """Test simple_text command with no changes (exit code 1)."""
        result = runner.invoke(cli, ["simple-text", "Hello world", "Hello world"])
        assert result.exit_code == 1

    def test_simple_text_with_changes(self, runner):
        """Test simple_text command with changes (exit code 0)."""
        result = runner.invoke(cli, ["simple-text", "Hello world", "Hello there"])
        assert result.exit_code == 0


class TestMarkdownCommand:
    """Tests for the markdown command."""

    def test_markdown_with_strings(self, runner):
        """Test markdown command with string arguments."""
        result = runner.invoke(
            cli,
            [
                "markdown",
                "The quick brown fox jumps over the lazy dog.",
                "The quick brown fox walks past the lazy dog.",
            ],
        )
        assert result.exit_code == 0
        # Should contain markdown-style output
        assert "jumps over" in result.output or "walks past" in result.output

    def test_markdown_with_files(self, runner, temp_files):
        """Test markdown command with file inputs."""
        result = runner.invoke(
            cli, ["markdown", str(temp_files["source"]), str(temp_files["test"])]
        )
        assert result.exit_code == 0

    def test_markdown_style_option(self, runner):
        """Test markdown command with different style options."""
        for style in ["none", "red", "red_green", "ghfm", "bbcode", "streamlit"]:
            result = runner.invoke(
                cli,
                [
                    "markdown",
                    "Hello world",
                    "Hello there",
                    "--markdown-style",
                    style,
                ],
            )
            assert result.exit_code == 0

    def test_markdown_quiet_flag(self, runner):
        """Test markdown command with quiet flag."""
        result = runner.invoke(
            cli, ["markdown", "Hello world", "Hello there", "--quiet"]
        )
        assert result.exit_code == 0

    def test_markdown_no_changes(self, runner):
        """Test markdown command with no changes (exit code 1)."""
        result = runner.invoke(cli, ["markdown", "Hello world", "Hello world"])
        assert result.exit_code == 1

    def test_markdown_with_changes(self, runner):
        """Test markdown command with changes (exit code 0)."""
        result = runner.invoke(cli, ["markdown", "Hello world", "Hello there"])
        assert result.exit_code == 0


class TestJsonCommand:
    """Tests for the json command."""

    def test_json_with_strings(self, runner):
        """Test json command with string arguments."""
        result = runner.invoke(
            cli,
            [
                "json",
                "The quick brown fox jumps over the lazy dog.",
                "The quick brown fox walks past the lazy dog.",
            ],
        )
        assert result.exit_code == 0

        # Verify it's valid JSON
        data = json.loads(result.output)
        assert "source" in data
        assert "test" in data
        assert "changes" in data
        assert "stats" in data

    def test_json_with_files(self, runner, temp_files):
        """Test json command with file inputs."""
        result = runner.invoke(
            cli, ["json", str(temp_files["source"]), str(temp_files["test"])]
        )
        assert result.exit_code == 0

        data = json.loads(result.output)
        assert "The quick brown fox" in data["source"]

    def test_json_pretty_flag(self, runner):
        """Test json command with pretty flag."""
        result_compact = runner.invoke(cli, ["json", "Hello world", "Hello there"])
        result_pretty = runner.invoke(
            cli, ["json", "Hello world", "Hello there", "--pretty"]
        )

        assert result_compact.exit_code == 0
        assert result_pretty.exit_code == 0

        # Pretty version should have more characters (whitespace)
        assert len(result_pretty.output) > len(result_compact.output)
        assert "\n" in result_pretty.output

    def test_json_structure(self, runner):
        """Test json output structure."""
        result = runner.invoke(cli, ["json", "Hello world", "Hello there"])
        data = json.loads(result.output)

        # Verify required fields
        assert data["source"] == "Hello world"
        assert data["test"] == "Hello there"
        assert isinstance(data["source_tokens"], list)
        assert isinstance(data["test_tokens"], list)
        assert isinstance(data["changes"], list)
        assert isinstance(data["stats"], dict)

        # Verify stats structure
        stats = data["stats"]
        assert "total_changes" in stats
        assert "deletions" in stats
        assert "insertions" in stats
        assert "replacements" in stats
        assert "chars_added" in stats
        assert "chars_deleted" in stats

    def test_json_no_changes(self, runner):
        """Test json command with no changes (exit code 1)."""
        result = runner.invoke(cli, ["json", "Hello world", "Hello world"])
        assert result.exit_code == 1

        data = json.loads(result.output)
        assert data["stats"]["total_changes"] == 0

    def test_json_with_changes(self, runner):
        """Test json command with changes (exit code 0)."""
        result = runner.invoke(cli, ["json", "Hello world", "Hello there"])
        assert result.exit_code == 0

        data = json.loads(result.output)
        assert data["stats"]["total_changes"] > 0


class TestStatsCommand:
    """Tests for the stats command."""

    def test_stats_with_strings(self, runner):
        """Test stats command with string arguments."""
        result = runner.invoke(
            cli,
            [
                "stats",
                "The quick brown fox jumps over the lazy dog.",
                "The quick brown fox walks past the lazy dog.",
                "--quiet",
            ],
        )
        assert result.exit_code == 0

        # Should contain statistics
        assert "Total Changes:" in result.output
        assert "Deletions:" in result.output
        assert "Insertions:" in result.output
        assert "Replacements:" in result.output

    def test_stats_with_files(self, runner, temp_files):
        """Test stats command with file inputs."""
        result = runner.invoke(
            cli,
            ["stats", str(temp_files["source"]), str(temp_files["test"]), "--quiet"],
        )
        assert result.exit_code == 0

    def test_stats_quiet_output(self, runner):
        """Test stats quiet output format."""
        result = runner.invoke(
            cli, ["stats", "Hello world", "Hello there", "--quiet"]
        )
        assert result.exit_code == 0

        # Verify plain text format
        lines = result.output.strip().split("\n")
        assert any("Total Changes:" in line for line in lines)
        assert any("Replacements:" in line for line in lines)
        assert any("Change Ratio:" in line for line in lines)

    def test_stats_no_changes(self, runner):
        """Test stats command with no changes (exit code 1)."""
        result = runner.invoke(
            cli, ["stats", "Hello world", "Hello world", "--quiet"]
        )
        assert result.exit_code == 1
        assert "Total Changes: 0" in result.output

    def test_stats_with_changes(self, runner):
        """Test stats command with changes (exit code 0)."""
        result = runner.invoke(
            cli, ["stats", "Hello world", "Hello there", "--quiet"]
        )
        assert result.exit_code == 0
        # Total changes should be > 0
        assert "Total Changes: 0" not in result.output


class TestFileInputHandling:
    """Tests for file input handling across commands."""

    def test_file_vs_string_detection(self, runner, temp_files):
        """Test that files are properly detected and read."""
        # With file path
        result_file = runner.invoke(
            cli, ["json", str(temp_files["source"]), str(temp_files["test"])]
        )
        data_file = json.loads(result_file.output)

        # With actual strings
        result_string = runner.invoke(
            cli,
            [
                "json",
                "The quick brown fox jumps over the lazy dog.",
                "The quick brown fox walks past the lazy dog.",
            ],
        )
        data_string = json.loads(result_string.output)

        # Both should succeed
        assert result_file.exit_code == 0
        assert result_string.exit_code == 0

        # File should contain the expected text
        assert "The quick brown fox" in data_file["source"]
        assert "The quick brown fox" in data_string["source"]

    def test_utf8_file_encoding(self, runner, tmp_path):
        """Test that UTF-8 files are handled correctly."""
        source = tmp_path / "source_utf8.txt"
        test = tmp_path / "test_utf8.txt"

        source.write_text("Hello 世界", encoding="utf-8")
        test.write_text("Hello 🌍", encoding="utf-8")

        result = runner.invoke(cli, ["json", str(source), str(test)])
        assert result.exit_code == 0

        data = json.loads(result.output)
        assert "世界" in data["source"]
        assert "🌍" in data["test"]

    def test_non_utf8_file_error(self, runner, tmp_path):
        """Test error handling for non-UTF-8 files."""
        source = tmp_path / "source_latin1.txt"
        source.write_bytes(b"\xe9\xe8")  # Latin-1 encoded bytes

        result = runner.invoke(cli, ["json", str(source), "test"])
        # Click exceptions result in exit code 1, not 2
        # Error message should mention encoding
        assert result.exit_code != 0  # Should not succeed
        assert "encoding" in result.output.lower() or "utf-8" in result.output.lower() or "error" in result.output.lower()


class TestExitCodes:
    """Tests for exit code handling."""

    def test_exit_code_with_changes(self, runner):
        """Test exit code 0 when changes are detected."""
        result = runner.invoke(cli, ["json", "Hello world", "Hello there"])
        assert result.exit_code == 0

    def test_exit_code_no_changes(self, runner):
        """Test exit code 1 when no changes are detected."""
        result = runner.invoke(cli, ["json", "Hello world", "Hello world"])
        assert result.exit_code == 1

    def test_exit_code_consistency_across_commands(self, runner):
        """Test that exit codes are consistent across all commands."""
        commands = [
            ["text", "Hello world", "Hello there", "--quiet"],
            ["simple-text", "Hello world", "Hello there"],
            ["markdown", "Hello world", "Hello there"],
            ["json", "Hello world", "Hello there"],
            ["stats", "Hello world", "Hello there", "--quiet"],
        ]

        for cmd in commands:
            result = runner.invoke(cli, cmd)
            assert result.exit_code == 0, f"Command {cmd[0]} should exit with 0"

        # Test with no changes
        commands_no_changes = [
            ["text", "Hello world", "Hello world", "--quiet"],
            ["simple-text", "Hello world", "Hello world"],
            ["markdown", "Hello world", "Hello world"],
            ["json", "Hello world", "Hello world"],
            ["stats", "Hello world", "Hello world", "--quiet"],
        ]

        for cmd in commands_no_changes:
            result = runner.invoke(cli, cmd)
            assert result.exit_code == 1, f"Command {cmd[0]} should exit with 1"


class TestQuietFlag:
    """Tests for the --quiet flag."""

    def test_quiet_suppresses_formatting(self, runner):
        """Test that quiet flag suppresses rich formatting."""
        result_normal = runner.invoke(cli, ["stats", "Hello world", "Hello there"])
        result_quiet = runner.invoke(
            cli, ["stats", "Hello world", "Hello there", "--quiet"]
        )

        # Both should succeed
        assert result_normal.exit_code == 0
        assert result_quiet.exit_code == 0

        # Quiet should have simpler output
        # Normal might have ANSI codes or rich formatting
        assert len(result_quiet.output) <= len(result_normal.output) * 2

    def test_quiet_in_markdown(self, runner):
        """Test quiet flag in markdown command."""
        result = runner.invoke(
            cli, ["markdown", "Hello world", "Hello there", "--quiet"]
        )
        assert result.exit_code == 0
        # Should output raw markdown
        assert "<" in result.output  # HTML tags in markdown

    def test_quiet_in_text(self, runner):
        """Test quiet flag in text command."""
        result = runner.invoke(cli, ["text", "Hello world", "Hello there", "--quiet"])
        assert result.exit_code == 0
        # Should output just the redline without panels/intro
