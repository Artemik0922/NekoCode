"""MCP (Model Context Protocol) integration for NekoCode.

Uses the MCP Python SDK v2 Client API.
"""

from mcp import Client, StdioServerParameters


class MCPServer:
    def __init__(self, name, command, args=None, env=None):
        self.name = name
        self.command = command
        self.args = args or []
        self.env = env or {}
        self._client = None
        self._tools = {}
        self._status = "disconnected"

    async def connect(self):
        merged_env = {**self.env}
        params = StdioServerParameters(command=self.command, args=self.args, env=merged_env)
        try:
            client = Client(params)
            await client.__aenter__()
            self._client = client
            result = await client.list_tools()
            if hasattr(result, "tools"):
                self._tools = {t.name: t for t in result.tools}
            else:
                self._tools = {}
            self._status = "connected"
        except Exception as e:
            self._status = f"error: {e}"
            raise

    async def disconnect(self):
        self._status = "disconnected"
        self._tools = {}
        if self._client:
            try:
                await self._client.__aexit__(None, None, None)
            except Exception:
                pass
            self._client = None

    async def call_tool(self, name, args):
        if not self._client:
            raise RuntimeError(f"MCP server '{self.name}' not connected")
        result = await self._client.call_tool(name, args)
        return result

    @property
    def tools(self):
        return dict(self._tools)

    @property
    def status(self):
        return self._status


class MCPManager:
    def __init__(self, agent):
        self.agent = agent
        self.servers = []
        self._tool_map = {}  # mcp_full_name -> (server_name, tool_name)

    def load_config(self):
        from nekocode.config import Config
        cfg = Config.load().data
        server_list = cfg.get("mcp_servers", [])
        if not server_list:
            return
        for entry in server_list:
            name = entry.get("name", entry.get("command", "unknown"))
            self.servers.append(MCPServer(
                name=name,
                command=entry["command"],
                args=entry.get("args", []),
                env=entry.get("env", {}),
            ))

    def register_tools(self):
        for server in self.servers:
            if server.status != "connected":
                continue
            for tool_name, tool_info in server.tools.items():
                full_name = f"mcp_{server.name}_{tool_name}"
                self._tool_map[full_name] = (server.name, tool_name)
                schema = tool_info.inputSchema if hasattr(tool_info, "inputSchema") else {}
                from nekocode.agent import MiniAgent
                MiniAgent.register_tool(
                    name=full_name,
                    fn=lambda args, srv=server, tn=tool_name: self._call_handler(srv, tn, args),
                    risky=False,
                    schema=schema,
                )

    def _call_handler(self, server, tool_name, args):
        try:
            import asyncio
            result = asyncio.run(server.call_tool(tool_name, args))
            parts = []
            if hasattr(result, "content"):
                for c in result.content:
                    if hasattr(c, "text"):
                        parts.append(c.text)
                    elif isinstance(c, dict):
                        parts.append(str(c.get("text", c)))
                    else:
                        parts.append(str(c))
            return "\n".join(parts) if parts else str(result)
        except Exception as e:
            return f"[MCP error] {e}"

    async def connect_all(self):
        results = {}
        for server in self.servers:
            try:
                await server.connect()
                results[server.name] = "connected"
            except Exception as e:
                results[server.name] = f"error: {e}"
        return results

    async def disconnect_all(self):
        for server in self.servers:
            try:
                await server.disconnect()
            except Exception:
                pass

    def summary(self):
        lines = []
        for server in self.servers:
            tools = list(server.tools.keys())
            lines.append(f"  {server.name}: {server.status} ({len(tools)} tools)")
            for t in tools[:5]:
                lines.append(f"    - {t}")
            if len(tools) > 5:
                lines.append(f"    ... +{len(tools) - 5} more")
        return "\n".join(lines) if lines else "  (no MCP servers configured)"
