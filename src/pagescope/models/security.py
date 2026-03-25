"""Pydantic models for security diagnostic output."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CertificateDetail(BaseModel):
    """Full X.509 certificate details -- like openssl x509 -text."""

    # subject
    subject_cn: str = ""
    subject_org: str = ""
    subject_ou: str = ""
    subject_country: str = ""
    subject_state: str = ""
    subject_locality: str = ""
    subject_full: str = ""  # Full DN string

    # issuer
    issuer_cn: str = ""
    issuer_org: str = ""
    issuer_country: str = ""
    issuer_full: str = ""

    # validity
    not_before: str = ""
    not_after: str = ""
    is_expired: bool = False
    days_remaining: int | None = None

    # key info
    public_key_algorithm: str = ""
    public_key_bits: int | None = None
    signature_algorithm: str = ""
    serial_number: str = ""
    version: int | None = None

    # extensions
    san_list: list[str] = Field(default_factory=list)
    key_usage: list[str] = Field(default_factory=list)
    extended_key_usage: list[str] = Field(default_factory=list)
    is_ca: bool | None = None
    ocsp_urls: list[str] = Field(default_factory=list)
    crl_urls: list[str] = Field(default_factory=list)
    ca_issuers: list[str] = Field(default_factory=list)

    # fingerprints
    sha256_fingerprint: str = ""
    sha1_fingerprint: str = ""

    # chain
    chain_length: int = 0
    chain_subjects: list[str] = Field(default_factory=list)


class TLSInfo(BaseModel):
    """TLS connection details."""

    protocol: str = ""  # "TLS 1.3", "TLS 1.2", etc.
    cipher: str = ""
    key_exchange: str = ""
    certificate_subject: str = ""
    certificate_issuer: str = ""
    certificate_valid_from: str = ""
    certificate_valid_to: str = ""
    san_list: list[str] = Field(default_factory=list)
    certificate: CertificateDetail | None = None


class MixedContentIssue(BaseModel):
    """A mixed content resource (HTTP loaded from HTTPS page)."""

    url: str
    resource_type: str = ""
    resolution_status: str = ""  # "blocked", "allowed", "upgraded"


class CSPViolation(BaseModel):
    """A Content-Security-Policy violation."""

    blocked_url: str = ""
    violated_directive: str = ""
    effective_directive: str = ""
    original_policy: str = ""
    source_file: str = ""
    line_number: int | None = None
    column_number: int | None = None


class CookieIssue(BaseModel):
    """A cookie with security problems."""

    name: str
    domain: str = ""
    issue: str = ""  # "missing-secure", "missing-samesite", "third-party", etc.


class SecurityEvent(BaseModel):
    """A real-time security event for streaming."""

    type: str  # "mixed_content", "csp_violation", "certificate", "cookie"
    detail: str = ""


class SecuritySummary(BaseModel):
    """Aggregate security assessment."""

    security_state: str = "unknown"  # "secure", "insecure", "neutral", "unknown"
    mixed_content_count: int = 0
    csp_violation_count: int = 0
    cookie_issue_count: int = 0
    insecure_form_count: int = 0
    has_valid_certificate: bool | None = None
    protocol_version: str = ""


class SecurityReport(BaseModel):
    """Complete security diagnostic report."""

    tls_info: TLSInfo = Field(default_factory=TLSInfo)
    mixed_content: list[MixedContentIssue] = Field(default_factory=list)
    csp_violations: list[CSPViolation] = Field(default_factory=list)
    cookie_issues: list[CookieIssue] = Field(default_factory=list)
    insecure_forms: list[dict] = Field(default_factory=list)
    summary: SecuritySummary = Field(default_factory=SecuritySummary)
