"""Endpoint management for dynamic API endpoints.

This module provides the EndpointManager class which handles adding, removing,
and calling dynamic API endpoints, converting them to MCP tools.
"""

import asyncio
import json
import logging
from dataclasses import asdict
from typing import Any, Dict, List

import aiohttp
from google.adk.tools.function_tool import FunctionTool

from .models import APIEndpoint, APIParameter, HTTPMethod


class EndpointManager:
    """Manages API endpoints and their conversion to MCP tools
    
    This class handles adding/removing endpoints and maintaining the mapping
    between API endpoints and their corresponding MCP tools.
    """
    
    def __init__(self):
        self.endpoints: Dict[str, APIEndpoint] = {}
        self.tools: Dict[str, FunctionTool] = {}
        logging.info(f"[EndpointManager] Initialized endpoint manager")

    def add_endpoint(self, endpoint: APIEndpoint) -> None:
        """Add a new API endpoint and create a corresponding MCP tool
        
        Args:
            endpoint: APIEndpoint configuration to add
            
        Raises:
            ValueError: If endpoint name already exists
        """
        if endpoint.name in self.endpoints:
            raise ValueError(f"Endpoint '{endpoint.name}' already exists")
        self.endpoints[endpoint.name] = endpoint
        
        def create_endpoint_function(endpoint_name: str, params: List[APIParameter]):
            import inspect
            
            sig_params = []
            annotations = {}
            
            for param in params:
                if param.type == "string":
                    param_type = str
                elif param.type == "number":
                    param_type = float
                elif param.type == "boolean":
                    param_type = bool
                else:
                    param_type = Any
                
                annotations[param.name] = param_type
                
                if param.required:
                    sig_params.append(
                        inspect.Parameter(
                            param.name, 
                            inspect.Parameter.POSITIONAL_OR_KEYWORD,
                            annotation=param_type
                        )
                    )
                else:
                    default_val = param.default if param.default is not None else None
                    sig_params.append(
                        inspect.Parameter(
                            param.name, 
                            inspect.Parameter.POSITIONAL_OR_KEYWORD,
                            default=default_val,
                            annotation=param_type
                        )
                    )
            
            sig = inspect.Signature(sig_params, return_annotation=dict)
            
            async def endpoint_function(*args, **kwargs):
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                return await self._call_api_endpoint(endpoint_name, dict(bound.arguments))
            
            endpoint_function.__name__ = endpoint_name
            endpoint_function.__doc__ = endpoint.description
            endpoint_function.__signature__ = sig
            endpoint_function.__annotations__ = {**annotations, 'return': dict}
            
            return endpoint_function
        
        endpoint_function = create_endpoint_function(endpoint.name, endpoint.parameters)
        
        tool = FunctionTool(endpoint_function)
        self.tools[endpoint.name] = tool
        
        logging.info(f"[EndpointManager] Added endpoint '{endpoint.name}' as MCP tool ({endpoint.method.value} {endpoint.url})")

    async def _call_api_endpoint(self, endpoint_name: str, arguments: dict) -> dict:
        """Call the actual API endpoint with the provided arguments
        
        Args:
            endpoint_name: Name of the endpoint to call
            arguments: Arguments to pass to the API endpoint
            
        Returns:
            Dict containing success status, data, and message
        """
        if endpoint_name not in self.endpoints:
            logging.error(f"[EndpointManager] Endpoint '{endpoint_name}' not found")
            return {"success": False, "message": f"Endpoint '{endpoint_name}' not found"}
        
        endpoint = self.endpoints[endpoint_name]
        logging.info(f"[EndpointManager] Calling {endpoint.method.value} {endpoint.url} with args: {arguments}")
        
        try:
            for param in endpoint.parameters:
                if param.required and param.name not in arguments:
                    return {
                        "success": False, 
                        "message": f"Missing required parameter: {param.name}"
                    }
            
            url = endpoint.url
            for param_name, param_value in arguments.items():
                url = url.replace(f"{{{param_name}}}", str(param_value))
            
            headers = endpoint.headers or {}
            timeout = aiohttp.ClientTimeout(total=endpoint.timeout)
            
            request_args = arguments.copy()
            if endpoint.method in [HTTPMethod.GET, HTTPMethod.DELETE]:
                for param_name in arguments.keys():
                    if f"{{{param_name}}}" in endpoint.url:
                        request_args.pop(param_name, None)
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                if endpoint.method == HTTPMethod.GET:
                    async with session.get(url, params=request_args, headers=headers) as response:
                        return await self._process_response(response, endpoint_name)
                        
                elif endpoint.method in [HTTPMethod.POST, HTTPMethod.PUT, HTTPMethod.PATCH]:
                    headers.setdefault('Content-Type', 'application/json')
                    async with session.request(
                        endpoint.method.value, 
                        url, 
                        json=arguments, 
                        headers=headers
                    ) as response:
                        return await self._process_response(response, endpoint_name)
                        
                elif endpoint.method == HTTPMethod.DELETE:
                    async with session.delete(url, params=request_args, headers=headers) as response:
                        return await self._process_response(response, endpoint_name)
                        
        except aiohttp.ClientTimeout:
            error_msg = f"Request to {url} timed out after {endpoint.timeout} seconds"
            logging.error(f"[EndpointManager] {error_msg}")
            return {"success": False, "message": error_msg}
        except Exception as e:
            logging.exception(f"[EndpointManager] Error calling endpoint '{endpoint_name}': {e}")
            return {"success": False, "message": f"Error calling API: {str(e)}"}

    async def _process_response(self, response: aiohttp.ClientResponse, endpoint_name: str) -> dict:
        """Process the HTTP response and return a standardized result
        
        Args:
            response: HTTP response object
            endpoint_name: Name of the endpoint that was called
            
        Returns:
            Dict containing success status, data, and message
        """
        try:
            if response.content_type and 'json' in response.content_type:
                data = await response.json()
            else:
                data = await response.text()
            
            if response.status >= 200 and response.status < 300:
                logging.info(f"[EndpointManager] API call successful: {endpoint_name} returned {response.status}")
                return {
                    "success": True,
                    "status_code": response.status,
                    "data": data,
                    "message": f"Successfully called {endpoint_name}"
                }
            else:
                logging.warning(f"[EndpointManager] API call failed: {endpoint_name} returned {response.status}")
                return {
                    "success": False,
                    "status_code": response.status,
                    "data": data,
                    "message": f"API call failed with status {response.status}"
                }
                
        except Exception as e:
            logging.exception(f"[EndpointManager] Error processing response from {endpoint_name}: {e}")
            return {
                "success": False,
                "status_code": response.status,
                "message": f"Error processing response: {str(e)}"
            }

    def remove_endpoint(self, endpoint_name: str) -> bool:
        """Remove an endpoint and its corresponding tool
        
        Args:
            endpoint_name: Name of the endpoint to remove
            
        Returns:
            True if endpoint was removed, False if it didn't exist
        """
        removed = False
        if endpoint_name in self.endpoints:
            del self.endpoints[endpoint_name]
            removed = True
        if endpoint_name in self.tools:
            del self.tools[endpoint_name]
            removed = True
            
        if removed:
            logging.info(f"[EndpointManager] Removed endpoint '{endpoint_name}'")
        else:
            logging.warning(f"[EndpointManager] Endpoint '{endpoint_name}' not found for removal")
            
        return removed

    def get_tools(self) -> Dict[str, FunctionTool]:
        """Get all registered tools
        
        Returns:
            Dictionary of tool name to FunctionTool mappings
        """
        return self.tools

    def list_endpoints(self) -> List[dict]:
        """List all configured endpoints
        
        Returns:
            List of endpoint configurations as dictionaries
        """
        result = []
        for endpoint in self.endpoints.values():
            endpoint_dict = asdict(endpoint)
            endpoint_dict['method'] = endpoint.method.value
            result.append(endpoint_dict)
        return result


__all__ = [
    "EndpointManager",
]
