class Redline:
    output_markdown: str | None = None
    opcodes: list[tuple[str, int, int, int, int]] | None = None

    def __init__(self, original: str, test: str | None = None):
        self.seq1 = original
        if test:
            self.seq2 = test
            self.compare()
        else:
            self.seq2 = None

    def compare(self, test: str | None = None):
        if test:
            if test == self.seq2:
                return self.output_markdown
            else:
                self.seq2 = test
        elif self.seq2 is None:
            raise ValueError('No test string was provided when the function was called, or during initialisation.')

        from difflib import SequenceMatcher
        import re

        tokenizer = re.compile(r"((?:[^()\s]+|[()\.\?\!])\s*)")
        seq1_token = re.findall(tokenizer, self.seq1)
        seq2_token = re.findall(tokenizer, self.seq2)

        matcher = SequenceMatcher(None, seq1_token, seq2_token)
        self.opcodes = matcher.get_opcodes()

        result = []
        for tag, i1, i2, j1, j2 in self.opcodes:
            match tag:
                case 'equal':
                    result.append("".join(seq1_token[i1:i2]))
                case 'insert':
                    result.append(f"<ins>{''.join(seq2_token[j1:j2])}</ins>")
                case 'delete':
                    result.append(f"<del>{''.join(seq1_token[i1:i2])}</del>")
                case 'replace':
                    result.append(f"<del>{''.join(seq1_token[i1:i2])}</del><ins>{''.join(seq2_token[j1:j2])}</ins>")

        self.output_markdown = "".join(result)

        return self.output_markdown
