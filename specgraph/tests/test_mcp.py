from specgraph.mcp_server import handle_rpc


def test_initialize_and_tools():
    r = handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert r["result"]["serverInfo"]["name"] == "specgraph"
    t = handle_rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {x["name"] for x in t["result"]["tools"]}
    assert "gather_context" in names
    assert "search_requirements" in names
