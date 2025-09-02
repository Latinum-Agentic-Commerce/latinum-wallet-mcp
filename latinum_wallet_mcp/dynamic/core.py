"""Core MCP server implementation for dynamic API endpoints.

This module provides the DynamicMCPServer class which serves as the main
MCP server that handles tool listing and execution using an EndpointManager.
"""

import json
import logging
import sys

from google.adk.tools.mcp_tool.conversion_utils import adk_to_mcp_tool_type
from mcp import types as mcp_types
from mcp.server.lowlevel import Server

from .endpoint_manager import EndpointManager

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='[%(levelname)s] %(message)s')


class DynamicMCPServer:
    """Pure MCP Server that serves tools from an EndpointManager
    
    This server focuses solely on MCP protocol handling (list_tools, call_tool)
    and delegates all endpoint management to an EndpointManager instance.
    
    Args:
        server_name: Name for the MCP server instance
        endpoint_manager: EndpointManager instance to get tools from
    """
    
    def __init__(self, server_name: str = "dynamic-mcp-server", endpoint_manager: EndpointManager = None):
        self.server_name = server_name
        self.server = Server(server_name)
        self.endpoint_manager = endpoint_manager or EndpointManager()
        self._setup_server()
        logging.info(f"[DynamicMCP] Initialized MCP server '{server_name}'")
        
    def _setup_server(self) -> None:
        """Setup the MCP server with list_tools and call_tool handlers"""
        
        @self.server.list_tools() 
        async def list_tools():
            tool_list = []
            for tool in self.endpoint_manager.tools.values():
                try:
                    mcp_tool = adk_to_mcp_tool_type(tool)
                    logging.info(f"[DynamicMCP] Converted tool '{tool.name}' - Schema: {mcp_tool.inputSchema}")
                    tool_list.append(mcp_tool)
                except Exception as e:
                    logging.error(f"[DynamicMCP] Error converting tool {tool.name} to MCP type: {e}")
            logging.info(f"[DynamicMCP] Returning {len(tool_list)} tools to MCP client")
            return tool_list

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict):
            logging.info(f"[DynamicMCP] Tool call: {name} with args: {json.dumps(arguments)}")
            try:
                if name not in self.endpoint_manager.tools:
                    logging.warning(f"[DynamicMCP] Tool '{name}' not found")
                    return [mcp_types.TextContent(type="text", text=f"Tool '{name}' not found")]
                
                tool = self.endpoint_manager.tools[name]
                result = await tool.run_async(args=arguments, tool_context=None)
                logging.info(f"[DynamicMCP] Tool '{name}' execution result: {result}")
                
                if isinstance(result, dict):
                    if result.get("success"):
                        data = result.get("data")
                        if data:
                            formatted_message = f"{result.get('message', 'Success')}\n\nResponse Data:\n{json.dumps(data, indent=2)}"
                        else:
                            formatted_message = result.get("message", "Success - no data returned")
                    else:
                        formatted_message = result.get("message", "Unknown error occurred")
                else:
                    formatted_message = str(result)
                    
                return [mcp_types.TextContent(type="text", text=formatted_message)]
                
            except Exception as e:
                logging.exception(f"[DynamicMCP] Error executing tool '{name}': {e}")
                return [mcp_types.TextContent(type="text", text=f"Error executing tool: {str(e)}")]

    def get_server(self) -> Server:
        """Get the configured MCP server instance
        
        Returns:
            The underlying MCP Server instance
        """
        return self.server

    def get_endpoint_manager(self) -> EndpointManager:
        """Get the endpoint manager instance
        
        Returns:
            The EndpointManager instance
        """
        return self.endpoint_manager


__all__ = [
    "DynamicMCPServer",
]