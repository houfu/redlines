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
    long series of characters. [b][link=https://github.com/houfu/redlines]Homepage[/][/]
    """
    pass


@cli.command()
@click.argument("source", required=True)
@click.argument("test", required=True)
def text(source, test):
    """
    Compares the strings SOURCE and TEST and produce a redline in the terminal.
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
