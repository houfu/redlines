# Processor Comparison Demo

This demo compares the **NupunktProcessor** and **WholeDocumentProcessor** implementations in terms of speed, accuracy, and edge case handling.

## Running the Demo

```bash
uv run demo/processor_comparison.py
```

## What This Demo Tests

### 1. Accuracy Tests (13 Edge Cases)

The demo tests both processors against challenging text patterns:

- **Abbreviations**: Dr., Mr., p.m., etc.
- **Decimal numbers**: $3.50, 98.6, 3.14159
- **URLs and emails**: example.com, test@example.com
- **Complex punctuation**: Multiple quotes, exclamation marks
- **Legal citations**: Smith v. Jones, F.3d, Cir.
- **Initials and acronyms**: J.R.R., NATO, U.S.A.
- **Ellipsis**: Handling of "..." in text
- **Multi-sentence paragraphs**: Testing granularity differences
- **Paragraph boundaries**: Handling of `\n` characters
- **False sentence boundaries**: Decimals that look like sentence endings
- **Abbreviations mid-sentence**: Context-dependent handling
- **Quoted abbreviations**: Abbreviations within quotation marks

### 2. Performance Tests (4 Sizes)

- **Small**: ~400 characters
- **Medium**: ~4,000 characters
- **Large**: ~40,000 characters
- **Very Large**: ~400,000 characters

## Key Findings

### Accuracy

**Both processors detect the SAME changes correctly!**

The 61.5% "different output" rate is NOT about accuracy - it's about **formatting**:

- **WholeDocumentProcessor**: Keeps sentences in paragraphs (no line breaks between sentences)
- **NupunktProcessor**: Adds line breaks at sentence boundaries

#### Example:
```
Input: "Sentence one. Sentence two."

WholeDocument output: "Sentence one. Sentence two."
Nupunkt output:       "Sentence one.

                       Sentence two."
```

Both correctly identify changes - they just format output differently based on their tokenization strategy.

### Performance

| Text Size | WholeDocument | Nupunkt | Speed Difference |
|-----------|--------------|---------|------------------|
| Small (~400 chars) | 0.19 ms | 0.40 ms | 2.1x slower |
| Medium (~4K chars) | 0.39 ms | 2.34 ms | 6.0x slower |
| Large (~40K chars) | 3.85 ms | 25.14 ms | 6.5x slower |
| Very Large (~400K chars) | 37.92 ms | 241.68 ms | 6.4x slower |

**Average**: NupunktProcessor is **5.3x slower** than WholeDocumentProcessor

**Throughput**:
- WholeDocumentProcessor: ~10 million chars/second
- NupunktProcessor: ~1.6 million chars/second

## Recommendations

### Use WholeDocumentProcessor when:
- Speed is critical
- Processing large volumes of documents
- Documents are simple without complex sentence structures
- Paragraph-level granularity is sufficient

### Use NupunktProcessor when:
- Working with legal or technical documents
- Sentence-level granularity is important
- Documents contain many abbreviations, citations, or complex punctuation
- The output needs sentence boundaries marked
- Performance overhead (2-6x slower) is acceptable

### General Guidelines:
- **Documents < 10KB**: NupunktProcessor overhead is minimal (~1-3ms)
- **Documents > 100KB**: Consider WholeDocumentProcessor if speed matters
- **Legal/technical texts**: NupunktProcessor provides better structure
- **Simple documents**: WholeDocumentProcessor is sufficient

## Technical Details

### WholeDocumentProcessor
- **Tokenization**: Paragraph-based (splits on `\n` characters)
- **Method**: Regular expression pattern matching
- **Dependencies**: None (built-in)
- **Speed**: Fast (simple regex operations)

### NupunktProcessor
- **Tokenization**: Sentence-based (intelligent boundary detection)
- **Method**: Machine learning-based (nupunkt library)
- **Dependencies**: nupunkt>=0.6.0 (Python 3.11+)
- **Speed**: Slower (ML inference overhead)
- **Advantages**: Handles abbreviations, decimals, URLs correctly

## Conclusion

Both processors are **equally accurate** at detecting changes. The choice between them depends on:

1. **Performance requirements**: WholeDocumentProcessor is 5-6x faster
2. **Output format needs**: Do you need sentence boundaries marked?
3. **Document complexity**: Technical documents benefit from NupunktProcessor
4. **Python version**: NupunktProcessor requires Python 3.11+

For most use cases, start with **WholeDocumentProcessor** for speed, and switch to **NupunktProcessor** if you need sentence-level granularity or work with complex technical/legal texts.
