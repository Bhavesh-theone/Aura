import pytest

from aura.core.domain.enums import IdentifierScheme as K
from aura.core.domain.errors import RuleViolation
from aura.core.policy.identifier_policy import normalise_identifier


@pytest.mark.parametrize("scheme,value", [
    (K.PAN, "ABCDE1234F"), (K.GSTIN, "27ABCDE1234F1Z5"), (K.DIN, "01234567"),
    (K.CIN, "U12345MH2020PTC123456"), (K.LLPIN, "AAB-1234")])
def test_valid_identifiers(scheme, value):
    assert normalise_identifier(scheme, value) == value


def test_normalises_case_and_whitespace():
    assert normalise_identifier(K.PAN, " abcde1234f ") == "ABCDE1234F"


@pytest.mark.parametrize("scheme,value", [
    (K.PAN, "ABCDE12345"), (K.PAN, "ABCD1234F"), (K.GSTIN, "27ABCDE1234F1Z"),
    (K.DIN, "1234567"), (K.CIN, "X12345MH2020PTC123456"), (K.LLPIN, "AB-1234")])
def test_invalid_identifiers(scheme, value):
    with pytest.raises(RuleViolation):
        normalise_identifier(scheme, value)
