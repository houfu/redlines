"""
# Command line interface for redlines.

A command line interface for the redlines library that allows you to compare two strings/text or files
and see the differences in the terminal.


## NAME
`redlines` - A command line interface for the redlines library to compare text differences

## SYNOPSIS
```sh
redlines [COMMAND] [OPTIONS] SOURCE TEST
```

## DESCRIPTION
`Redlines` is a command line utility that shows the differences between two strings/text.
The changes are represented with strike-throughs and underlines, similar to Microsoft Word's track changes.
This method of showing changes is more familiar to lawyers and is more compact for long series of characters.

SOURCE and TEST can be either literal strings or file paths. If a file path is provided, the file content
will be read and used for comparison.

## COMMANDS
```sh
text
```
Compares SOURCE and TEST and produces a redline in the terminal in a display that shows the original,
new, redlined text, and statistics. Supports `--quiet` flag to suppress intro and styling.

```sh
simple_text
```
Compares SOURCE and TEST and outputs the redline in the terminal.

```sh
markdown
```
Compares SOURCE and TEST and outputs the redline as markdown. Supports `--markdown-style` to choose
the output style and `--quiet` for raw markdown output.

```sh
json
```
Compares SOURCE and TEST and outputs the comparison results as JSON with complete structural information.
Supports `--pretty` flag for formatted output.

```sh
stats
```
Compares SOURCE and TEST and displays comprehensive statistics including operation counts, change metrics,
and character-level statistics. Supports `--quiet` for plain text output.

## OPTIONS
```sh
-h, --help
```
Show this help message and exit.

```sh
-q, --quiet
```
Suppress rich formatting and styling (available for text, markdown, and stats commands).

```sh
-p, --pretty
```
Format JSON output with indentation (json command only).

```sh
-m, --markdown-style STYLE
```
Specify markdown style: red_green, none, red, ghfm, bbcode, streamlit (markdown command only).

## EXIT CODES
```sh
0
```
Success with changes detected

```sh
1
```
Success with no changes (source == test)

```sh
2
```
Error (file not found, encoding issues, etc.)

## EXAMPLES

Compare two strings and display the differences in a detailed layout with statistics:
```sh
redlines text "The quick brown fox jumps over the lazy dog." "The quick brown fox walks past the lazy dog."
```

Compare two files and output the redline directly:
```sh
redlines simple_text source.txt test.txt
```

Compare files and output as JSON for automation:
```sh
redlines json source.txt test.txt --pretty > comparison.json
```

Get statistics about changes between two files:
```sh
redlines stats source.txt test.txt --quiet
```

Compare strings with specific markdown style:
```sh
redlines markdown "Hello world" "Hello there" --markdown-style ghfm
```

Use in scripts with exit codes:
```sh
if redlines stats file1.txt file2.txt --quiet; then
    echo "Changes detected"
else
    echo "No changes or error occurred"
fi
```

## LIMITATIONS
* The `text` command is not able to show more than 6 lines of text. You may want to use `simple_text` for longer text.
* File inputs must be UTF-8 encoded.

You may also want to consider a related textual project if you want to use redlines in the terminal,
[redlines-textual](https://github.com/houfu/redlines-textual).
"""

import sys
import typing as t
from importlib.metadata import version
from pathlib import Path

import rich_click as click
from click_default_group import DefaultGroup
from rich.console import Console, group
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .enums import MarkdownStyle
from .processor import Stats
from .redlines import Redlines

# Use Rich markup
click.rich_click.USE_RICH_MARKUP = True
click.rich_click.SHOW_ARGUMENTS = True


if sys.version_info < (3, 10):
    raise RuntimeError(
        "redlines requires Python 3.10 or higher. Please upgrade your Python version."
    )


@group()
def print_intro() -> t.Generator[Text, None, None]:
    """@private"""
    yield Text.from_markup(
        f"\n[bold red]--__--[/] [b]Redlines CLI[/b] [magenta]v{version('redlines')}[/] [bold red]--__--[/]\n\n"
        f"[dim]➡️ Showing differences in text in the terminal⬅️ \n "
        f"[b]🏠 [link=https://github.com/houfu/redlines]Homepage[/][/]",
        justify="center",
    )


def _read_input(value: str) -> str:
    """
    Smart reader that accepts both file paths and string literals.

    If the value is a path to an existing file, reads and returns its content.
    Otherwise, treats the value as a literal string and returns it as-is.

    :param value: Either a file path or a literal string
    :return: The content to process
    :raises click.ClickException: If file exists but cannot be read
    """
    path = Path(value)
    if path.exists() and path.is_file():
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise click.ClickException(
                f"Failed to read file '{value}': File encoding is not UTF-8"
            )
        except PermissionError:
            raise click.ClickException(
                f"Failed to read file '{value}': Permission denied"
            )
        except Exception as e:
            raise click.ClickException(f"Failed to read file '{value}': {e}")
    return value


def _format_stats_panel(stats: Stats) -> Panel:
    """
    Format statistics as a Rich panel with a table.

    :param stats: Statistics object from Redlines
    :return: Rich Panel containing formatted statistics
    """
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Metric", style="bold cyan")
    table.add_column("Value", style="bold")

    table.add_row("Total Changes", str(stats.total_changes))
    table.add_row("Deletions", f"[red]{stats.deletions}[/red]")
    table.add_row("Insertions", f"[green]{stats.insertions}[/green]")
    table.add_row("Replacements", f"[yellow]{stats.replacements}[/yellow]")
    table.add_row("Characters Added", f"[green]+{stats.chars_added}[/green]")
    table.add_row("Characters Deleted", f"[red]-{stats.chars_deleted}[/red]")
    table.add_row("Net Change", str(stats.chars_net_change))
    table.add_row("Change Ratio", f"{stats.change_ratio:.1%}")

    if stats.levenshtein_distance is not None:
        table.add_row("Levenshtein Distance", str(stats.levenshtein_distance))

    return Panel(table, title="Statistics", title_align="left")


def _set_exit_code(ctx: click.Context, redlines: Redlines) -> None:
    """
    Set the exit code based on whether changes were detected.

    Exit codes:
    - 0: Success with changes detected
    - 1: Success with no changes (source == test)
    - 2: Error (handled by click.ClickException)

    :param ctx: Click context
    :param redlines: Redlines object with comparison results
    """
    stats = redlines.stats()
    if stats.total_changes == 0:
        ctx.exit(1)
    # Otherwise, normal exit (0) will occur


@click.group(cls=DefaultGroup, default="compare")
def cli() -> None:
    """
    [red on black]Redlines[/] shows the differences between two strings/text.

    The changes are represented with strike-throughs and underlines, which looks similar to Microsoft Word's
    track changes. This method of showing changes is more familiar to lawyers and is more compact for
    long series of characters.

    [dim]🤖 For AI agents & automation: run[/] [b]redlines guide[/b] [dim]or see AGENT_GUIDE.md[/]

    [b][link=https://github.com/houfu/redlines]Homepage[/][/]
    \f
    @private
    """
    pass


@cli.command()
@click.argument("source", required=True)
@click.argument("test", required=True)
@click.option(
    "--pretty",
    "-p",
    is_flag=True,
    help="Format JSON output with indentation for readability",
)
@click.pass_context
def compare(ctx: click.Context, source: str, test: str, pretty: bool) -> None:
    """
    Compare SOURCE and TEST and output the comparison as JSON.

    This is the default command when no command is specified.

    SOURCE and TEST can be either literal strings or file paths. If a file path is provided, the file content will be read and used.

    \f
    @private
    """
    # Print helpful message to stderr only if running in a TTY (not piped/redirected)
    if sys.stderr.isatty():
        sys.stderr.write(
            "💡 Tip: Use 'redlines --help' for all commands or 'redlines guide' for the agent integration guide\n\n"
        )
        sys.stderr.flush()

    source_content = _read_input(source)
    test_content = _read_input(test)

    redlines = Redlines(source_content, test_content)
    print(redlines.output_json(pretty=pretty))

    _set_exit_code(ctx, redlines)


@cli.command()
@click.argument("source", required=True)
@click.argument("test", required=True)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help="Suppress intro and styling, output only the redline",
)
@click.pass_context
def text(ctx: click.Context, source: str, test: str, quiet: bool) -> None:
    """
    Compares the strings SOURCE and TEST and produce a redline in the terminal in a display that shows the original, new and redlined text.

    SOURCE and TEST can be either literal strings or file paths. If a file path is provided, the file content will be read and used.

    \f
    @private
    """
    source_content = _read_input(source)
    test_content = _read_input(test)

    redlines = Redlines(source_content, test_content)

    if quiet:
        from rich import print

        print(redlines.output_rich)
    else:
        console = Console()
        layout = Layout()
        layout.split_column(
            Layout(print_intro(), name="intro"),
            Layout(
                Panel(redlines.output_rich, title="redline", title_align="left"),
                name="redline",
            ),
            Layout(name="middle"),
            Layout(name="stats"),
        )
        layout["middle"].split_row(
            Layout(
                Panel(source_content, title="Source", title_align="left"), name="source"
            ),
            Layout(Panel(test_content, title="Test", title_align="left"), name="test"),
        )
        layout["stats"].update(_format_stats_panel(redlines.stats()))
        console.print(layout)

    _set_exit_code(ctx, redlines)


@cli.command()
@click.argument("source", required=True)
@click.argument("test", required=True)
@click.pass_context
def simple_text(ctx: click.Context, source: str, test: str) -> None:
    """
    Compares the strings SOURCE and TEST and outputs the redline in the terminal.

    SOURCE and TEST can be either literal strings or file paths. If a file path is provided, the file content will be read and used.

    \f
    @private
    """
    from rich import print

    source_content = _read_input(source)
    test_content = _read_input(test)

    redlines = Redlines(source_content, test_content)
    print(redlines.output_rich)

    _set_exit_code(ctx, redlines)


@cli.command()
@click.argument("source", required=True)
@click.argument("test", required=True)
@click.option(
    "markdown_style",
    "--markdown-style",
    "-m",
    type=click.Choice(list(MarkdownStyle), case_sensitive=False),
    default="red_green",
    help="The markdown style to use.",
)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help="Suppress rich formatting, output raw markdown",
)
@click.pass_context
def markdown(
    ctx: click.Context, source: str, test: str, markdown_style: MarkdownStyle, quiet: bool
) -> None:
    """
    Compares the strings SOURCE and TEST and outputs the redline as a markdown.

    SOURCE and TEST can be either literal strings or file paths. If a file path is provided, the file content will be read and used.

    \f
    @private
    """
    source_content = _read_input(source)
    test_content = _read_input(test)

    redlines = Redlines(source_content, test_content, markdown_style=markdown_style)

    if quiet:
        # Output raw markdown without rich formatting (use builtin print)
        import builtins

        builtins.print(redlines.output_markdown)
    else:
        from rich import print

        print(redlines.output_markdown)

    _set_exit_code(ctx, redlines)


@cli.command()
@click.argument("source", required=True)
@click.argument("test", required=True)
@click.option(
    "--pretty",
    "-p",
    is_flag=True,
    help="Format JSON output with indentation for readability",
)
@click.pass_context
def json(ctx: click.Context, source: str, test: str, pretty: bool) -> None:
    """
    Compares the strings SOURCE and TEST and outputs the comparison results as JSON.

    SOURCE and TEST can be either literal strings or file paths. If a file path is provided, the file content will be read and used.

    The JSON output includes:
    - Original source and test texts
    - Token lists showing how text was parsed
    - All changes with character and token positions
    - Comprehensive statistics about the changes

    \f
    @private
    """
    source_content = _read_input(source)
    test_content = _read_input(test)

    redlines = Redlines(source_content, test_content)
    print(redlines.output_json(pretty=pretty))

    _set_exit_code(ctx, redlines)


@cli.command()
@click.argument("source", required=True)
@click.argument("test", required=True)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help="Suppress panel formatting, output plain statistics",
)
@click.pass_context
def stats(ctx: click.Context, source: str, test: str, quiet: bool) -> None:
    """
    Compares the strings SOURCE and TEST and displays comprehensive statistics.

    SOURCE and TEST can be either literal strings or file paths. If a file path is provided, the file content will be read and used.

    Statistics include:
    - Operation counts (deletions, insertions, replacements)
    - Change size metrics (longest, shortest, average lengths)
    - Change ratio (percentage of text modified)
    - Character-level statistics (added, deleted, net change)
    - Levenshtein distance (if available)

    \f
    @private
    """
    source_content = _read_input(source)
    test_content = _read_input(test)

    redlines = Redlines(source_content, test_content)
    stats_obj = redlines.stats()

    if quiet:
        # Plain text output for piping/scripting
        print(f"Total Changes: {stats_obj.total_changes}")
        print(f"Deletions: {stats_obj.deletions}")
        print(f"Insertions: {stats_obj.insertions}")
        print(f"Replacements: {stats_obj.replacements}")
        print(f"Characters Added: {stats_obj.chars_added}")
        print(f"Characters Deleted: {stats_obj.chars_deleted}")
        print(f"Net Change: {stats_obj.chars_net_change}")
        print(f"Change Ratio: {stats_obj.change_ratio:.1%}")
        if stats_obj.levenshtein_distance is not None:
            print(f"Levenshtein Distance: {stats_obj.levenshtein_distance}")
    else:
        console = Console()
        console.print(_format_stats_panel(stats_obj))

    _set_exit_code(ctx, redlines)


@cli.command()
@click.option(
    "--open",
    "-o",
    is_flag=True,
    help="Open the guide in your default browser (GitHub)",
)
def guide(open: bool) -> None:
    """
    Display the Agent Integration Guide for AI agents and automation.

    This guide contains:
    - Copy-paste ready code examples
    - JSON schema documentation
    - CLI automation patterns
    - Error handling cookbook
    - Performance guidelines
    - Real-world integration examples

    Use --open to view the guide on GitHub in your browser.

    \f
    @private
    """
    if open:
        import webbrowser

        url = "https://github.com/houfu/redlines/blob/main/AGENT_GUIDE.md"
        console = Console()
        console.print(f"[green]Opening Agent Guide in browser:[/] {url}")
        webbrowser.open(url)
    else:
        # Try to read the local AGENT_GUIDE.md file
        guide_path = Path(__file__).parent.parent / "AGENT_GUIDE.md"

        if guide_path.exists():
            console = Console()
            try:
                guide_content = guide_path.read_text(encoding="utf-8")
                from rich.markdown import Markdown

                console.print(Markdown(guide_content))
            except Exception as e:
                console.print(
                    f"[yellow]Could not display guide:[/] {e}\n\n"
                    "[dim]View online:[/] https://github.com/houfu/redlines/blob/main/AGENT_GUIDE.md"
                )
        else:
            console = Console()
            console.print(
                "[yellow]Agent Guide not found locally.[/]\n\n"
                "[b]View online:[/] https://github.com/houfu/redlines/blob/main/AGENT_GUIDE.md\n\n"
                "[dim]Or use[/] [b]redlines guide --open[/b] [dim]to open in your browser.[/]"
            )
