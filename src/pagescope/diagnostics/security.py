"""Security diagnostic module -- TLS, mixed content, CSP, cookies."""

from __future__ import annotations

import asyncio
import hashlib
import ssl
import socket
from datetime import datetime, timezone
from typing import AsyncIterator
from urllib.parse import urlparse

from playwright.async_api import CDPSession, Page

from pagescope.diagnostics.base import BaseDiagnostic
from pagescope.models.common import SessionConfig
from pagescope.models.security import (
    CertificateDetail,
    CookieIssue,
    CSPViolation,
    MixedContentIssue,
    SecurityEvent,
    SecurityReport,
    SecuritySummary,
    TLSInfo,
)


class SecurityChecker(BaseDiagnostic[SecurityReport, SecurityEvent]):
    """Checks page security: TLS, mixed content, CSP violations, cookies.

    CDP domains used:
    - Security (securityStateChanged)
    - Audits (issueAdded for mixed content, CSP, cookies)
    - Network (response security metadata)
    """

    def __init__(self, page: Page, cdp: CDPSession, config: SessionConfig) -> None:
        super().__init__(page, cdp, config)
        self._own_cdp: CDPSession | None = None
        self._security_state: dict = {}
        self._mixed_content: list[MixedContentIssue] = []
        self._csp_violations: list[CSPViolation] = []
        self._cookie_issues: list[CookieIssue] = []
        self._events: asyncio.Queue[SecurityEvent] = asyncio.Queue()

    async def setup(self) -> None:
        if self._enabled:
            return

        # create a dedicated CDP session so we don't conflict with other modules
        self._own_cdp = await self._page.context.new_cdp_session(self._page)

        await self._own_cdp.send("Security.enable")
        try:
            await self._own_cdp.send("Audits.enable")
        except Exception:
            pass  # Audits domain may not be available

        self._own_cdp.on("Security.securityStateChanged", self._on_security_state)
        self._own_cdp.on("Audits.issueAdded", self._on_issue_added)

        self._enabled = True

    def _on_security_state(self, params: dict) -> None:
        self._security_state = params

    def _on_issue_added(self, params: dict) -> None:
        issue = params.get("issue", {})
        code = issue.get("code", "")
        details = issue.get("details", {})

        if "MixedContent" in code or "mixedContent" in details:
            mc = details.get("mixedContentIssueDetails", {})
            self._mixed_content.append(
                MixedContentIssue(
                    url=mc.get("insecureURL", mc.get("url", "")),
                    resource_type=mc.get("resourceType", ""),
                    resolution_status=mc.get("resolutionStatus", ""),
                )
            )
            self._events.put_nowait(
                SecurityEvent(type="mixed_content", detail=mc.get("insecureURL", ""))
            )

        elif "ContentSecurityPolicy" in code or "contentSecurityPolicy" in details:
            csp = details.get("contentSecurityPolicyIssueDetails", {})
            self._csp_violations.append(
                CSPViolation(
                    blocked_url=csp.get("blockedURL", ""),
                    violated_directive=csp.get("violatedDirective", ""),
                    effective_directive=csp.get("effectiveDirective", ""),
                    source_file=csp.get("sourceCodeLocation", {}).get("url", ""),
                    line_number=csp.get("sourceCodeLocation", {}).get("lineNumber"),
                    column_number=csp.get("sourceCodeLocation", {}).get("columnNumber"),
                )
            )
            self._events.put_nowait(
                SecurityEvent(type="csp_violation", detail=csp.get("violatedDirective", ""))
            )

        elif "Cookie" in code or "cookie" in details:
            cookie = details.get("cookieIssueDetails", {})
            cookie_info = cookie.get("cookie", {})
            for raw_reason in cookie.get("cookieExclusionReasons", []) + cookie.get("cookieWarningReasons", []):
                self._cookie_issues.append(
                    CookieIssue(
                        name=cookie_info.get("name", ""),
                        domain=cookie_info.get("domain", ""),
                        issue=raw_reason,
                    )
                )
            self._events.put_nowait(
                SecurityEvent(type="cookie", detail=cookie_info.get("name", ""))
            )

    async def _get_tls_info(self) -> TLSInfo:
        """Extract TLS info from the security state."""
        cdp = self._own_cdp or self._cdp
        info = TLSInfo()

        # method 1: getVisibleSecurityState (most reliable)
        try:
            result = await cdp.send("Security.getVisibleSecurityState")
            vs = result.get("visibleSecurityState", {})
            cert_sec = vs.get("certificateSecurityState", {})
            if cert_sec:
                info.protocol = cert_sec.get("protocol", "")
                info.cipher = cert_sec.get("cipher", "")
                info.key_exchange = cert_sec.get("keyExchange", "")
                info.certificate_subject = cert_sec.get("subjectName", "")
                info.certificate_issuer = cert_sec.get("issuer", "")
                info.certificate_valid_from = str(cert_sec.get("validFrom", ""))
                info.certificate_valid_to = str(cert_sec.get("validTo", ""))
                info.san_list = cert_sec.get("sanList", [])
                return info

            # check securityState at top level
            sec_state = vs.get("securityState", "")
            if sec_state and sec_state != "unknown":
                self._security_state["securityState"] = sec_state
        except Exception:
            pass

        # method 2: Extract from securityStateChanged event data
        state = self._security_state
        explanations = state.get("explanations", [])
        for exp in explanations:
            desc = exp.get("description", "")
            if "TLS" in desc or "certificate" in desc.lower():
                info.protocol = desc
                break

        # method 3: Check via JavaScript as last resort
        if not info.protocol:
            try:
                protocol = await self._page.evaluate(
                    "() => location.protocol"
                )
                if protocol == "https:":
                    info.protocol = "HTTPS"
                    # try to get more info from Performance API
                    perf_info = await self._page.evaluate("""
                        () => {
                            const entries = performance.getEntriesByType('navigation');
                            if (entries.length > 0) {
                                const nav = entries[0];
                                return {
                                    protocol: nav.nextHopProtocol || '',
                                };
                            }
                            return {};
                        }
                    """)
                    if perf_info and perf_info.get("protocol"):
                        info.protocol = perf_info["protocol"]
            except Exception:
                pass

        return info

    async def _fetch_certificate_direct(self, url: str) -> CertificateDetail | None:
        """Connect directly via SSL and extract full X.509 certificate details."""

        def _fetch(hostname: str, port: int) -> CertificateDetail | None:
            ctx = ssl.create_default_context()
            try:
                with socket.create_connection((hostname, port), timeout=10) as sock:
                    with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                        # get the binary DER cert and the parsed dict
                        der_cert = ssock.getpeercert(binary_form=True)
                        cert_dict = ssock.getpeercert()
                        cipher_info = ssock.cipher()
                        ssl_version = ssock.version()

                        if not cert_dict:
                            return None

                        detail = CertificateDetail()

                        # subject
                        subject = dict(x[0] for x in cert_dict.get("subject", ()))
                        detail.subject_cn = subject.get("commonName", "")
                        detail.subject_org = subject.get("organizationName", "")
                        detail.subject_ou = subject.get("organizationalUnitName", "")
                        detail.subject_country = subject.get("countryName", "")
                        detail.subject_state = subject.get("stateOrProvinceName", "")
                        detail.subject_locality = subject.get("localityName", "")
                        detail.subject_full = ", ".join(
                            f"{k}={v}" for k, v in subject.items()
                        )

                        # issuer
                        issuer = dict(x[0] for x in cert_dict.get("issuer", ()))
                        detail.issuer_cn = issuer.get("commonName", "")
                        detail.issuer_org = issuer.get("organizationName", "")
                        detail.issuer_country = issuer.get("countryName", "")
                        detail.issuer_full = ", ".join(
                            f"{k}={v}" for k, v in issuer.items()
                        )

                        # validity
                        not_before = cert_dict.get("notBefore", "")
                        not_after = cert_dict.get("notAfter", "")
                        detail.not_before = not_before
                        detail.not_after = not_after

                        try:
                            expiry = datetime.strptime(
                                not_after, "%b %d %H:%M:%S %Y %Z"
                            ).replace(tzinfo=timezone.utc)
                            now = datetime.now(timezone.utc)
                            detail.is_expired = expiry < now
                            detail.days_remaining = (expiry - now).days
                        except (ValueError, TypeError):
                            pass

                        # serial number
                        detail.serial_number = cert_dict.get("serialNumber", "")

                        # version
                        detail.version = cert_dict.get("version")

                        # sANs
                        san_entries = cert_dict.get("subjectAltName", ())
                        detail.san_list = [v for _, v in san_entries]

                        # oCSP / CRL / CA Issuers
                        for key in ("OCSP", "caIssuers", "crlDistributionPoints"):
                            vals = cert_dict.get(key, ())
                            if isinstance(vals, (list, tuple)):
                                if key == "OCSP":
                                    detail.ocsp_urls = list(vals)
                                elif key == "caIssuers":
                                    detail.ca_issuers = list(vals)
                                elif key == "crlDistributionPoints":
                                    detail.crl_urls = list(vals)

                        # cipher / protocol from the connection
                        if cipher_info:
                            detail.signature_algorithm = cipher_info[0] if cipher_info[0] else ""
                            detail.public_key_bits = cipher_info[2] if len(cipher_info) > 2 else None

                        # fingerprints from DER cert
                        if der_cert:
                            detail.sha256_fingerprint = hashlib.sha256(der_cert).hexdigest()
                            detail.sha1_fingerprint = hashlib.sha1(der_cert).hexdigest()

                        return detail
            except Exception:
                return None

        parsed = urlparse(url)
        if parsed.scheme != "https":
            return None
        hostname = parsed.hostname or ""
        port = parsed.port or 443

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _fetch, hostname, port)

    async def _check_insecure_forms(self) -> list[dict]:
        """Check for forms that submit to HTTP endpoints."""
        try:
            forms = await self._page.evaluate("""
                () => {
                    const forms = document.querySelectorAll('form[action]');
                    const insecure = [];
                    for (const form of forms) {
                        const action = form.getAttribute('action') || '';
                        if (action.startsWith('http://')) {
                            insecure.push({
                                action: action,
                                method: form.method || 'GET',
                                has_password: !!form.querySelector('input[type="password"]'),
                            });
                        }
                    }
                    return insecure;
                }
            """)
            return forms or []
        except Exception:
            return []

    async def analyze(self) -> SecurityReport:
        if not self._enabled:
            await self.setup()

        # wait for audits events to arrive
        await asyncio.sleep(1.0)

        # get URL for direct SSL connection
        try:
            current_url = await self._page.evaluate("() => location.href")
        except Exception:
            current_url = ""

        tls_info = await self._get_tls_info()

        # direct SSL cert fetch -- gives us full x509 details
        cert_detail = await self._fetch_certificate_direct(current_url)
        if cert_detail:
            tls_info.certificate = cert_detail
            # backfill TLSInfo fields from cert if CDP didn't provide them
            if not tls_info.certificate_subject:
                tls_info.certificate_subject = cert_detail.subject_cn
            if not tls_info.certificate_issuer:
                tls_info.certificate_issuer = cert_detail.issuer_cn or cert_detail.issuer_org
            if not tls_info.certificate_valid_from:
                tls_info.certificate_valid_from = cert_detail.not_before
            if not tls_info.certificate_valid_to:
                tls_info.certificate_valid_to = cert_detail.not_after
            if not tls_info.san_list:
                tls_info.san_list = cert_detail.san_list
            if not tls_info.protocol or tls_info.protocol in ("HTTPS", "h2", "h3"):
                tls_info.protocol = "TLS (see Certificate tab for details)"

        insecure_forms = await self._check_insecure_forms()

        # determine overall security state
        state_str = self._security_state.get("securityState", "unknown")

        # if CDP didn't give us a state, infer from what we know
        has_cert = bool(tls_info.protocol)
        if state_str == "unknown" and has_cert:
            state_str = "secure"
        elif state_str == "unknown":
            try:
                protocol = await self._page.evaluate("() => location.protocol")
                if protocol == "https:":
                    state_str = "secure"
                elif protocol == "http:":
                    state_str = "insecure"
            except Exception:
                pass

        # downgrade if issues found
        if state_str == "secure" and (self._mixed_content or insecure_forms):
            state_str = "neutral"

        summary = SecuritySummary(
            security_state=state_str,
            mixed_content_count=len(self._mixed_content),
            csp_violation_count=len(self._csp_violations),
            cookie_issue_count=len(self._cookie_issues),
            insecure_form_count=len(insecure_forms),
            has_valid_certificate=has_cert if has_cert else None,
            protocol_version=tls_info.protocol,
        )

        return SecurityReport(
            tls_info=tls_info,
            mixed_content=self._mixed_content,
            csp_violations=self._csp_violations,
            cookie_issues=self._cookie_issues,
            insecure_forms=insecure_forms,
            summary=summary,
        )

    async def stream(self) -> AsyncIterator[SecurityEvent]:
        if not self._enabled:
            await self.setup()
        while True:
            event = await self._events.get()
            yield event

    async def teardown(self) -> None:
        cdp = self._own_cdp or self._cdp
        try:
            await cdp.send("Security.disable")
        except Exception:
            pass
        try:
            await cdp.send("Audits.disable")
        except Exception:
            pass
        if self._own_cdp:
            try:
                await self._own_cdp.detach()
            except Exception:
                pass
        await super().teardown()
