# Redlines

`Redlines` produces a Markdown text showing the differences between two strings/text. The changes are represented with
strike-throughs and underlines, which looks similar to Microsoft Word's track changes. This method of showing changes is
more familiar to lawyers and is more compact for long series of characters.

Redlines uses [SequenceMatcher](https://docs.python.org/3/library/difflib.html#difflib.SequenceMatcher)
to find differences between words used.

## Example

Given an original string:

    The quick brown fox jumps over the lazy dog.`

And the string to be tested with:

    The quick brown fox walks past the lazy dog.

The library gives a result of:

    The quick brown fox <del>jumps over </del><ins>walks past </ins>the lazy dog.

Which is rendered like this:

The quick brown fox <del>jumps over </del><ins>walks past </ins>the lazy dog.

## Install

```shell
pip install redlines
```

## Usage

The library contains one class: `Redlines`, which is used to compare text.

```python
from redlines import Redlines

test = Redlines("The quick brown fox jumps over the lazy dog.",
                "The quick brown fox walks past the lazy dog.")
assert test.output_markdown == "The quick brown fox <del>jumps over </del><ins>walks past </ins>the lazy dog."
```

Alternatively, you can create Redline with the text to be tested, and compare several times to see the results.

```python
from redlines import Redlines

test = Redlines("The quick brown fox jumps over the lazy dog.")
assert test.compare(
    'The quick brown fox walks past the lazy dog.') == "The quick brown fox <del>jumps over </del><ins>walks past </ins>the lazy dog."

assert test.compare(
    'The quick brown fox jumps over the dog.') == 'The quick brown fox jumps over the <del>lazy </del>dog.'
```

## Roadmap / Contributing

Please feel free to post issues and comments. I work on this in my free time, so please excuse lack of activity.

### Nice things to do

* Style the way changes are presented
* Other than Markdown, have other output formats (HTML? PDF?)
* Associate changes with an author
* Show different changes by different authors or times.

If this was useful to you, please feel free to [contact me](mailto:houfu@lovelawrobots.com)!

## License

MIT License

