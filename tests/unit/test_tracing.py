from finance_mcp.core.tracing import _parse_headers


def test_parse_headers_empty_when_none() -> None:
    assert _parse_headers(None) == {}


def test_parse_headers_single_pair() -> None:
    assert _parse_headers("Authorization=Basic abc123") == {"Authorization": "Basic abc123"}


def test_parse_headers_multiple_pairs() -> None:
    result = _parse_headers("a=1,b=2")
    assert result == {"a": "1", "b": "2"}


def test_parse_headers_ignores_malformed_entries() -> None:
    assert _parse_headers("a=1,not-a-pair,b=2") == {"a": "1", "b": "2"}
