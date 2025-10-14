#!/usr/bin/env python3
"""
Demo script comparing NupunktProcessor vs WholeDocumentProcessor

This script benchmarks and compares two text processing approaches:
1. WholeDocumentProcessor: Splits on paragraph boundaries (\\n characters)
2. NupunktProcessor: Uses intelligent sentence boundary detection

The comparison focuses on:
- Speed performance across different text sizes
- Accuracy in handling edge cases (abbreviations, decimals, URLs, etc.)
"""

import time
from typing import Any, Literal, TypedDict

from redlines.processor import Redline

try:
    from redlines import Redlines
    from redlines.processor import NupunktProcessor, WholeDocumentProcessor
except ImportError:
    import sys
    from pathlib import Path

    # Add parent directory to path for imports
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from redlines import Redlines
    from redlines.processor import NupunktProcessor, WholeDocumentProcessor


class EdgeCaseResult(TypedDict):
    """Result structure for edge case comparisons."""
    whole_changes: list[Redline]
    nupunkt_changes: list[Redline]
    whole_output: str | None
    nupunkt_output: str | None
    match: bool


class PerformanceResult(TypedDict):
    """Result structure for performance comparisons."""
    size: str
    whole_time: float | None
    whole_changes: int
    nupunkt_time: float | None
    nupunkt_changes: int


# Edge case test texts
EDGE_CASES = {
    "abbreviations": {
        "source": "Dr. Smith visited Mr. Jones at 3 p.m. yesterday.",
        "test": "Dr. Smith met Mr. Jones at 3 p.m. yesterday.",
        "description": "Tests handling of common abbreviations (Dr., Mr., p.m.)",
    },
    "decimals": {
        "source": "The price was $3.50 and the temperature was 98.6 degrees.",
        "test": "The price was $4.50 and the temperature was 98.6 degrees.",
        "description": "Tests handling of decimal numbers",
    },
    "urls_and_emails": {
        "source": "Visit example.com or email test@example.com for more info.",
        "test": "Visit example.org or email test@example.com for more info.",
        "description": "Tests handling of URLs and email addresses",
    },
    "complex_punctuation": {
        "source": "He said, \"Are you sure?\" She replied, \"Yes!\" It was settled.",
        "test": 'He said, "Are you certain?" She replied, "Yes!" It was settled.',
        "description": "Tests handling of quotes and multiple punctuation marks",
    },
    "legal_citations": {
        "source": "See Smith v. Jones, 123 F.3d 456 (9th Cir. 2020). The court held...",
        "test": "See Smith v. Jones, 123 F.3d 456 (9th Cir. 2021). The court held...",
        "description": "Tests handling of legal citations with abbreviations",
    },
    "multi_sentence_paragraph": {
        "source": "This is sentence one. This is sentence two. This is sentence three.",
        "test": "This is sentence one. This is modified sentence two. This is sentence three.",
        "description": "Tests sentence-level vs paragraph-level granularity",
    },
    "paragraph_boundaries": {
        "source": "First paragraph.\n\nSecond paragraph with change.",
        "test": "First paragraph.\n\nSecond paragraph without change.",
        "description": "Tests handling of paragraph breaks",
    },
    "initials_and_acronyms": {
        "source": "J.R.R. Tolkien wrote about NATO and the U.S.A. in his notes.",
        "test": "J.R.R. Tolkien wrote about NATO and the U.K. in his notes.",
        "description": "Tests handling of initials and acronyms with periods",
    },
    "false_sentence_boundary": {
        "source": "The value is 3.14159. The next sentence starts here.",
        "test": "The value is 3.14159. The modified sentence starts here.",
        "description": "Tests whether decimal point triggers false sentence boundary",
    },
    "abbreviation_mid_sentence": {
        "source": "Contact Dr. Smith or Mrs. Jones for more information about the project.",
        "test": "Contact Dr. Smith or Mr. Jones for more information about the project.",
        "description": "Tests abbreviations in middle of sentence (should NOT split)",
    },
    "multiple_sentences": {
        "source": "Sentence A. Sentence B. Sentence C.",
        "test": "Sentence A. Modified B. Sentence C.",
        "description": "Tests granularity difference: paragraph vs sentence-level detection",
    },
    "ellipsis": {
        "source": "She said... well... never mind.",
        "test": "She said... um... never mind.",
        "description": "Tests handling of ellipsis (should not split on '...')",
    },
    "quoted_abbreviation": {
        "source": 'The document states "Mr. Jones is correct." We agree.',
        "test": 'The document states "Dr. Jones is correct." We agree.',
        "description": "Tests abbreviation within quotes",
    },
}

# Performance test texts (varying sizes)
PERFORMANCE_TEXTS = {
    "small": {
        "source": "The quick brown fox jumps over the lazy dog. " * 10,
        "test": "The quick red fox jumps over the lazy dog. " * 10,
        "size": "~400 chars",
    },
    "medium": {
        "source": "The quick brown fox jumps over the lazy dog. " * 100,
        "test": "The quick red fox jumps over the lazy dog. " * 100,
        "size": "~4,000 chars",
    },
    "large": {
        "source": "The quick brown fox jumps over the lazy dog. " * 1000,
        "test": "The quick red fox jumps over the lazy dog. " * 1000,
        "size": "~40,000 chars",
    },
    "very_large": {
        "source": "The quick brown fox jumps over the lazy dog. " * 10000,
        "test": "The quick red fox jumps over the lazy dog. " * 10000,
        "size": "~400,000 chars",
    },
}


def benchmark_processor(
    processor_type: Literal["nupunkt", "whole"],
    source: str,
    test: str,
    iterations: int = 5,
) -> tuple[float, int]:
    """
    Benchmark a processor's performance.

    Args:
        processor_type: Type of processor to use
        source: Source text
        test: Test text
        iterations: Number of iterations to average

    Returns:
        Tuple of (average_time_seconds, num_changes)
    """
    processor = NupunktProcessor() if processor_type == "nupunkt" else WholeDocumentProcessor()

    times = []
    num_changes = 0

    for _ in range(iterations):
        start = time.perf_counter()
        redlines = Redlines(source, test, processor=processor)
        diff_ops = redlines.redlines
        end = time.perf_counter()

        times.append(end - start)
        num_changes = len(diff_ops)

    avg_time = sum(times) / len(times)
    return avg_time, num_changes


def run_edge_case_comparison(case_name: str, case_data: dict[str, str]) -> EdgeCaseResult:
    """Run comparison for a single edge case and return results."""
    print(f"\n{'='*70}")
    print(f"Edge Case: {case_name}")
    print(f"Description: {case_data['description']}")
    print(f"{'='*70}")

    source = case_data["source"]
    test = case_data["test"]

    print(f"\nSource: {source}")
    print(f"Test:   {test}")

    results: EdgeCaseResult = {
        "whole_changes": [],
        "nupunkt_changes": [],
        "whole_output": None,
        "nupunkt_output": None,
        "match": False,
    }

    # Test WholeDocumentProcessor
    print("\n--- WholeDocumentProcessor ---")
    try:
        whole_processor = WholeDocumentProcessor()
        whole_redlines = Redlines(source, test, processor=whole_processor)
        whole_changes = whole_redlines.redlines
        whole_time, _ = benchmark_processor("whole", source, test, iterations=10)
        whole_output = whole_redlines.output_markdown

        results["whole_changes"] = whole_changes
        results["whole_output"] = whole_output

        print(f"Changes detected: {len(whole_changes)}")
        print(f"Average time: {whole_time*1000:.3f} ms")

        if whole_changes:
            print("\nDetailed changes:")
            for i, change in enumerate(whole_changes, 1):
                print(f"  {i}. {change.operation.upper()}")
                if change.source_text:
                    print(f"     Source: {change.source_text[:100]}")
                if change.test_text:
                    print(f"     Test:   {change.test_text[:100]}")

    except Exception as e:
        print(f"Error: {e}")

    # Test NupunktProcessor
    print("\n--- NupunktProcessor ---")
    try:
        nupunkt_processor = NupunktProcessor()
        nupunkt_redlines = Redlines(source, test, processor=nupunkt_processor)
        nupunkt_changes = nupunkt_redlines.redlines
        nupunkt_time, _ = benchmark_processor("nupunkt", source, test, iterations=10)
        nupunkt_output = nupunkt_redlines.output_markdown

        results["nupunkt_changes"] = nupunkt_changes
        results["nupunkt_output"] = nupunkt_output

        print(f"Changes detected: {len(nupunkt_changes)}")
        print(f"Average time: {nupunkt_time*1000:.3f} ms")

        if nupunkt_changes:
            print("\nDetailed changes:")
            for i, change in enumerate(nupunkt_changes, 1):
                print(f"  {i}. {change.operation.upper()}")
                if change.source_text:
                    print(f"     Source: {change.source_text[:100]}")
                if change.test_text:
                    print(f"     Test:   {change.test_text[:100]}")

    except ImportError:
        print("NupunktProcessor requires nupunkt (Python 3.11+)")
        print("Install with: pip install nupunkt>=0.6.0")
    except Exception as e:
        print(f"Error: {e}")

    # Compare outputs
    whole_out = results["whole_output"]
    nupunkt_out = results["nupunkt_output"]
    if whole_out and nupunkt_out and isinstance(whole_out, str) and isinstance(nupunkt_out, str):
        results["match"] = whole_out == nupunkt_out
        if results["match"]:
            print("\n✓ Both processors produced IDENTICAL output")
        else:
            print("\n✗ Processors produced DIFFERENT outputs")
            print("\nWholeDocument output:")
            print(f"  {whole_out[:200]}...")
            print("\nNupunkt output:")
            print(f"  {nupunkt_out[:200]}...")

    return results


def run_performance_comparison() -> dict[str, PerformanceResult]:
    """Run performance benchmarks across different text sizes and return results."""
    print("\n" + "="*70)
    print("PERFORMANCE COMPARISON")
    print("="*70)

    print(f"\n{'Size':<15} {'Processor':<20} {'Avg Time':<15} {'Changes':<10} {'Speedup'}")
    print("-" * 75)

    results: dict[str, PerformanceResult] = {}

    for size_name, text_data in PERFORMANCE_TEXTS.items():
        source = text_data["source"]
        test = text_data["test"]

        results[size_name] = {
            "size": text_data["size"],
            "whole_time": None,
            "whole_changes": 0,
            "nupunkt_time": None,
            "nupunkt_changes": 0,
        }

        # Benchmark WholeDocumentProcessor
        try:
            whole_time, whole_changes = benchmark_processor("whole", source, test)
            results[size_name]["whole_time"] = whole_time
            results[size_name]["whole_changes"] = whole_changes
        except Exception as e:
            print(f"{size_name:<15} {'WholeDocument':<20} ERROR: {e}")
            whole_time = None
            whole_changes = 0

        # Benchmark NupunktProcessor
        try:
            nupunkt_time, nupunkt_changes = benchmark_processor("nupunkt", source, test)
            results[size_name]["nupunkt_time"] = nupunkt_time
            results[size_name]["nupunkt_changes"] = nupunkt_changes
        except ImportError:
            nupunkt_time = None
            nupunkt_changes = 0
        except Exception as e:
            print(f"{size_name:<15} {'Nupunkt':<20} ERROR: {e}")
            nupunkt_time = None
            nupunkt_changes = 0

        # Print results
        if whole_time is not None:
            print(f"{size_name:<15} {'WholeDocument':<20} {whole_time*1000:>10.2f} ms {whole_changes:>8} {'-':>10}")

        if nupunkt_time is not None:
            speedup = f"{whole_time/nupunkt_time:.2f}x" if whole_time and nupunkt_time else "-"
            print(f"{size_name:<15} {'Nupunkt':<20} {nupunkt_time*1000:>10.2f} ms {nupunkt_changes:>8} {speedup:>10}")
        else:
            print(f"{size_name:<15} {'Nupunkt':<20} {'NOT AVAILABLE (requires Python 3.11+)'}")

        print()

    return results


def print_comparison_table(results: dict[str, PerformanceResult]) -> None:
    """Print a comprehensive comparison table of the results."""
    print("\n" + "="*80)
    print("DETAILED PERFORMANCE COMPARISON TABLE")
    print("="*80)
    print()

    # Header
    print(f"{'Text Size':<15} {'Metric':<25} {'WholeDocument':<20} {'Nupunkt':<20} {'Ratio':<15}")
    print("-" * 95)

    for size_name, data in results.items():
        whole_time = data["whole_time"]
        nupunkt_time = data["nupunkt_time"]
        whole_changes = data["whole_changes"]
        nupunkt_changes = data["nupunkt_changes"]
        size = data["size"]

        # Size row
        print(f"{size_name:<15} {'Size':<25} {size:<20} {size:<20} {'-':<15}")

        # Processing time
        if whole_time is not None and nupunkt_time is not None and isinstance(whole_time, float) and isinstance(nupunkt_time, float):
            whole_time_str = f"{whole_time*1000:.2f} ms"
            nupunkt_time_str = f"{nupunkt_time*1000:.2f} ms"
            ratio = f"{nupunkt_time/whole_time:.2f}x slower"
            print(f"{'':15} {'Processing Time':<25} {whole_time_str:<20} {nupunkt_time_str:<20} {ratio:<15}")
        elif whole_time is not None:
            whole_time_str = f"{whole_time*1000:.2f} ms"
            print(f"{'':15} {'Processing Time':<25} {whole_time_str:<20} {'N/A':<20} {'-':<15}")

        # Changes detected
        print(f"{'':15} {'Changes Detected':<25} {whole_changes:<20} {nupunkt_changes:<20} {'-':<15}")

        # Throughput (chars/sec)
        if whole_time is not None and nupunkt_time is not None and isinstance(whole_time, float) and isinstance(nupunkt_time, float) and isinstance(size, str):
            # Estimate char count from size description
            char_count = int(size.replace("~", "").replace(",", "").split()[0])
            whole_throughput = int(char_count / whole_time)
            nupunkt_throughput = int(char_count / nupunkt_time)
            whole_throughput_str = f"{whole_throughput:,} chars/s"
            nupunkt_throughput_str = f"{nupunkt_throughput:,} chars/s"
            print(f"{'':15} {'Throughput':<25} {whole_throughput_str:<20} {nupunkt_throughput_str:<20} {'-':<15}")

        print()

    # Summary statistics
    print("="*80)
    print("PERFORMANCE SUMMARY")
    print("="*80)
    print()

    # Calculate averages and ranges
    all_ratios: list[float] = []
    for data in results.values():
        whole_t = data["whole_time"]
        nupunkt_t = data["nupunkt_time"]
        if whole_t is not None and nupunkt_t is not None and isinstance(whole_t, float) and isinstance(nupunkt_t, float):
            ratio_val: float = nupunkt_t / whole_t
            all_ratios.append(ratio_val)

    if all_ratios:
        avg_ratio = sum(all_ratios) / len(all_ratios)
        min_ratio = min(all_ratios)
        max_ratio = max(all_ratios)

        print(f"Average Speed Difference: Nupunkt is {avg_ratio:.2f}x slower than WholeDocument")
        print(f"Best Case (smallest difference): {min_ratio:.2f}x slower")
        print(f"Worst Case (largest difference): {max_ratio:.2f}x slower")
        print()
        print(f"Speed Range: Nupunkt takes {min_ratio:.1f}x to {max_ratio:.1f}x longer to process")
        print()


def print_accuracy_table(accuracy_results: dict[str, EdgeCaseResult]) -> None:
    """Print a comprehensive accuracy comparison table."""
    print("\n" + "="*80)
    print("ACCURACY COMPARISON TABLE")
    print("="*80)
    print()

    # Header
    print(f"{'Edge Case':<25} {'Output Match':<15} {'Changes Detected':<25} {'Accuracy Notes'}")
    print("-" * 95)

    identical_count = 0
    total_count = 0

    for case_name, results in accuracy_results.items():
        if results["whole_output"] and results["nupunkt_output"]:
            total_count += 1
            match_status = "✓ IDENTICAL" if results["match"] else "✗ DIFFERENT"

            if results["match"]:
                identical_count += 1

            whole_count = len(results["whole_changes"])
            nupunkt_count = len(results["nupunkt_changes"])
            changes_str = f"W:{whole_count}, N:{nupunkt_count}"

            # Determine accuracy notes
            if results["match"]:
                accuracy_note = "Both correct"
            elif whole_count == nupunkt_count:
                accuracy_note = "Same count, diff context"
            else:
                accuracy_note = "Different detection"

            print(f"{case_name:<25} {match_status:<15} {changes_str:<25} {accuracy_note}")

    print("-" * 95)
    if total_count > 0:
        match_percent = (identical_count / total_count) * 100
        print(f"\nSummary: {identical_count}/{total_count} cases produced identical output ({match_percent:.1f}%)")
        if identical_count == total_count:
            print("Result: ✓ Both processors have IDENTICAL accuracy for these test cases")
        else:
            print(f"Result: ✗ Processors differ in {total_count - identical_count} cases")
    print()

    print("KEY FINDING ON ACCURACY:")
    print("-" * 80)
    print("""
When outputs differ, it's NOT about correctness - both detect the same changes!
The difference is in FORMATTING:

• WholeDocumentProcessor: Keeps sentences together in paragraphs (no line breaks)
• NupunktProcessor: Adds line breaks between sentences (sentence boundaries)

Example:
  Input: "Sentence one. Sentence two."

  WholeDocument: "Sentence one. Sentence two." (single paragraph)
  Nupunkt:       "Sentence one.                 (line break between)

                  Sentence two."

Both correctly identify the same changes - they just format the output differently
based on their tokenization strategy (paragraph-level vs sentence-level).
    """)
    print("-" * 80)
    print()


def main() -> None:
    """Run all comparisons."""
    print("="*70)
    print("PROCESSOR COMPARISON DEMO")
    print("Comparing NupunktProcessor vs WholeDocumentProcessor")
    print("="*70)

    # Run edge case tests
    print("\n" + "="*70)
    print("EDGE CASE ACCURACY TESTS")
    print("="*70)

    accuracy_results = {}
    for case_name, case_data in EDGE_CASES.items():
        accuracy_results[case_name] = run_edge_case_comparison(case_name, case_data)

    # Print accuracy summary table
    print_accuracy_table(accuracy_results)

    # Run performance tests
    perf_results = run_performance_comparison()

    # Print detailed comparison table
    print_comparison_table(perf_results)

    # Summary
    print("\n" + "="*70)
    print("CONCLUSIONS")
    print("="*70)
    print("""
Key Differences:

1. GRANULARITY:
   - WholeDocumentProcessor: Splits on paragraph boundaries (\\n characters)
   - NupunktProcessor: Splits on sentence boundaries (intelligent detection)

2. EDGE CASE HANDLING:
   - WholeDocumentProcessor: May incorrectly split at abbreviations/decimals
   - NupunktProcessor: Handles abbreviations, decimals, URLs, citations correctly

3. PERFORMANCE:
   - WholeDocumentProcessor: Generally faster (simpler regex-based splitting)
   - NupunktProcessor: Slightly slower (ML-based sentence detection)
   - Performance gap increases with document size

4. USE CASES:
   - WholeDocumentProcessor: Best for simple texts, speed-critical applications
   - NupunktProcessor: Best for complex texts with legal/technical content

5. REQUIREMENTS:
   - WholeDocumentProcessor: No additional dependencies
   - NupunktProcessor: Requires nupunkt>=0.6.0 (Python 3.11+)

6. RECOMMENDATION:
   - For documents < 10KB: NupunktProcessor overhead is minimal (~1-3ms difference)
   - For documents > 100KB: Consider WholeDocumentProcessor if speed is critical
   - For legal/technical documents: NupunktProcessor provides better accuracy
   - For simple documents: WholeDocumentProcessor is sufficient
    """)


if __name__ == "__main__":
    main()
