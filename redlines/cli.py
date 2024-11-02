"""
# Command line interface for redlines.

A command line interface for the redlines library that allows you to compare two strings
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

## COMMANDS
```sh
text
```
Compares the strings SOURCE and TEST and produces a redline in the terminal in a display that shows the original, new, and redlined text.

```sh
simple_text
```
Compares the strings SOURCE and TEST and outputs the redline in the terminal.

## OPTIONS
```sh
-h, --help
```
Show this help message and exit.

## EXAMPLES

Compare two strings and display the differences in a detailed layout:
```sh
redlines text "The quick brown fox jumps over the lazy dog." "The quick brown fox walks past the lazy dog."
```

Compare two strings and output the redline directly:
```sh
redlines simple_text "The quick brown fox jumps over the lazy dog." "The quick brown fox walks past the lazy dog."
```

## LIMITATIONS
* The `text` command is not able to show more than 6 lines of text. You may want to use `simple_text` for longer text.

You may also want to consider a related textual project if you want to use redlines in the terminal,
[redlines-textual](https://github.com/houfu/redlines-textual).
"""

from importlib.metadata import version

import rich_click as click
from rich.console import Console, group
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text

from redlines import Redlines

# Use Rich markup
click.rich_click.USE_RICH_MARKUP = True
click.rich_click.SHOW_ARGUMENTS = True


@group()
def print_intro():
    """@private"""
    yield Text.from_markup(
        f"\n[bold red]--__--[/] [b]Redlines CLI[/b] [magenta]v{version('redlines')}[/] [bold red]--__--[/]\n\n"
        f"[dim]➡️ Showing differences in text in the terminal⬅️ \n "
        f"[b]🏠 [link=https://github.com/houfu/redlines]Homepage[/][/]",
        justify="center",
    )


@click.group()
def cli():
    """
    [red on black]Redlines[/] shows the differences between two strings/text.

    The changes are represented with strike-throughs and underlines, which looks similar to Microsoft Word's
    track changes. This method of showing changes is more familiar to lawyers and is more compact for
    long series of characters.

    [b][link=https://github.com/houfu/redlines]Homepage[/][/]
    \f
    @private
    """
    pass


@cli.command()
@click.argument("source", required=True)
@click.argument("test", required=True)
def text(source, test):
    """
    Compares the strings SOURCE and TEST and produce a redline in the terminal in a display that shows the original, new and redlined text.

    \f
    @private
    """

    redlines = Redlines(source, test)

    console = Console()
    layout = Layout()
    layout.split_column(
        Layout(print_intro()),
        Layout(
            Panel(redlines.output_rich, title="redline", title_align="left"),
            name="redline",
        ),
        Layout(name="lower"),
    )
    layout["lower"].split_row(
        Layout(Panel(source, title="Source", title_align="left"), name="source"),
        Layout(Panel(test, title="Test", title_align="left"), name="test"),
    )
    console.print(layout)


@cli.command()
@click.argument("source", required=True)
@click.argument("test", required=True)
def simple_text(source, test):
    """
    Compares the strings SOURCE and TEST and outputs the redline in the terminal.

    \f
    @private
    """
    from rich import print

    redlines = Redlines(source, test)
    print(redlines.output_rich)
