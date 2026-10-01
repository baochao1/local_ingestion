"""Unit tests for API base components"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch, call

import pytest
import requests

from local_ingestion.api.base import APIError, APIResponse, BaseAPI


class TestAPIResponse:
    """Tests for APIResponse wrapper"""

    def test_success_response_2xx(self):
        """Test success method returns True for 2xx status codes"""
        response = APIResponse(data={"key": "value"}, status_code=200)
        assert response.success() is True

        response = APIResponse(data=None, status_code=201)
        assert response.success() is True

        response = APIResponse(data=[], status_code=204)
        assert response.success() is True

    def test_failure_response_4xx(self):
        """Test success method returns False for 4xx status codes"""
        response = APIResponse(data=None, status_code=400)
        assert response.success() is False

        response = APIResponse(data=None, status_code=404)
        assert response.success() is False

    def test_failure_response_5xx(self):
        """Test success method returns False for 5xx status codes"""
        response = APIResponse(data=None, status_code=500)
        assert response.success() is False

        response = APIResponse(data=None, status_code=503)
        assert response.success() is False

    def test_response_attributes(self):
        """Test APIResponse has correct attributes"""
        data = {"result": "ok"}
        timestamp = datetime.now(timezone.utc)
        response = APIResponse(
            data=data,
            status_code=200,
            message="Success",
            timestamp=timestamp,
        )
        assert response.data == data
        assert response.status_code == 200
        assert response.message == "Success"
        assert response.timestamp == timestamp

    def test_response_repr(self):
        """Test APIResponse string representation"""
        response = APIResponse(data=None, status_code=200)
        assert "APIResponse" in repr(response)
        assert "200" in repr(response)


class TestAPIError:
    """Tests for APIError exception"""

    def test_error_creation(self):
        """Test APIError can be created with all attributes"""
        error = APIError(
            message="Not Found",
            status_code=404,
            details={"path": "/api/test"},
        )
        assert error.message == "Not Found"
        assert error.status_code == 404
        assert error.details == {"path": "/api/test"}

    def test_error_with_defaults(self):
        """Test APIError uses default values"""
        error = APIError(message="Something went wrong")
        assert error.message == "Something went wrong"
        assert error.status_code == 0
        assert error.details == {}

    def test_error_repr(self):
        """Test APIError string representation"""
        error = APIError(message="Test error", status_code=500)
        assert "APIError" in repr(error)
        assert "500" in repr(error)
        assert "Test error" in repr(error)

    def test_error_is_exception(self):
        """Test APIError is a subclass of Exception"""
        error = APIError(message="Test")
        assert isinstance(error, Exception)


class MockAPI(BaseAPI):
    """Mock implementation of BaseAPI for testing"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def health_check(self) -> bool:
        try:
            response = self._request("GET", "/health")
            return response.status_code == 200
        except Exception:
            return False


class TestBaseAPI:
    """Tests for BaseAPI abstract class"""

    def test_api_initialization(self):
        """Test API client initializes with correct defaults"""
        api = MockAPI(base_url="https://api.example.com")
        assert api._base_url == "https://api.example.com"
        assert api._timeout == 30
        assert api._headers["Content-Type"] == "application/json"

    def test_api_custom_headers(self):
        """Test API client accepts custom headers"""
        api = MockAPI(
            base_url="https://api.example.com",
            headers={"Authorization": "Bearer token123"},
        )
        assert api._headers["Authorization"] == "Bearer token123"
        assert api._headers["Content-Type"] == "application/json"

    def test_api_custom_timeout(self):
        """Test API client accepts custom timeout"""
        api = MockAPI(base_url="https://api.example.com", timeout=60)
        assert api._timeout == 60

    def test_build_url(self):
        """Test URL building"""
        api = MockAPI(base_url="https://api.example.com")
        assert api._build_url("/api/v1/users") == "https://api.example.com/api/v1/users"

    def test_build_url_no_double_slash(self):
        """Test URL building handles paths correctly"""
        api = MockAPI(base_url="https://api.example.com/")
        assert api._build_url("/api/v1/users") == "https://api.example.com/api/v1/users"

    def test_build_url_trailing_slash(self):
        """Test URL building removes trailing slashes from base_url"""
        api = MockAPI(base_url="https://api.example.com///")
        assert api._build_url("/api/v1") == "https://api.example.com/api/v1"


class TestBaseAPIMethods:
    """Tests for BaseAPI HTTP methods with mocked responses"""

    @pytest.fixture
    def mock_api(self):
        """Create a mock API instance"""
        return MockAPI(base_url="https://api.example.com")

    def test_get_success(self, mock_api):
        """Test successful GET request"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"id": 1, "name": "test"}'
        mock_response.json.return_value = {"id": 1, "name": "test"}

        with patch.object(mock_api, "_request", return_value=mock_response):
            response = mock_api.get("/api/v1/users/1")
            assert response.success() is True
            assert response.data == {"id": 1, "name": "test"}

    def test_get_with_params(self, mock_api):
        """Test GET request with query parameters"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'[{"id": 1}, {"id": 2}]'
        mock_response.json.return_value = [{"id": 1}, {"id": 2}]

        with patch.object(mock_api, "_request", return_value=mock_response):
            response = mock_api.get("/api/v1/users", params={"page": 1, "limit": 10})
            assert response.success() is True
            assert len(response.data) == 2

    def test_post_success(self, mock_api):
        """Test successful POST request"""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.content = b'{"id": 123, "name": "new_user"}'
        mock_response.json.return_value = {"id": 123, "name": "new_user"}

        with patch.object(mock_api, "_request", return_value=mock_response):
            response = mock_api.post("/api/v1/users", data={"name": "new_user"})
            assert response.success() is True
            assert response.data["id"] == 123

    def test_put_success(self, mock_api):
        """Test successful PUT request"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"id": 1, "name": "updated"}'
        mock_response.json.return_value = {"id": 1, "name": "updated"}

        with patch.object(mock_api, "_request", return_value=mock_response):
            response = mock_api.put("/api/v1/users/1", data={"name": "updated"})
            assert response.success() is True

    def test_delete_success(self, mock_api):
        """Test successful DELETE request"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"deleted": true}'
        mock_response.json.return_value = {"deleted": True}

        with patch.object(mock_api, "_request", return_value=mock_response):
            response = mock_api.delete("/api/v1/users/1")
            assert response.success() is True

    def test_get_handles_error(self, mock_api):
        """Test GET request raises APIError on failure"""
        with patch.object(
            mock_api,
            "_request",
            side_effect=APIError("Not Found", status_code=404),
        ):
            with pytest.raises(APIError) as exc_info:
                mock_api.get("/api/v1/users/999")
            assert exc_info.value.status_code == 404


class TestRetryLogic:
    """Tests for retry logic with exponential backoff"""

    def test_retry_on_failure(self):
        """Test that requests are retried on failure"""
        mock_api = MockAPI(
            base_url="https://api.example.com",
            max_retries=3,
            retry_backoff_factor=0.01,
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"result": "ok"}'
        mock_response.json.return_value = {"result": "ok"}
        mock_response.raise_for_status = MagicMock()

        call_count = 0

        def failing_then_success(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise requests.exceptions.ConnectionError("Connection failed")
            return mock_response

        with patch("requests.request", side_effect=failing_then_success):
            response = mock_api.get("/api/v1/test")
            assert response.success() is True
            assert call_count == 3

    def test_max_retries_exceeded(self):
        """Test that APIError is raised after max retries"""
        mock_api = MockAPI(
            base_url="https://api.example.com",
            max_retries=3,
            retry_backoff_factor=0.01,
        )

        with patch(
            "requests.request",
            side_effect=requests.exceptions.ConnectionError("Connection failed"),
        ):
            with pytest.raises(APIError) as exc_info:
                mock_api.get("/api/v1/test")
            assert "failed after 3 attempts" in str(exc_info.value)


class TestHealthCheck:
    """Tests for health_check method"""

    def test_health_check_success(self):
        """Test health_check returns True on success"""
        mock_api = MockAPI(base_url="https://api.example.com")

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(mock_api, "_request", return_value=mock_response):
            assert mock_api.health_check() is True

    def test_health_check_failure(self):
        """Test health_check returns False on failure"""
        mock_api = MockAPI(base_url="https://api.example.com")

        with patch.object(
            mock_api,
            "_request",
            side_effect=APIError("Service unavailable", status_code=503),
        ):
            assert mock_api.health_check() is False
