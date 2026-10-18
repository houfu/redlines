## 1. Hostile text

[clause] 1.1 The report quotes <script>alert({~~1~>2~~})</script> with "double", 'single' & ampersand marks.

[clause] 1.2 A literal \{++x++\} and an arrow ~\> stay as typed, and so does {~~\\\{--this--\}.~>\\\{--this--\} and \{--that--\}.~~}

[clause] 1.3 Bidi controls ‮desrever‬ and ⁦isolated⁩ text must {~~survive.~>survive intact.~~}

[clause] 1.4 Archives are kept in C:\dir\\{--(old)--}

[clause] {--1.6 This clause goes, with <b>bold</b> & \{~~a substitution~\>of its own~~\}.--}

{>>moved to /section[1]/list_item[5]/paragraph[1]<<}

[clause] {++1.5 An inserted clause says ~\> and ++\} and <<\} and ends in a backslash \\++}

\[clause] This paragraph begins like a role prefix. {>>moved from /section[1]/list_item[5]/paragraph[1]<<}

- \[x] A task item that looks like a {~~role.~>role, edited.~~}

- \\\[y] A second task item with a backslash before its bracket.

## 2. Table

| Item | Note |
| --- | --- |
| a \| b | plain |
| ~\> | {~~x++\}~>y++\}~~} |
| {++new \| row++} | {++\{++z++\}++} |

## 3. Code

```python
if a { b++ }
print({~~"++\}"~>"++\} --\}"~~})
```