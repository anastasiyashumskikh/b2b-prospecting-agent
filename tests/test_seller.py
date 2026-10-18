from pathlib import Path

import pytest
from pydantic import ValidationError

from prospect.seller import load_seller

ROOT = Path(__file__).resolve().parent.parent


def test_every_seller_fact_has_source():
    s = load_seller(ROOT / "seller.yaml")
    assert s.facts and all(f.source.url.startswith("http") for f in s.facts)
    assert set(s.roles) == {"economic_buyer", "decision_maker", "champion"}


def test_seller_fact_without_source_rejected(tmp_path):
    f = tmp_path / "seller.yaml"
    f.write_text(
        "name: X\ncompany: X\nsummary: s\nicp: i\noffers: [a demo]\n"
        "fallback: {linkedin_note: n, email_subject: s, email_body: b}\n"
        "facts:\n  - text: no source here\n"
        "roles:\n"
        "  economic_buyer: {titles: [COO], pain: p}\n"
        "  champion: {titles: [Director], pain: p}\n"
        "  decision_maker: {titles: [CIO], pain: p}\n"
    )
    with pytest.raises(ValidationError):
        load_seller(f)
