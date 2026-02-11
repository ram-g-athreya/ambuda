"""Verify that the Dharmamitra API is accepting requests.

Usage:
    uv run scripts/dharmamitra_demo.py
"""

from dharmamitra_sanskrit_grammar import DharmamitraSanskritProcessor as DSP


def main():
    processor = DSP()
    sentences = ["rāmo gṛham gacchati"]

    print(f"Sending {len(sentences)} sentence(s) to Dharmamitra API...")
    print(f"  URL: {processor.api_url}")
    print()

    results = processor.process_batch(
        sentences,
        mode="unsandhied-lemma-morphosyntax",
        human_readable_tags=False,
    )

    if not results:
        print("ERROR: No results returned from Dharmamitra.")
        raise SystemExit(1)

    for sentence_result in results:
        print(f"Sentence: {sentence_result['sentence']}")
        for token in sentence_result["grammatical_analysis"]:
            print(f"  {token['unsandhied']:20s} lemma={token['lemma']:15s} tag={token['tag']}")

    print()
    print("OK: Dharmamitra API is responding.")


if __name__ == "__main__":
    main()
