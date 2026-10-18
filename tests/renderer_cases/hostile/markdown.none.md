## 1. Hostile text

1.1 The report quotes <script>alert(<del>1</del><ins>2</ins>)</script> with "double", 'single' & ampersand marks.

1.2 A literal {++x++} and an arrow ~> stay as typed, and so does <del>\{--this--}.</del><ins>\{--this--} and {--that--}.</ins>

1.3 Bidi controls ‮desrever‬ and ⁦isolated⁩ text must <del>survive.</del><ins>survive intact.</ins>

1.4 Archives are kept in C:\dir\<del>(old)</del>

<del>1.6 This clause goes, with <b>bold</b> & {~~a substitution~>of its own~~}.</del>

<del>[clause] This paragraph begins like a role prefix.</del>

<ins>1.5 An inserted clause says ~> and ++} and <<} and ends in a backslash \</ins>

<ins>[clause] This paragraph begins like a role prefix.</ins>

- [x] A task item that looks like a <del>role.</del><ins>role, edited.</ins>

- \[y] A second task item with a backslash before its bracket.

## 2. Table

| Item | Note |
| --- | --- |
| a \| b | plain |
| ~> | <del>x++}</del><ins>y++}</ins> |
| <ins>new \| row</ins> | <ins>{++z++}</ins> |

## 3. Code

```python
if a { b++ }
print(<del>"++}"</del><ins>"++} --}"</ins>)
```