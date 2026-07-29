"""Tests for MCP integration."""

from nekocode.mcp import MCPManager, MCPServer


class TestMCPServer:
    def test_init_defaults(self):
        srv = MCPServer("test", "echo")
        assert srv.name == "test"
        assert srv.command == "echo"
        assert srv.args == []
        assert srv.env == {}
        assert srv.status == "disconnected"

    def test_status_disconnected_by_default(self):
        srv = MCPServer("x", "y")
        assert srv.status == "disconnected"

    def test_tools_empty_disconnected(self):
        srv = MCPServer("x", "y")
        assert srv.tools == {}


class TestMCPManager:
    def test_init_no_agent(self):
        mgr = MCPManager(None)
        assert mgr.servers == []
        assert mgr._tool_map == {}

    def test_load_config_no_servers(self):
        mgr = MCPManager(None)
        mgr.load_config()
        assert mgr.servers == []

    def test_summary_empty(self):
        mgr = MCPManager(None)
        s = mgr.summary()
        assert "no MCP servers" in s

    def test_disconnect_all_empty(self):
        import asyncio
        mgr = MCPManager(None)
        asyncio.run(mgr.disconnect_all())

    def test_connect_all_empty(self):
        import asyncio
        mgr = MCPManager(None)
        result = asyncio.run(mgr.connect_all())
        assert result == {}
