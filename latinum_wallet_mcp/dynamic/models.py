"""Data models for dynamic API endpoints and parameters.

This module contains the core data structures used to define API endpoints
that can be dynamically registered with the MCP server.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class HTTPMethod(Enum):
    """Supported HTTP methods for API endpoints"""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"


@dataclass
class APIParameter:
    """Configuration for an API endpoint parameter
    
    Args:
        name: Parameter name
        type: Parameter type ("string", "number", "boolean", "object", "array")
        description: Parameter description for tool documentation
        required: Whether parameter is required (default: True)
        default: Default value for optional parameters
    """
    name: str
    type: str
    description: str
    required: bool = True
    default: Optional[Any] = None


@dataclass
class APIEndpoint:
    """Configuration for a dynamic API endpoint
    
    Args:
        name: Unique endpoint name (becomes tool name)
        url: API endpoint URL (supports templating like /users/{id})
        method: HTTP method to use
        description: Endpoint description for tool documentation
        parameters: List of endpoint parameters
        headers: Optional custom headers to send
        timeout: Request timeout in seconds (default: 30.0)
    """
    name: str
    url: str
    method: HTTPMethod
    description: str
    parameters: List[APIParameter]
    headers: Optional[Dict[str, str]] = None
    timeout: float = 30.0


__all__ = [
    "HTTPMethod",
    "APIParameter", 
    "APIEndpoint",
]
