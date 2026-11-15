"""Locate Judge quotes in the original Unicode text and retain source coordinates."""

from functools import cached_property
import re
import unicodedata

from .common import require


def normalized_text(text):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text))


def decomposed_offsets(text):
    """Give the source index for each code point in canonically ordered NFKD."""
    segment = []
    for index, character in enumerate(text):
        for decomposed in unicodedata.normalize("NFKD", character):
            order = unicodedata.combining(decomposed)
            if order == 0 and segment:
                yield from (offset for _, offset in sorted(segment, key=lambda item: item[0]))
                segment.clear()
            segment.append((order, index))
    yield from (offset for _, offset in sorted(segment, key=lambda item: item[0]))


def occurrences(text, needle):
    start = text.find(needle)
    while start >= 0:
        yield start, start + len(needle)
        start = text.find(needle, start + 1)


class QuoteLocator:
    def __init__(self, source):
        self.source = source

    @cached_property
    def normalized(self):
        text = unicodedata.normalize("NFKC", self.source)
        # The source and NFKC result have the same canonically ordered NFKD.
        offsets = [[] for _ in text]
        for start, index in zip(decomposed_offsets(self.source), decomposed_offsets(text), strict=True):
            offsets[index].append(start)
        pieces, spans = [], []
        for match in re.finditer(r"\s+|\S", text):
            chars = offsets[match.start():match.end()]
            spans.append((min(min(item) for item in chars), max(max(item) for item in chars) + 1))
            pieces.append(" " if match.group().isspace() else match.group())
        return "".join(pieces), spans

    def locate(self, quote, *, last=False):
        require(isinstance(quote, str) and quote.strip(), "empty evidence quote")
        matches = list(occurrences(self.source, quote))
        method = "exact"
        if not matches:
            normalized, offsets = self.normalized
            needle = normalized_text(quote)
            found = set()
            for start, end in occurrences(normalized, needle):
                cover = offsets[start:end]
                left = min(index[0] for index in cover)
                right = max(index[1] for index in cover)
                if normalized_text(self.source[left:right]) == needle:
                    found.add((left, right))
            matches = sorted(found)
            method = "normalized"
        require(bool(matches), "evidence quote not found in source")
        start, end = matches[-1 if last else 0]
        return {"start": start, "end": end, "quote": self.source[start:end], "coordinate": "source_char",
                "location_method": "multi" if len(matches) > 1 else method, "occurrences": len(matches)}
