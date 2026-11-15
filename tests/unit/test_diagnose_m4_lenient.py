from hashlib import sha256
from importlib import import_module
from pathlib import Path

import pytest


@pytest.fixture
def diagnostic(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    return import_module("diagnose_m4_lenient")


def test_selection_is_order_independent_and_public_receipt_contains_only_ids(diagnostic):
    sample = diagnostic.Sample("final")
    identifiers = [f"fixture:{i}" for i in range(25)]
    for identifier in reversed(identifiers):
        sample.add(identifier, {"private_text": "must remain in the review packet"})
    expected = sorted(identifiers, key=lambda eid: sha256(("20261116|" + eid).encode()).hexdigest())[:20]
    assert [row["id"] for row in sample.packet()] == expected
    packet = {key: sample.packet() if key == "final" else [] for key in diagnostic.LAYOUT}
    labels = {key: dict.fromkeys(expected, "correct") if key == "final" else {} for key in diagnostic.LAYOUT}
    report = diagnostic.spot_receipt(packet, labels)
    assert report["final"]["labels"]["correct"] == {"count": 20, "ids": expected}
    assert "private_text" not in str(report)
    labels["final"].pop(expected[0])
    with pytest.raises(ValueError, match="selected IDs"):
        diagnostic.spot_receipt(packet, labels)
