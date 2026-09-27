"""Public Terms and Privacy documents (store readiness, spec §23.1 bot disclosure, §30 deletion)."""

from __future__ import annotations

import pytest

from app.common.settings import Settings
from app.legal.documents import DOCUMENTS, LegalIdentity, render
from app.profiles.service import PRIVACY_VERSION, TERMS_VERSION

IDENTITY = LegalIdentity(operator="Acme Games Ltd", contact="privacy@acme.test", address="1 Main St",
                         law="the laws of Testland", effective="2026-09-27")


@pytest.mark.parametrize("doc", ["terms", "privacy"])
def test_documents_have_matching_languages_and_no_unfilled_placeholders(doc):
    en = render(doc, "en", IDENTITY)[1]
    tr = render(doc, "tr", IDENTITY)[1]
    assert len(en) == len(tr) == len(DOCUMENTS[doc]["en"])
    text = " ".join(p for s in en + tr for p in [s["heading"], *s["paragraphs"]])
    assert "{" not in text and "}" not in text and "Acme Games Ltd" in text and "privacy@acme.test" in text


def test_terms_disclose_computer_opponents_and_privacy_describes_immediate_deletion():
    terms = str(render("terms", "en", IDENTITY)[1])
    assert "computer-controlled" in terms
    assert "bilgisayar kontrollü" in str(render("terms", "tr", IDENTITY)[1])
    privacy = str(render("privacy", "en", IDENTITY)[1])
    assert "Deletion starts immediately" in privacy and "date of birth" in privacy


def test_public_json_and_html_endpoints(client):
    res = client.get("/v1/legal/terms", params={"lang": "tr"})
    assert res.status_code == 200
    body = res.json()
    assert body["version"] == TERMS_VERSION and body["language"] == "tr" and body["title"] == "Kullanım Koşulları"
    assert client.get("/v1/legal/privacy").json()["version"] == PRIVACY_VERSION
    page = client.get("/legal/privacy", headers={"accept-language": "en-GB,en"})
    assert page.status_code == 200 and "Privacy Policy" in page.text and "<script" not in page.text
    assert client.get("/v1/legal/cookies").status_code == 404


def test_production_requires_legal_identity():
    base = dict(env="stage", auth_mode="firebase", store_backend="firebase", admob_ssv_mode="google",
                purchase_verify_mode="store")
    with pytest.raises(ValueError, match="legal"):
        Settings(**base)
    Settings(**base, legal_operator_name="Acme", legal_contact_email="a@acme.test", legal_governing_law="law")
