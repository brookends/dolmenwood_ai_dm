"""
LLM Provider Abstraction for Dolmenwood AI DM.

Supports multiple LLM backends:
- Anthropic Claude API (default, best quality)
- Ollama (local, free)
- OpenAI-compatible APIs (LM Studio, text-generation-webui, vLLM, etc.)

Usage:
    # Claude (default)
    provider = create_llm_provider("claude", api_key="sk-ant-...")

    # Ollama (local)
    provider = create_llm_provider("ollama", model="llama3.2")

    # OpenAI-compatible (local server)
    provider = create_llm_provider("openai", base_url="http://localhost:1234/v1")
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Union
from enum import Enum

logger = logging.getLogger(__name__)


class ProviderType(str, Enum):
    """Supported LLM provider types."""
    CLAUDE = "claude"
    OLLAMA = "ollama"
    OPENAI_COMPATIBLE = "openai"


@dataclass
class LLMMessage:
    """A message in a conversation."""
    role: str  # "user", "assistant", "system"
    content: str
    tool_calls: Optional[list[dict]] = None
    tool_results: Optional[list[dict]] = None


@dataclass
class ToolCall:
    """A tool/function call from the LLM."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """Response from an LLM provider."""
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: Optional[str] = None
    usage: Optional[dict[str, int]] = None  # {"input_tokens": N, "output_tokens": M}
    raw_response: Optional[Any] = None


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""
    
    @property
    @abstractmethod
    def supports_tool_calling(self) -> bool:
        """Whether this provider supports native tool/function calling."""
        pass
    
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider name."""
        pass
    
    @abstractmethod
    def generate(
        self,
        messages: list[LLMMessage],
        system_prompt: Optional[str] = None,
        tools: Optional[list[dict]] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """
        Generate a response from the LLM.
        
        Args:
            messages: Conversation history.
            system_prompt: System prompt/instructions.
            tools: Tool definitions (if supported).
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.
            
        Returns:
            LLMResponse with content and optional tool calls.
        """
        pass
    
    def _extract_json_tool_calls(self, content: str) -> tuple[str, list[ToolCall]]:
        """
        Extract tool calls from text for models without native tool support.
        
        Looks for JSON blocks in the format:
        ```json
        {"tool": "tool_name", "arguments": {...}}
        ```
        
        Returns:
            Tuple of (cleaned content, list of tool calls)
        """
        tool_calls = []
        cleaned_content = content
        found_jsons = set()  # Track found JSON to avoid duplicates
        
        # Pattern for ```json blocks (most specific, check first)
        json_block_pattern = r'```json\s*(\{[^`]*?"tool"[^`]*?\})\s*```'
        
        for match in re.finditer(json_block_pattern, content, re.DOTALL):
            json_str = match.group(1)
            if json_str in found_jsons:
                continue
            found_jsons.add(json_str)
            
            try:
                data = json.loads(json_str)
                if "tool" in data:
                    tool_call = ToolCall(
                        id=f"call_{len(tool_calls)}",
                        name=data["tool"],
                        arguments=data.get("arguments", {})
                    )
                    tool_calls.append(tool_call)
                    # Remove the entire block from content
                    cleaned_content = cleaned_content.replace(match.group(0), "").strip()
            except json.JSONDecodeError:
                continue
        
        # Clean up any empty code blocks
        cleaned_content = re.sub(r'```json\s*```', '', cleaned_content).strip()
        
        return cleaned_content, tool_calls


class ClaudeProvider(LLMProvider):
    """Anthropic Claude API provider with rate limiting support."""

    # Rate limiting settings
    MIN_REQUEST_INTERVAL = 0.5  # Minimum seconds between requests
    MAX_RETRIES = 5  # Maximum retry attempts for rate limit errors
    INITIAL_BACKOFF = 2.0  # Initial backoff in seconds
    MAX_BACKOFF = 60.0  # Maximum backoff in seconds
    BACKOFF_MULTIPLIER = 2.0  # Backoff multiplier for exponential backoff

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-20250514",
        min_request_interval: float = 0.5,
    ):
        """
        Initialize Claude provider.

        Args:
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var).
            model: Model to use.
            min_request_interval: Minimum seconds between API requests (rate limiting).
        """
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Anthropic API key required. "
                "Set ANTHROPIC_API_KEY environment variable or pass api_key parameter."
            )
        self.model = model
        self._client = None
        self._last_request_time = 0.0
        self._min_request_interval = min_request_interval

    def _throttle_request(self) -> None:
        """Ensure minimum interval between requests to avoid rate limiting."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            sleep_time = self._min_request_interval - elapsed
            logger.debug(f"Rate limiting: sleeping {sleep_time:.2f}s")
            time.sleep(sleep_time)
        self._last_request_time = time.time()

    @property
    def client(self):
        """Lazy-load Anthropic client with custom retry settings."""
        if self._client is None:
            try:
                import anthropic
                # Create client with custom retry settings for rate limits
                self._client = anthropic.Anthropic(
                    api_key=self.api_key,
                    max_retries=self.MAX_RETRIES,
                )
            except ImportError:
                raise ImportError(
                    "anthropic package required. Install with: pip install anthropic"
                )
        return self._client
    
    @property
    def supports_tool_calling(self) -> bool:
        return True
    
    @property
    def provider_name(self) -> str:
        return f"Claude ({self.model})"
    
    def generate(
        self,
        messages: list[LLMMessage],
        system_prompt: Optional[str] = None,
        tools: Optional[list[dict]] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Generate response using Claude API with rate limiting."""

        # Convert messages to Anthropic format
        anthropic_messages = []
        for msg in messages:
            if msg.role == "system":
                continue  # System handled separately

            anthropic_msg = {"role": msg.role, "content": msg.content}
            anthropic_messages.append(anthropic_msg)

        # Build request
        request_kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": anthropic_messages,
        }

        if system_prompt:
            request_kwargs["system"] = system_prompt

        if temperature != 0.7:
            request_kwargs["temperature"] = temperature

        if tools:
            request_kwargs["tools"] = tools

        # Throttle request to avoid rate limiting
        self._throttle_request()

        # Make request with retry handling
        backoff = self.INITIAL_BACKOFF
        last_error = None

        for attempt in range(self.MAX_RETRIES + 1):
            try:
                response = self.client.messages.create(**request_kwargs)
                break
            except Exception as e:
                error_str = str(e).lower()
                # Check if it's a rate limit error
                if "429" in str(e) or "rate" in error_str or "too many" in error_str:
                    last_error = e
                    if attempt < self.MAX_RETRIES:
                        logger.warning(
                            f"Rate limited (attempt {attempt + 1}/{self.MAX_RETRIES + 1}), "
                            f"retrying in {backoff:.1f}s..."
                        )
                        time.sleep(backoff)
                        backoff = min(backoff * self.BACKOFF_MULTIPLIER, self.MAX_BACKOFF)
                        continue
                    else:
                        logger.error(f"Rate limit exceeded after {self.MAX_RETRIES + 1} attempts")
                        raise
                else:
                    # Non-rate-limit error, re-raise immediately
                    raise
        else:
            # All retries exhausted
            raise last_error if last_error else RuntimeError("Request failed after all retries")

        # Parse response
        content = ""
        tool_calls = []

        for block in response.content:
            if hasattr(block, "text"):
                content += block.text
            elif hasattr(block, "type") and block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input
                ))

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            stop_reason=response.stop_reason,
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
            raw_response=response
        )


class OllamaProvider(LLMProvider):
    """
    Ollama local LLM provider.
    
    Supports models like llama3.2, mistral, mixtral, etc.
    Some models support tool calling natively.
    """
    
    # Models known to support tool calling in Ollama
    TOOL_CAPABLE_MODELS = {
        "llama3.1", "llama3.2", "llama3.3",
        "mistral", "mixtral",
        "qwen2.5", "qwen2",
        "command-r",
    }
    
    def __init__(
        self,
        model: str = "llama3.2",
        base_url: str = "http://localhost:11434",
        supports_tools: Optional[bool] = None,
    ):
        """
        Initialize Ollama provider.
        
        Args:
            model: Ollama model name.
            base_url: Ollama server URL.
            supports_tools: Override tool support detection.
        """
        self.model = model
        self.base_url = base_url.rstrip("/")
        
        # Detect tool support
        if supports_tools is not None:
            self._supports_tools = supports_tools
        else:
            # Check if model name starts with any known tool-capable model
            self._supports_tools = any(
                model.startswith(m) for m in self.TOOL_CAPABLE_MODELS
            )
        
        self._client = None
    
    @property
    def client(self):
        """Lazy-load Ollama client."""
        if self._client is None:
            try:
                import ollama
                self._client = ollama.Client(host=self.base_url)
            except ImportError:
                raise ImportError(
                    "ollama package required. Install with: pip install ollama"
                )
        return self._client
    
    @property
    def supports_tool_calling(self) -> bool:
        return self._supports_tools
    
    @property
    def provider_name(self) -> str:
        return f"Ollama ({self.model})"
    
    def _format_tools_as_prompt(self, tools: list[dict]) -> str:
        """Format tools as a prompt for models without native support."""
        tool_descriptions = []
        for tool in tools:
            name = tool.get("name", "unknown")
            desc = tool.get("description", "No description")
            params = tool.get("input_schema", {}).get("properties", {})
            
            param_strs = []
            for param_name, param_info in params.items():
                param_type = param_info.get("type", "any")
                param_desc = param_info.get("description", "")
                param_strs.append(f"  - {param_name} ({param_type}): {param_desc}")
            
            tool_desc = f"**{name}**: {desc}"
            if param_strs:
                tool_desc += "\n  Parameters:\n" + "\n".join(param_strs)
            tool_descriptions.append(tool_desc)
        
        return """
## Available Tools

You can use tools by responding with JSON in this exact format:
```json
{"tool": "tool_name", "arguments": {"param1": "value1"}}
```

Available tools:
""" + "\n\n".join(tool_descriptions)
    
    def generate(
        self,
        messages: list[LLMMessage],
        system_prompt: Optional[str] = None,
        tools: Optional[list[dict]] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Generate response using Ollama."""
        
        # Build messages
        ollama_messages = []
        
        # Add system prompt
        effective_system = system_prompt or ""
        
        # If tools provided but no native support, add to system prompt
        if tools and not self._supports_tools:
            effective_system += self._format_tools_as_prompt(tools)
        
        if effective_system:
            ollama_messages.append({
                "role": "system",
                "content": effective_system
            })
        
        # Add conversation messages
        for msg in messages:
            if msg.role != "system":
                ollama_messages.append({
                    "role": msg.role,
                    "content": msg.content
                })
        
        # Build request options
        options = {
            "temperature": temperature,
            "num_predict": max_tokens,
        }
        
        try:
            if tools and self._supports_tools:
                # Use native tool calling
                # Convert tools to Ollama format
                ollama_tools = []
                for tool in tools:
                    ollama_tool = {
                        "type": "function",
                        "function": {
                            "name": tool.get("name"),
                            "description": tool.get("description", ""),
                            "parameters": tool.get("input_schema", {})
                        }
                    }
                    ollama_tools.append(ollama_tool)
                
                response = self.client.chat(
                    model=self.model,
                    messages=ollama_messages,
                    tools=ollama_tools,
                    options=options,
                )
            else:
                # No tools or no native support
                response = self.client.chat(
                    model=self.model,
                    messages=ollama_messages,
                    options=options,
                )
        except Exception as e:
            logger.error(f"Ollama request failed: {e}")
            raise
        
        # Parse response
        content = response.get("message", {}).get("content", "")
        tool_calls = []
        
        # Check for native tool calls
        if "message" in response and "tool_calls" in response["message"]:
            for tc in response["message"]["tool_calls"]:
                func = tc.get("function", {})
                tool_calls.append(ToolCall(
                    id=tc.get("id", f"call_{len(tool_calls)}"),
                    name=func.get("name", ""),
                    arguments=func.get("arguments", {})
                ))
        elif tools and not self._supports_tools:
            # Try to extract tool calls from text
            content, tool_calls = self._extract_json_tool_calls(content)
        
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            stop_reason="stop",
            usage=response.get("usage"),
            raw_response=response
        )


class OpenAICompatibleProvider(LLMProvider):
    """
    OpenAI-compatible API provider.
    
    Works with:
    - LM Studio
    - text-generation-webui (with openai extension)
    - vLLM
    - LocalAI
    - Any server implementing OpenAI's API format
    """
    
    def __init__(
        self,
        model: str = "local-model",
        base_url: str = "http://localhost:1234/v1",
        api_key: str = "not-needed",
        supports_tools: bool = False,
    ):
        """
        Initialize OpenAI-compatible provider.
        
        Args:
            model: Model name (may be ignored by some servers).
            base_url: Server URL (should end with /v1).
            api_key: API key (often not needed for local servers).
            supports_tools: Whether the server supports function calling.
        """
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._supports_tools = supports_tools
        self._client = None
    
    @property
    def client(self):
        """Lazy-load OpenAI client."""
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    base_url=self.base_url,
                    api_key=self.api_key,
                )
            except ImportError:
                raise ImportError(
                    "openai package required. Install with: pip install openai"
                )
        return self._client
    
    @property
    def supports_tool_calling(self) -> bool:
        return self._supports_tools
    
    @property
    def provider_name(self) -> str:
        return f"OpenAI-Compatible ({self.model})"
    
    def _format_tools_as_prompt(self, tools: list[dict]) -> str:
        """Format tools as a prompt for models without native support."""
        tool_descriptions = []
        for tool in tools:
            name = tool.get("name", "unknown")
            desc = tool.get("description", "No description")
            params = tool.get("input_schema", {}).get("properties", {})
            
            param_strs = []
            for param_name, param_info in params.items():
                param_type = param_info.get("type", "any")
                param_desc = param_info.get("description", "")
                param_strs.append(f"  - {param_name} ({param_type}): {param_desc}")
            
            tool_desc = f"**{name}**: {desc}"
            if param_strs:
                tool_desc += "\n  Parameters:\n" + "\n".join(param_strs)
            tool_descriptions.append(tool_desc)
        
        return """
## Available Tools

You can use tools by responding with JSON in this exact format:
```json
{"tool": "tool_name", "arguments": {"param1": "value1"}}
```

Available tools:
""" + "\n\n".join(tool_descriptions)
    
    def generate(
        self,
        messages: list[LLMMessage],
        system_prompt: Optional[str] = None,
        tools: Optional[list[dict]] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Generate response using OpenAI-compatible API."""
        
        # Build messages
        openai_messages = []
        
        effective_system = system_prompt or ""
        
        # If tools but no native support, add to system prompt
        if tools and not self._supports_tools:
            effective_system += self._format_tools_as_prompt(tools)
        
        if effective_system:
            openai_messages.append({
                "role": "system",
                "content": effective_system
            })
        
        for msg in messages:
            if msg.role != "system":
                openai_messages.append({
                    "role": msg.role,
                    "content": msg.content
                })
        
        # Build request
        request_kwargs = {
            "model": self.model,
            "messages": openai_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        
        if tools and self._supports_tools:
            # Convert to OpenAI tool format
            openai_tools = []
            for tool in tools:
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.get("name"),
                        "description": tool.get("description", ""),
                        "parameters": tool.get("input_schema", {})
                    }
                })
            request_kwargs["tools"] = openai_tools
        
        try:
            response = self.client.chat.completions.create(**request_kwargs)
        except Exception as e:
            logger.error(f"OpenAI-compatible request failed: {e}")
            raise
        
        # Parse response
        message = response.choices[0].message
        content = message.content or ""
        tool_calls = []
        
        # Check for native tool calls
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                args = tc.function.arguments
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args
                ))
        elif tools and not self._supports_tools:
            # Try to extract tool calls from text
            content, tool_calls = self._extract_json_tool_calls(content)
        
        usage = None
        if hasattr(response, "usage") and response.usage:
            usage = {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
            }
        
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            stop_reason=response.choices[0].finish_reason,
            usage=usage,
            raw_response=response
        )


def create_llm_provider(
    provider_type: Union[str, ProviderType] = "claude",
    **kwargs
) -> LLMProvider:
    """
    Factory function to create an LLM provider.
    
    Args:
        provider_type: "claude", "ollama", or "openai"
        **kwargs: Provider-specific arguments
        
    Returns:
        Configured LLMProvider instance.
        
    Examples:
        # Claude (default)
        provider = create_llm_provider("claude", api_key="sk-ant-...")
        
        # Ollama
        provider = create_llm_provider("ollama", model="llama3.2")
        
        # LM Studio or other OpenAI-compatible
        provider = create_llm_provider(
            "openai",
            base_url="http://localhost:1234/v1",
            model="local-model"
        )
    """
    if isinstance(provider_type, str):
        provider_type = ProviderType(provider_type.lower())
    
    if provider_type == ProviderType.CLAUDE:
        return ClaudeProvider(**kwargs)
    elif provider_type == ProviderType.OLLAMA:
        return OllamaProvider(**kwargs)
    elif provider_type == ProviderType.OPENAI_COMPATIBLE:
        return OpenAICompatibleProvider(**kwargs)
    else:
        raise ValueError(f"Unknown provider type: {provider_type}")


# Convenience aliases
def create_claude_provider(
    api_key: Optional[str] = None,
    model: str = "claude-sonnet-4-20250514"
) -> ClaudeProvider:
    """Create a Claude provider."""
    return ClaudeProvider(api_key=api_key, model=model)


def create_ollama_provider(
    model: str = "llama3.2",
    base_url: str = "http://localhost:11434"
) -> OllamaProvider:
    """Create an Ollama provider."""
    return OllamaProvider(model=model, base_url=base_url)


def create_local_provider(
    model: str = "local-model",
    base_url: str = "http://localhost:1234/v1"
) -> OpenAICompatibleProvider:
    """Create an OpenAI-compatible provider for local LLMs."""
    return OpenAICompatibleProvider(model=model, base_url=base_url)
