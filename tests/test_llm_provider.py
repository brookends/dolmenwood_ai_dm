"""
Tests for the LLM provider abstraction layer.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ai.llm_provider import (
    LLMProvider,
    LLMMessage,
    LLMResponse,
    ToolCall,
    ClaudeProvider,
    OllamaProvider,
    OpenAICompatibleProvider,
    create_llm_provider,
    ProviderType,
)


class TestLLMMessage:
    """Tests for LLMMessage dataclass."""
    
    def test_basic_message(self):
        msg = LLMMessage(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"
        assert msg.tool_calls is None
    
    def test_message_with_tool_calls(self):
        msg = LLMMessage(
            role="assistant",
            content="Using tool",
            tool_calls=[{"id": "1", "name": "test"}]
        )
        assert msg.tool_calls == [{"id": "1", "name": "test"}]


class TestLLMResponse:
    """Tests for LLMResponse dataclass."""
    
    def test_basic_response(self):
        resp = LLMResponse(content="Hello world")
        assert resp.content == "Hello world"
        assert resp.tool_calls == []
        assert resp.stop_reason is None
    
    def test_response_with_tool_calls(self):
        tool_call = ToolCall(id="1", name="roll_dice", arguments={"notation": "1d20"})
        resp = LLMResponse(content="", tool_calls=[tool_call])
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "roll_dice"


class TestToolCall:
    """Tests for ToolCall dataclass."""
    
    def test_tool_call_creation(self):
        tc = ToolCall(id="call_1", name="roll_dice", arguments={"notation": "2d6"})
        assert tc.id == "call_1"
        assert tc.name == "roll_dice"
        assert tc.arguments == {"notation": "2d6"}


class TestProviderType:
    """Tests for ProviderType enum."""
    
    def test_provider_types(self):
        assert ProviderType.CLAUDE.value == "claude"
        assert ProviderType.OLLAMA.value == "ollama"
        assert ProviderType.OPENAI_COMPATIBLE.value == "openai"


class TestClaudeProvider:
    """Tests for ClaudeProvider."""
    
    def test_init_with_api_key(self):
        provider = ClaudeProvider(api_key="test-key")
        assert provider.api_key == "test-key"
        assert provider.supports_tool_calling is True
        assert "Claude" in provider.provider_name
    
    def test_init_without_api_key_raises(self):
        with patch.dict('os.environ', {}, clear=True):
            with pytest.raises(ValueError, match="API key required"):
                ClaudeProvider(api_key=None)
    
    def test_provider_name_includes_model(self):
        provider = ClaudeProvider(api_key="test", model="claude-test-model")
        assert "claude-test-model" in provider.provider_name


class TestOllamaProvider:
    """Tests for OllamaProvider."""
    
    def test_init_default(self):
        provider = OllamaProvider()
        assert provider.model == "llama3.2"
        assert provider.base_url == "http://localhost:11434"
    
    def test_init_custom_model(self):
        provider = OllamaProvider(model="mistral", base_url="http://custom:11434")
        assert provider.model == "mistral"
        assert provider.base_url == "http://custom:11434"
    
    def test_tool_capability_detection(self):
        # Models that should support tools
        for model in ["llama3.1", "llama3.2", "mistral", "qwen2.5"]:
            provider = OllamaProvider(model=model)
            assert provider.supports_tool_calling is True, f"{model} should support tools"
        
        # Model that shouldn't (unknown)
        provider = OllamaProvider(model="unknown-model")
        assert provider.supports_tool_calling is False
    
    def test_tool_capability_override(self):
        provider = OllamaProvider(model="unknown-model", supports_tools=True)
        assert provider.supports_tool_calling is True
    
    def test_provider_name(self):
        provider = OllamaProvider(model="llama3.2")
        assert "Ollama" in provider.provider_name
        assert "llama3.2" in provider.provider_name


class TestOpenAICompatibleProvider:
    """Tests for OpenAICompatibleProvider."""
    
    def test_init_default(self):
        provider = OpenAICompatibleProvider()
        assert provider.model == "local-model"
        assert provider.base_url == "http://localhost:1234/v1"
        assert provider.supports_tool_calling is False
    
    def test_init_custom(self):
        provider = OpenAICompatibleProvider(
            model="my-model",
            base_url="http://localhost:8080/v1",
            supports_tools=True
        )
        assert provider.model == "my-model"
        assert provider.supports_tool_calling is True
    
    def test_provider_name(self):
        provider = OpenAICompatibleProvider(model="test-model")
        assert "OpenAI-Compatible" in provider.provider_name


class TestToolCallExtraction:
    """Tests for prompt-based tool call extraction."""
    
    def test_extract_json_block(self):
        provider = OllamaProvider(model="unknown", supports_tools=False)
        
        content = '''Here is my response.
```json
{"tool": "roll_dice", "arguments": {"notation": "1d20"}}
```
And some more text.'''
        
        cleaned, calls = provider._extract_json_tool_calls(content)
        
        assert len(calls) == 1
        assert calls[0].name == "roll_dice"
        assert calls[0].arguments == {"notation": "1d20"}
        assert "```json" not in cleaned
    
    def test_extract_multiple_tools(self):
        provider = OllamaProvider(model="unknown", supports_tools=False)
        
        content = '''Let me do that.
```json
{"tool": "roll_dice", "arguments": {"notation": "1d20"}}
```
And then:
```json
{"tool": "lookup_monster", "arguments": {"name": "goblin"}}
```
Done.'''
        
        cleaned, calls = provider._extract_json_tool_calls(content)
        
        assert len(calls) == 2
        assert calls[0].name == "roll_dice"
        assert calls[1].name == "lookup_monster"
    
    def test_no_tool_calls(self):
        provider = OllamaProvider(model="unknown", supports_tools=False)
        
        content = "This is just normal text without any tool calls."
        
        cleaned, calls = provider._extract_json_tool_calls(content)
        
        assert len(calls) == 0
        assert cleaned == content


class TestCreateLLMProvider:
    """Tests for the factory function."""
    
    def test_create_claude(self):
        provider = create_llm_provider("claude", api_key="test-key")
        assert isinstance(provider, ClaudeProvider)
    
    def test_create_ollama(self):
        provider = create_llm_provider("ollama", model="llama3.2")
        assert isinstance(provider, OllamaProvider)
    
    def test_create_openai(self):
        provider = create_llm_provider("openai", base_url="http://localhost:1234/v1")
        assert isinstance(provider, OpenAICompatibleProvider)
    
    def test_create_with_enum(self):
        provider = create_llm_provider(ProviderType.OLLAMA, model="mistral")
        assert isinstance(provider, OllamaProvider)
    
    def test_create_unknown_raises(self):
        with pytest.raises(ValueError):
            create_llm_provider("unknown_provider")
