from aura.mcp.servers.deals_server import add_internal_note, get_deal_status, list_deals


def test_get_deal_status_returns_known_deal():
    assert "Sunrise" in get_deal_status("D-001")


def test_get_deal_status_handles_unknown_deal():
    assert "No deal" in get_deal_status("D-999")


def test_list_deals_returns_all():
    result = list_deals()
    assert "D-001" in result and "D-002" in result


def test_add_internal_note_confirms():
    assert "D-001" in add_internal_note("D-001", "spoke to founder")
