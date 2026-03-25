"""Forensics diagnostic module -- deep page inspection for CTF, security audit, debugging."""

from __future__ import annotations

import re

from playwright.async_api import Page

from pagescope.models.forensics import (
    Endpoint,
    ForensicsReport,
    HiddenElement,
    MetaTag,
    PageComment,
    ResponseBodyMatch,
    SecurityHeader,
    SecurityHeadersReport,
)


# ── Security Headers Definitions ──

# (header_name, required, description, good_pattern, bad_pattern)
_SECURITY_HEADERS = [
    (
        "Strict-Transport-Security",
        True,
        "Enforces HTTPS connections",
        r"max-age=\d{7,}",  # At least ~4 months
        None,
    ),
    (
        "Content-Security-Policy",
        True,
        "Controls which resources the browser can load",
        None,  # Any CSP is better than none
        r"unsafe-inline.*unsafe-eval|unsafe-eval.*unsafe-inline",
    ),
    (
        "X-Content-Type-Options",
        True,
        "Prevents MIME type sniffing",
        r"^nosniff$",
        None,
    ),
    (
        "X-Frame-Options",
        False,
        "Prevents clickjacking (superseded by CSP frame-ancestors)",
        r"^(DENY|SAMEORIGIN)$",
        r"^ALLOW-FROM",
    ),
    (
        "Referrer-Policy",
        False,
        "Controls referrer information leakage",
        r"(strict-origin|no-referrer|same-origin)",
        r"^unsafe-url$",
    ),
    (
        "Permissions-Policy",
        False,
        "Controls browser feature access (camera, mic, geolocation, etc.)",
        None,
        None,
    ),
    (
        "X-XSS-Protection",
        False,
        "Legacy XSS filter (deprecated but still useful for old browsers)",
        r"^1;\s*mode=block$",
        r"^0$",
    ),
    (
        "Cross-Origin-Opener-Policy",
        False,
        "Isolates browsing context for cross-origin attacks",
        r"same-origin",
        None,
    ),
    (
        "Cross-Origin-Resource-Policy",
        False,
        "Controls cross-origin resource loading",
        r"(same-origin|same-site)",
        None,
    ),
    (
        "Cross-Origin-Embedder-Policy",
        False,
        "Required for SharedArrayBuffer and high-resolution timers",
        r"require-corp",
        None,
    ),
]

# patterns that are interesting in comments/hidden content
_INTERESTING_PATTERNS = [
    r"(?i)(password|passwd|pwd)\s*[:=]",
    r"(?i)(api[_-]?key|apikey|secret[_-]?key|auth[_-]?token)\s*[:=]",
    r"(?i)(todo|fixme|hack|xxx|bug)\b",
    r"(?i)(admin|root|debug|test)\s*(url|path|endpoint|page)",
    r"(?i)flag\{[^}]+\}",  # CTF flags
    r"(?i)(version|v)\s*[:=]\s*[\d.]+",
    r"(?i)(internal|staging|dev|localhost|127\.0\.0\.1)",
    r"(?i)(bearer|jwt|token)\s+[a-zA-Z0-9._-]{10,}",
    r"[a-f0-9]{32,64}",  # Hex strings (hashes, tokens)
    r"(?i)(BEGIN\s+(RSA|DSA|EC|OPENSSH)\s+PRIVATE\s+KEY)",
    r"(?i)(aws_access_key|aws_secret|AKIA[0-9A-Z]{16})",
]


def _is_interesting(text: str) -> bool:
    """Check if text contains interesting patterns."""
    for pattern in _INTERESTING_PATTERNS:
        if re.search(pattern, text):
            return True
    return False


def _grade_score(score: int) -> str:
    """Convert a numeric score to a letter grade."""
    if score >= 90:
        return "A+"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B"
    if score >= 60:
        return "C"
    if score >= 50:
        return "D"
    return "F"


def analyze_security_headers(headers: dict[str, str]) -> SecurityHeadersReport:
    """Score a page's security headers."""
    # normalize header names to lowercase for lookup
    lower_headers = {k.lower(): (k, v) for k, v in headers.items()}

    results: list[SecurityHeader] = []
    score = 100
    missing_critical: list[str] = []

    for name, required, desc, good_pattern, bad_pattern in _SECURITY_HEADERS:
        key = name.lower()
        orig_name, value = lower_headers.get(key, (name, ""))
        present = key in lower_headers

        if not present:
            grade = "bad" if required else "warning"
            rec = f"Add {name} header. {desc}."
            if required:
                score -= 15
                missing_critical.append(name)
            else:
                score -= 5
        else:
            if bad_pattern and re.search(bad_pattern, value, re.IGNORECASE):
                grade = "warning"
                rec = f"{name} is present but has a weak configuration."
                score -= 5
            elif good_pattern and re.search(good_pattern, value, re.IGNORECASE):
                grade = "good"
                rec = ""
            elif good_pattern:
                grade = "warning"
                rec = f"{name} is present but may not be optimally configured."
                score -= 3
            else:
                grade = "good"
                rec = ""

        results.append(
            SecurityHeader(
                name=name,
                present=present,
                value=value,
                grade=grade,
                recommendation=rec,
            )
        )

    # check for information disclosure headers
    info_headers = [
        "Server", "X-Powered-By", "X-AspNet-Version", "X-AspNetMvc-Version",
    ]
    for hdr in info_headers:
        key = hdr.lower()
        if key in lower_headers:
            _, value = lower_headers[key]
            results.append(
                SecurityHeader(
                    name=hdr,
                    present=True,
                    value=value,
                    grade="info",
                    recommendation=f"Consider removing {hdr} to reduce information disclosure.",
                )
            )
            score -= 2

    score = max(0, min(100, score))

    return SecurityHeadersReport(
        headers=results,
        score=score,
        grade=_grade_score(score),
        missing_critical=missing_critical,
    )


async def find_hidden_elements(page: Page) -> list[HiddenElement]:
    """Find hidden DOM elements that might contain interesting content."""
    try:
        data = await page.evaluate("""
            () => {
                const results = [];
                const all = document.querySelectorAll('*');
                for (const el of all) {
                    const style = window.getComputedStyle(el);
                    let reason = '';

                    if (style.display === 'none') reason = 'display:none';
                    else if (style.visibility === 'hidden') reason = 'visibility:hidden';
                    else if (style.opacity === '0') reason = 'opacity:0';
                    else if (el.hasAttribute('hidden')) reason = 'hidden attribute';
                    else if (el.getAttribute('aria-hidden') === 'true') reason = 'aria-hidden';
                    else if (el.type === 'hidden') reason = 'input[type=hidden]';
                    else {
                        const rect = el.getBoundingClientRect();
                        if (rect.width === 0 && rect.height === 0 && el.children.length === 0) {
                            reason = 'zero-size';
                        } else if (rect.left < -9000 || rect.top < -9000) {
                            reason = 'off-screen positioning';
                        }
                    }

                    if (!reason) continue;

                    // Skip trivial elements
                    const text = (el.textContent || '').trim();
                    if (!text && !el.querySelector('a, form, input, img, script')) continue;

                    // Build selector
                    let selector = el.tagName.toLowerCase();
                    if (el.id) selector += '#' + el.id;
                    else if (el.className && typeof el.className === 'string') {
                        selector += '.' + el.className.trim().split(/\\s+/).slice(0, 2).join('.');
                    }

                    const attrs = {};
                    for (const attr of el.attributes) {
                        if (['style', 'class', 'id'].includes(attr.name)) continue;
                        attrs[attr.name] = attr.value.substring(0, 200);
                    }

                    results.push({
                        tag: el.tagName.toLowerCase(),
                        selector: selector,
                        reason: reason,
                        text_content: text.substring(0, 500),
                        attributes: attrs,
                        has_links: !!el.querySelector('a[href]'),
                        has_forms: !!el.querySelector('form'),
                        has_inputs: !!el.querySelector('input'),
                    });
                }
                return results.slice(0, 200);
            }
        """)
        return [HiddenElement(**d) for d in (data or [])]
    except Exception:
        return []


async def extract_comments(page: Page) -> list[PageComment]:
    """Extract HTML comments from the page."""
    try:
        data = await page.evaluate("""
            () => {
                const comments = [];
                const walker = document.createTreeWalker(
                    document, NodeFilter.SHOW_COMMENT
                );
                while (walker.nextNode()) {
                    const node = walker.currentNode;
                    const text = node.textContent.trim();
                    if (!text) continue;

                    // Determine location
                    let location = 'body';
                    let parent = node.parentElement;
                    if (parent) {
                        if (parent.tagName === 'HEAD' || parent.closest('head'))
                            location = 'head';
                        else if (parent.tagName === 'SCRIPT' || parent.closest('script'))
                            location = 'script';
                    }

                    comments.push({
                        text: text.substring(0, 1000),
                        location: location,
                    });
                }
                return comments;
            }
        """)
        results = []
        for d in (data or []):
            comment = PageComment(
                text=d.get("text", ""),
                location=d.get("location", ""),
                interesting=_is_interesting(d.get("text", "")),
            )
            results.append(comment)
        return results
    except Exception:
        return []


async def discover_endpoints(page: Page) -> list[Endpoint]:
    """Discover all URLs/endpoints referenced in the page."""
    try:
        data = await page.evaluate("""
            () => {
                const endpoints = [];
                const seen = new Set();

                function add(url, source, method, context) {
                    if (!url || url.startsWith('javascript:') || url.startsWith('data:')) return;
                    const key = method + ':' + url;
                    if (seen.has(key)) return;
                    seen.add(key);
                    endpoints.push({ url, source, method: method || 'GET', context: context || '' });
                }

                // Links
                for (const a of document.querySelectorAll('a[href]')) {
                    add(a.href, 'link', 'GET', a.textContent.trim().substring(0, 80));
                }

                // Forms
                for (const form of document.querySelectorAll('form')) {
                    const action = form.action || window.location.href;
                    const method = (form.method || 'GET').toUpperCase();
                    add(action, 'form', method, form.id || form.name || '');
                }

                // Scripts
                for (const s of document.querySelectorAll('script[src]')) {
                    add(s.src, 'script', 'GET', '');
                }

                // Stylesheets
                for (const l of document.querySelectorAll('link[rel="stylesheet"]')) {
                    add(l.href, 'stylesheet', 'GET', '');
                }

                // Images
                for (const img of document.querySelectorAll('img[src]')) {
                    add(img.src, 'image', 'GET', img.alt || '');
                }

                // Iframes
                for (const iframe of document.querySelectorAll('iframe[src]')) {
                    add(iframe.src, 'iframe', 'GET', iframe.title || iframe.name || '');
                }

                // Meta redirects
                for (const meta of document.querySelectorAll('meta[http-equiv="refresh"]')) {
                    const content = meta.getAttribute('content') || '';
                    const match = content.match(/url=(.+)/i);
                    if (match) add(match[1].trim(), 'meta-refresh', 'GET', '');
                }

                // Open Graph / canonical
                for (const meta of document.querySelectorAll('meta[property^="og:"], link[rel="canonical"]')) {
                    const url = meta.getAttribute('content') || meta.getAttribute('href') || '';
                    if (url.startsWith('http')) add(url, 'meta', 'GET', meta.getAttribute('property') || 'canonical');
                }

                return endpoints;
            }
        """)
        return [Endpoint(**d) for d in (data or [])]
    except Exception:
        return []


async def extract_metadata(page: Page) -> list[MetaTag]:
    """Extract all meta tags from the page."""
    try:
        data = await page.evaluate("""
            () => {
                const tags = [];
                for (const meta of document.querySelectorAll('meta')) {
                    tags.push({
                        name: meta.getAttribute('name') || '',
                        property: meta.getAttribute('property') || '',
                        content: (meta.getAttribute('content') || '').substring(0, 500),
                        http_equiv: meta.getAttribute('http-equiv') || '',
                    });
                }
                return tags;
            }
        """)
        return [MetaTag(**d) for d in (data or [])]
    except Exception:
        return []


def search_response_bodies(
    requests: list, pattern: str
) -> list[ResponseBodyMatch]:
    """Search across all captured response bodies for a pattern."""
    matches: list[ResponseBodyMatch] = []
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error:
        # fall back to literal string search
        regex = re.compile(re.escape(pattern), re.IGNORECASE)

    for req in requests:
        body = getattr(req, "response_body", None)
        if not body or body.startswith("[base64 encoded"):
            continue

        content_type = ""
        resp_headers = getattr(req, "response_headers", {}) or {}
        for k, v in resp_headers.items():
            if k.lower() == "content-type":
                content_type = v
                break

        for line_num, line in enumerate(body.split("\n"), 1):
            for m in regex.finditer(line):
                # get surrounding context
                start = max(0, m.start() - 40)
                end = min(len(line), m.end() + 40)
                context = line[start:end]

                matches.append(
                    ResponseBodyMatch(
                        url=req.url,
                        content_type=content_type,
                        match_text=m.group(),
                        line_number=line_num,
                        context=context,
                    )
                )

            # cap total matches
            if len(matches) > 500:
                return matches

    return matches


async def run_forensics(page: Page, response_headers: dict[str, str] | None = None) -> ForensicsReport:
    """Run full forensics analysis on the current page."""
    headers_report = SecurityHeadersReport()
    if response_headers:
        headers_report = analyze_security_headers(response_headers)

    hidden = await find_hidden_elements(page)
    comments = await extract_comments(page)
    endpoints = await discover_endpoints(page)
    meta_tags = await extract_metadata(page)

    # compile interesting findings
    findings: list[str] = []

    interesting_comments = [c for c in comments if c.interesting]
    if interesting_comments:
        findings.append(
            f"Found {len(interesting_comments)} comment(s) with interesting content"
        )

    hidden_with_content = [h for h in hidden if h.has_links or h.has_forms or h.has_inputs]
    if hidden_with_content:
        findings.append(
            f"Found {len(hidden_with_content)} hidden element(s) containing links, forms, or inputs"
        )

    if headers_report.missing_critical:
        findings.append(
            f"Missing critical security headers: {', '.join(headers_report.missing_critical)}"
        )

    # check for interesting hidden text
    for h in hidden:
        if _is_interesting(h.text_content):
            findings.append(
                f"Hidden element <{h.tag}> contains interesting text: "
                f"{h.text_content[:80]}..."
            )

    return ForensicsReport(
        security_headers=headers_report,
        hidden_elements=hidden,
        comments=comments,
        endpoints=endpoints,
        meta_tags=meta_tags,
        interesting_findings=findings,
    )
