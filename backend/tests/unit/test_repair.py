from aura.agents.llm.repair import extract_json


def test_plain_json():
    assert extract_json('{"tool": "send_email"}') == {"tool": "send_email"}


def test_json_in_fenced_code_block():
    text = 'Here is the call:\n```json\n{"tool": "send_email", "to": "a@b.com"}\n```\nDone.'
    assert extract_json(text) == {"tool": "send_email", "to": "a@b.com"}


def test_json_with_prose_preamble():
    assert extract_json('I will call {"tool": "list_deals"} now') == {"tool": "list_deals"}


def test_trailing_comma_is_repaired():
    assert extract_json('{"tool": "list_deals",}') == {"tool": "list_deals"}


def test_single_quotes_are_repaired():
    assert extract_json("{'tool': 'list_deals'}") == {"tool": "list_deals"}


def test_unrecoverable_returns_none():
    assert extract_json("I am not sure what to do here.") is None
