"""Cookie jar diagnostic -- full cookie enumeration with security analysis."""

from __future__ import annotations

from urllib.parse import urlparse

from pagescope.models.cookies import Cookie, CookieJarReport


async def get_cookie_jar(cdp, page_url: str) -> CookieJarReport:
    """Fetch all cookies via CDP and analyze security flags."""
    try:
        result = await cdp.send("Network.getAllCookies")
    except Exception:
        return CookieJarReport()

    raw_cookies = result.get("cookies", [])
    if not raw_cookies:
        return CookieJarReport()

    page_domain = urlparse(page_url).hostname or ""
    cookies: list[Cookie] = []

    for raw in raw_cookies:
        name = raw.get("name", "")
        domain = raw.get("domain", "")
        secure = raw.get("secure", False)
        http_only = raw.get("httpOnly", False)
        same_site = raw.get("sameSite", "")
        expires = raw.get("expires", -1)
        session = expires == -1 or expires == 0
        size = raw.get("size", 0)
        value = raw.get("value", "")

        # determine if third-party
        cookie_domain = domain.lstrip(".")
        is_third_party = not (
            page_domain == cookie_domain
            or page_domain.endswith("." + cookie_domain)
        )

        # security analysis
        missing_secure = not secure
        missing_http_only = not http_only
        missing_same_site = same_site not in ("Strict", "Lax")
        value_too_large = size > 4096

        cookies.append(Cookie(
            name=name,
            value=value,
            domain=domain,
            path=raw.get("path", "/"),
            expires=expires,
            size=size,
            http_only=http_only,
            secure=secure,
            same_site=same_site,
            priority=raw.get("priority", "Medium"),
            source_scheme=raw.get("sourceScheme", ""),
            session=session,
            missing_secure=missing_secure,
            missing_http_only=missing_http_only,
            missing_same_site=missing_same_site,
            is_third_party=is_third_party,
            value_too_large=value_too_large,
        ))

    # aggregate stats
    secure_count = sum(1 for c in cookies if c.secure)
    httponly_count = sum(1 for c in cookies if c.http_only)
    samesite_count = sum(1 for c in cookies if c.same_site in ("Strict", "Lax"))
    session_count = sum(1 for c in cookies if c.session)
    third_party_count = sum(1 for c in cookies if c.is_third_party)
    issues_count = sum(
        1 for c in cookies
        if c.missing_secure or c.missing_http_only or c.missing_same_site or c.value_too_large
    )

    return CookieJarReport(
        cookies=cookies,
        total_count=len(cookies),
        secure_count=secure_count,
        httponly_count=httponly_count,
        samesite_count=samesite_count,
        session_count=session_count,
        third_party_count=third_party_count,
        issues_count=issues_count,
    )
