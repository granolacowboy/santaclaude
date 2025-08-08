"""
Contract tests for AI Service
These tests ensure the AI service maintains its API contract during Phase 2 extraction.
"""

import pytest
import httpx
from fastapi.testclient import TestClient
from app.main import app
from app import schemas

client = TestClient(app)


class TestAIServiceContracts:
    """Contract tests to ensure API compatibility"""
    
    def test_health_endpoint_contract(self):
        """Test health endpoint returns expected format"""
        response = client.get("/health")
        assert response.status_code == 200
        
        data = response.json()
        assert "status" in data
        assert "service" in data
        assert data["status"] == "healthy"
        assert data["service"] == "ai-service"
    
    def test_providers_endpoint_contract(self):
        """Test providers endpoint returns expected format"""
        response = client.get("/api/v1/providers")
        assert response.status_code == 200
        
        data = response.json()
        assert isinstance(data, list)
        
        # If providers exist, check schema
        if data:
            provider = data[0]
            assert "id" in provider
            assert "name" in provider
            assert "display_name" in provider
            assert "is_active" in provider
    
    def test_models_endpoint_contract(self):
        """Test models endpoint returns expected format"""
        response = client.get("/api/v1/models")
        assert response.status_code == 200
        
        data = response.json()
        assert isinstance(data, list)
        
        # If models exist, check schema
        if data:
            model = data[0]
            assert "id" in model
            assert "name" in model
            assert "display_name" in model
            assert "provider_id" in model
            assert "is_active" in model
    
    def test_chat_request_schema(self):
        """Test chat request schema validation"""
        # Valid request
        valid_request = {
            "message": "Hello",
            "project_id": 1,
            "user_id": 1,
            "stream": False
        }
        
        # This would normally go through the API, but we test schema validation
        chat_request = schemas.ChatRequest(**valid_request)
        assert chat_request.message == "Hello"
        assert chat_request.project_id == 1
        assert chat_request.user_id == 1
        assert chat_request.stream == False
        
    def test_streaming_chunk_schema(self):
        """Test streaming response schema"""
        chunk_data = {
            "session_id": "test-session",
            "chunk": "Hello",
            "finished": False
        }
        
        chunk = schemas.StreamingChatChunk(**chunk_data)
        assert chunk.session_id == "test-session"
        assert chunk.chunk == "Hello"
        assert chunk.finished == False


class TestCrossServiceIntegration:
    """Integration tests that would run between services"""
    
    @pytest.mark.integration
    async def test_ai_service_projectflow_integration(self):
        """Test that projectflow-ai can successfully call ai-service"""
        # This would be run in a full integration test environment
        # where both services are running
        
        async with httpx.AsyncClient() as http_client:
            # Test health check
            health_response = await http_client.get("http://ai-service:8001/health")
            assert health_response.status_code == 200
            
            # Test providers endpoint
            providers_response = await http_client.get("http://ai-service:8001/api/v1/providers")
            assert providers_response.status_code == 200


@pytest.mark.contract
class TestBackwardsCompatibility:
    """Tests to ensure backwards compatibility during transition"""
    
    def test_session_create_response_format(self):
        """Ensure session creation response maintains expected format"""
        session_data = {
            "id": 1,
            "session_id": "test-session-id",
            "user_id": 1,
            "project_id": 1,
            "card_id": None,
            "provider": "openai",
            "model": "gpt-4",
            "status": "active",
            "context": {},
            "created_at": "2023-01-01T00:00:00Z",
            "updated_at": None,
            "completed_at": None,
            "messages": []
        }
        
        session = schemas.AISession(**session_data)
        
        # Ensure all expected fields exist
        assert session.id == 1
        assert session.session_id == "test-session-id"
        assert session.user_id == 1
        assert session.project_id == 1
        assert session.provider == "openai"
        assert session.model == "gpt-4"
        assert session.status == "active"
        assert isinstance(session.messages, list)
    
    def test_message_format_compatibility(self):
        """Ensure message format remains compatible"""
        message_data = {
            "id": 1,
            "session_id": 1,
            "role": "user",
            "content": "Hello",
            "tool_calls": None,
            "tool_results": None,
            "tokens_used": None,
            "cost": None,
            "created_at": "2023-01-01T00:00:00Z"
        }
        
        message = schemas.AIMessage(**message_data)
        
        assert message.role == "user"
        assert message.content == "Hello"
        assert message.tool_calls is None
        assert message.tool_results is None