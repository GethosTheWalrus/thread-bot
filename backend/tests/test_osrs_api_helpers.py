from types import SimpleNamespace
from app.api.osrs import parse_mcp_response

def test_parse_mcp_structured_response():
    assert parse_mcp_response(SimpleNamespace(structuredContent={"loadouts": []}, content=[])) == {"loadouts": []}

def test_parse_mcp_json_text_response():
    result = SimpleNamespace(content=[SimpleNamespace(text='{"items": [{"id": 1}]}')])
    assert parse_mcp_response(result)["items"][0]["id"] == 1

def test_parse_mcp_plain_text_response_is_safe():
    result = SimpleNamespace(content=[SimpleNamespace(text="not json")])
    assert parse_mcp_response(result) == {"text": "not json"}
