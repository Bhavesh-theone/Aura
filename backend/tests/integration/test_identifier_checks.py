"""Statutory identifier formats are enforced by the database, whatever wrote the row (F3.1)."""
import pytest
from sqlalchemy import text

from tests.integration.helpers import party

VALID = [("PAN", "ABCDE1234F"), ("DIN", "01234567"), ("GSTIN", "27ABCDE1234F1Z5"),
         ("CIN", "U12345MH2020PTC123456"), ("CIN", "L99999DL1990PLC000001"),
         ("LLPIN", "AAB-1234")]
INVALID = [
    ("PAN", "abcde1234f"), ("PAN", "ABCD1234FF"), ("PAN", "ABCDE12345"), ("PAN", "ABCDE1234"),
    ("PAN", "ABCDE1234FG"), ("PAN", "ABCDE1234F "), ("PAN", ""),
    ("DIN", "1234567"), ("DIN", "123456789"), ("DIN", "1234567A"),
    ("GSTIN", "27ABCDE1234F1Z"), ("GSTIN", "AAABCDE1234F1Z5"), ("GSTIN", "27abcde1234f1z5"),
    ("GSTIN", "27ABCDE1234F1Z5X"),
    ("CIN", "X12345MH2020PTC123456"), ("CIN", "U12345MH2020PTC12345"),
    ("CIN", "u12345mh2020ptc123456"), ("CIN", "U1234MH2020PTC1234567"),
    ("LLPIN", "AA-1234"), ("LLPIN", "AAB1234"), ("LLPIN", "aab-1234"),
]


def _insert(api, party_id, scheme, value):
    api.session.execute(text("INSERT INTO party_identifier (party_id, scheme, value) "
                             "VALUES (:p, :s, :v)"), {"p": party_id, "s": scheme, "v": value})


@pytest.mark.parametrize("scheme, value", INVALID)
def test_a_malformed_identifier_cannot_be_inserted_raw(api, scheme, value):
    p = party(api, pan=None)["id"]
    with pytest.raises(Exception, match="ck_identifier_format"):
        _insert(api, p, scheme, value)
    api.session.rollback()


@pytest.mark.parametrize("scheme, value", VALID)
def test_a_well_formed_identifier_is_accepted_raw(api, scheme, value):
    p = party(api, pan=None)["id"]
    _insert(api, p, scheme, value)
    api.session.commit()
    assert api.session.execute(text("SELECT COUNT(*) FROM party_identifier WHERE scheme = :s"),
                               {"s": scheme}).scalar() == 1


def test_a_raw_update_cannot_break_a_stored_identifier(api):
    pid = party(api)["id"]
    with pytest.raises(Exception, match="ck_identifier_format"):
        api.session.execute(text("UPDATE party_identifier SET value = 'bad' WHERE party_id = "
                                 ":p"), {"p": pid})
    api.session.rollback()


def test_the_service_and_the_database_agree_on_every_valid_value(api):
    """Whatever the service accepts (it upper-cases first) the database accepts."""
    for scheme, value in VALID:
        r = api.call("POST", "/api/parties", json={
            "party_type": "company", "display_name": f"P {scheme} {value}",
            "identifiers": [{"scheme": scheme, "value": value.lower()}]})
        assert r.status_code == 201, (scheme, value, r.text)
        assert r.json()["identifiers"][0]["value"] == value