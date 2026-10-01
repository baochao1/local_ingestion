"""API base components for Local Ingestion"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, Generic, Optional, TypeVar

import requests

logger = logging.getLogger(__name__)

T = TypeVar("T")


class APIError(Exception):
    """Exception raised for API errors"""

    def __init__(
        self,
        message: str,
        status_code: int = 0,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}

    def __repr__(self) -> str:
        return f"APIError(status_code={self.status_code}, message={self.message})"


class APIResponse(Generic[T]):
    """Generic response wrapper for API calls"""

    def __init__(
        self,
        data: T,
        status_code: int,
        message: str = "",
        timestamp: Optional[datetime] = None,
    ):
        self.data = data
        self.status_code = status_code
        self.message = message
        self.timestamp = timestamp or datetime.now(timezone.utc)

    def success(self) -> bool:
        """Check if the response indicates success (2xx status codes)"""
        return 200 <= self.status_code < 300

    def __repr__(self) -> str:
        return f"APIResponse(status_code={self.status_code}, success={self.success()})"


class BaseAPI(ABC):
    """Abstract base class for API clients"""

    _base_url: str = ""
    _timeout: int = 30
    _headers: Dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    _max_retries: int = 3
    _retry_backoff_factor: float = 0.5

    def __init__(
        self,
        base_url: str,
        timeout: int = 30,
        headers: Optional[Dict[str, str]] = None,
        max_retries: int = 3,
        retry_backoff_factor: float = 0.5,
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._headers = {**self._headers, **(headers or {})}
        self._max_retries = max_retries
        self._retry_backoff_factor = retry_backoff_factor

    def _build_url(self, path: str) -> str:
        """Build full URL from path"""
        path = path.lstrip("/")
        return f"{self._base_url}/{path}"

    def _request(
        self,
        method: str,
        path: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """Make HTTP request with retry logic"""
        url = self._build_url(path)
        last_exception = None

        for attempt in range(self._max_retries):
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    json=data,
                    params=params,
                    headers=self._headers,
                    timeout=self._timeout,
                )
                response.raise_for_status()
                return response

            except requests.exceptions.RequestException as e:
                last_exception = e
                if attempt < self._max_retries - 1:
                    sleep_time = self._retry_backoff_factor * (2**attempt)
                    logger.warning(
                        f"Request failed (attempt {attempt + 1}/{self._max_retries}): {e}. "
                        f"Retrying in {sleep_time}s..."
                    )
                    time.sleep(sleep_time)
                else:
                    logger.error(f"Request failed after {self._max_retries} attempts: {e}")

        raise APIError(
            message=f"Request failed after {self._max_retries} attempts: {last_exception}",
            status_code=getattr(last_exception, "response", None) and last_exception.response.status_code or 0,
            details={"url": url, "method": method},
        )

    def get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> APIResponse[Any]:
        """Make GET request"""
        try:
            response = self._request("GET", path, params=params)
            return APIResponse(
                data=response.json() if response.content else None,
                status_code=response.status_code,
                message="Success",
            )
        except APIError:
            raise
        except Exception as e:
            raise APIError(message=str(e), details={"path": path, "method": "GET"})

    def post(
        self,
        path: str,
        data: Dict[str, Any],
    ) -> APIResponse[Any]:
        """Make POST request"""
        try:
            response = self._request("POST", path, data=data)
            return APIResponse(
                data=response.json() if response.content else None,
                status_code=response.status_code,
                message="Created" if response.status_code == 201 else "Success",
            )
        except APIError:
            raise
        except Exception as e:
            raise APIError(message=str(e), details={"path": path, "method": "POST"})

    def put(
        self,
        path: str,
        data: Dict[str, Any],
    ) -> APIResponse[Any]:
        """Make PUT request"""
        try:
            response = self._request("PUT", path, data=data)
            return APIResponse(
                data=response.json() if response.content else None,
                status_code=response.status_code,
                message="Updated",
            )
        except APIError:
            raise
        except Exception as e:
            raise APIError(message=str(e), details={"path": path, "method": "PUT"})

    def delete(self, path: str) -> APIResponse[Any]:
        """Make DELETE request"""
        try:
            response = self._request("DELETE", path)
            return APIResponse(
                data=response.json() if response.content else None,
                status_code=response.status_code,
                message="Deleted",
            )
        except APIError:
            raise
        except Exception as e:
            raise APIError(message=str(e), details={"path": path, "method": "DELETE"})

    @abstractmethod
    def health_check(self) -> bool:
        """Check if the API is healthy"""
        raise NotImplementedError
