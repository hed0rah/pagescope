"""Pydantic models for cookie diagnostic output."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Cookie(BaseModel):
    """A single browser cookie with security analysis."""

    name: str
    value: str = ""
    domain: str = ""
    path: str = "/"
    expires: float = -1  # -1 = session cookie
    size: int = 0
    http_only: bool = False
    secure: bool = False
    same_site: str = ""  # "Strict", "Lax", "None", or ""
    priority: str = "Medium"
    source_scheme: str = ""
    session: bool = True  # No expiry set

    # security analysis flags
    missing_secure: bool = False
    missing_http_only: bool = False
    missing_same_site: bool = False
    is_third_party: bool = False
    value_too_large: bool = False


class CookieJarReport(BaseModel):
    """Complete cookie jar analysis."""

    cookies: list[Cookie] = Field(default_factory=list)
    total_count: int = 0
    secure_count: int = 0
    httponly_count: int = 0
    samesite_count: int = 0
    session_count: int = 0
    third_party_count: int = 0
    issues_count: int = 0
