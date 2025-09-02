import contextlib
import json
import logging
import os
import sys
from collections.abc import AsyncIterator
from typing import Any, Dict, List

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import Receive, Scope, Send

from latinum_wallet_mcp.dynamic import (
    DynamicMCPServer,
    EndpointManager,
    APIEndpoint,
    APIParameter,
    HTTPMethod,
)

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='[%(levelname)s] %(message)s')

endpoint_manager = EndpointManager()
dynamic_server = DynamicMCPServer("dynamic-api-mcp", endpoint_manager)

def create_endpoint_from_config(config: dict) -> APIEndpoint:
    """Create an APIEndpoint from a configuration dictionary
    
    Args:
        config: Dictionary containing endpoint configuration
        
    Returns:
        APIEndpoint instance
        
    Raises:
        KeyError: If required configuration keys are missing
        ValueError: If configuration values are invalid
    """
    parameters = [
        APIParameter(**param) for param in config.get("parameters", [])
    ]
    
    return APIEndpoint(
        name=config["name"],
        url=config["url"],
        method=HTTPMethod(config["method"]),
        description=config["description"],
        parameters=parameters,
        headers=config.get("headers"),
        timeout=config.get("timeout", 30.0)
    )

async def add_endpoint_handler(request: Request) -> JSONResponse:
    """HTTP endpoint to dynamically add new API endpoints
    
    Args:
        request: Starlette request containing endpoint configuration JSON
        
    Returns:
        JSON response indicating success or failure
    """
    try:
        body = await request.json()
        endpoint = create_endpoint_from_config(body)
        endpoint_manager.add_endpoint(endpoint)
        
        logging.info(f"[DynamicHTTP] Successfully added endpoint '{endpoint.name}'")
        return JSONResponse({
            "success": True,
            "message": f"Successfully added endpoint '{endpoint.name}'",
            "endpoint": {
                "name": endpoint.name,
                "url": endpoint.url,
                "method": endpoint.method.value
            }
        })
    except Exception as e:
        logging.error(f"[DynamicHTTP] Error adding endpoint: {e}")
        return JSONResponse({
            "success": False,
            "message": f"Error adding endpoint: {str(e)}"
        }, status_code=400)

async def remove_endpoint_handler(request: Request) -> JSONResponse:
    """HTTP endpoint to remove an API endpoint
    
    Args:
        request: Starlette request with endpoint name in path parameters
        
    Returns:
        JSON response indicating success or failure
    """
    try:
        endpoint_name = request.path_params.get("name")
        if not endpoint_name:
            logging.warning("[DynamicHTTP] Remove endpoint called without name")
            return JSONResponse({
                "success": False,
                "message": "Endpoint name is required"
            }, status_code=400)
        
        removed = endpoint_manager.remove_endpoint(endpoint_name)
        
        if removed:
            logging.info(f"[DynamicHTTP] Successfully removed endpoint '{endpoint_name}'")
            return JSONResponse({
                "success": True,
                "message": f"Successfully removed endpoint '{endpoint_name}'"
            })
        else:
            return JSONResponse({
                "success": False,
                "message": f"Endpoint '{endpoint_name}' not found"
            }, status_code=404)
    except Exception as e:
        logging.error(f"[DynamicHTTP] Error removing endpoint: {e}")
        return JSONResponse({
            "success": False,
            "message": f"Error removing endpoint: {str(e)}"
        }, status_code=500)

async def list_endpoints_handler(request: Request) -> JSONResponse:
    """HTTP endpoint to list all configured endpoints
    
    Args:
        request: Starlette request object
        
    Returns:
        JSON response with list of endpoints
    """
    try:
        endpoints = endpoint_manager.list_endpoints()
        return JSONResponse({
            "success": True,
            "endpoints": endpoints,
            "count": len(endpoints)
        })
    except Exception as e:
        logging.error(f"[DynamicHTTP] Error listing endpoints: {e}")
        return JSONResponse({
            "success": False,
            "message": f"Error listing endpoints: {str(e)}"
        }, status_code=500)

async def health_handler(request: Request) -> JSONResponse:
    """Health check endpoint
    
    Args:
        request: Starlette request object
        
    Returns:
        JSON response with server health status
    """
    return JSONResponse({
        "status": "healthy",
        "server": "dynamic-mcp-server",
        "endpoints_count": len(endpoint_manager.endpoints),
        "tools_count": len(endpoint_manager.tools)
    })

def main() -> None:
    """Main function to start the dynamic MCP HTTP server"""
    port = int(os.getenv("PORT", 8080))
    host = os.getenv("HOST", "0.0.0.0")
    
   
    logging.info(f"[DynamicHTTP] Starting with no initial endpoints - use HTTP API to add endpoints")

    
    mcp_server = dynamic_server.get_server()

    session_manager = StreamableHTTPSessionManager(
        app=mcp_server,
        event_store=None,
        json_response=True,
        stateless=True,
    )

    async def handle_streamable_http(scope: Scope, receive: Receive, send: Send) -> None:
        """Handle MCP protocol requests via streamable HTTP"""
        await session_manager.handle_request(scope, receive, send)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        """Context manager for session manager lifecycle
        
        Args:
            app: Starlette application instance
            
        Yields:
            None during server lifetime
        """
        async with session_manager.run():
            logging.info(f"[DynamicHTTP] Dynamic MCP Server started on {host}:{port}")
            logging.info("[DynamicHTTP] Available endpoints:")
            logging.info(f"[DynamicHTTP]   - POST http://{host}:{port}/ (MCP protocol)")
            logging.info(f"[DynamicHTTP]   - POST http://{host}:{port}/api/endpoints (Add endpoint)")
            logging.info(f"[DynamicHTTP]   - DELETE http://{host}:{port}/api/endpoints/{{name}} (Remove endpoint)")
            logging.info(f"[DynamicHTTP]   - GET http://{host}:{port}/api/endpoints (List endpoints)")
            logging.info(f"[DynamicHTTP]   - GET http://{host}:{port}/health (Health check)")
            
            endpoint_names = list(endpoint_manager.endpoints.keys())
            tool_names = list(endpoint_manager.tools.keys())
            logging.info(f"[DynamicHTTP]   - Loaded endpoints: {endpoint_names}")
            logging.info(f"[DynamicHTTP]   - Available tools: {tool_names}")
            
            if not tool_names:
                logging.warning("[DynamicHTTP] No tools available! Claude won't see any tools.")
            else:
                logging.info(f"[DynamicHTTP] {len(tool_names)} tools ready for Claude")
                
            try:
                yield
            finally:
                logging.info("[DynamicHTTP] Dynamic MCP Server shutting down...")

    starlette_app = Starlette(
        debug=True,
        routes=[
            Route("/api/endpoints", add_endpoint_handler, methods=["POST"]),
            Route("/api/endpoints/{name}", remove_endpoint_handler, methods=["DELETE"]),
            Route("/api/endpoints", list_endpoints_handler, methods=["GET"]),
            Route("/health", health_handler, methods=["GET"]),
            Mount("/", app=handle_streamable_http),
        ],
        lifespan=lifespan,
    )

    import uvicorn
    uvicorn.run(starlette_app, host=host, port=port)

if __name__ == "__main__":
    main()

__all__ = [
    "create_endpoint_from_config",
    "add_endpoint_handler",
    "remove_endpoint_handler", 
    "list_endpoints_handler",
    "health_handler",
    "main"
]