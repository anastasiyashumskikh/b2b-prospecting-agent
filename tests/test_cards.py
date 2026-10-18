from datetime import date

from prospect.cards import CardStore
from prospect.models import Contact, Source


def contact() -> Contact:
    return Contact(
        name="José Müller", title="CIO", company="Acme Corp", buying_role="decision_maker", relevance=4,
        relevance_reason="r", why="w", sources=[Source(url="https://a.com")], confidence="high",
        linkedin_status="not_found", role_evidence="e",
    )  # fmt: skip


def test_card_reused_within_ttl(tmp_path):
    CardStore(tmp_path, 14, date(2026, 10, 1)).put("Acme Corp", contact())
    card = CardStore(tmp_path, 14, date(2026, 10, 15)).get("Acme Corp", "Jose Muller")
    assert card is not None and card.contact.name == "José Müller" and card.context is None
    assert (tmp_path / "acme" / "j-muller.json").exists()


def test_card_expired_after_ttl(tmp_path):
    CardStore(tmp_path, 14, date(2026, 10, 1)).put("Acme Corp", contact())
    assert CardStore(tmp_path, 14, date(2026, 10, 16)).get("Acme Corp", "José Müller") is None


def test_missing_card_is_none(tmp_path):
    assert CardStore(tmp_path, 14, date(2026, 10, 1)).get("Acme Corp", "Nobody") is None


def test_card_folder_uses_short_company_name(tmp_path):
    store = CardStore(tmp_path, 14, date(2026, 10, 1))
    store.put("IKEA (Inter IKEA Group, franchisor)", contact())
    assert store.get("IKEA", "José Müller") is not None and (tmp_path / "ikea").is_dir()
