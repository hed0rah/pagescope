"""HAR 1.2 export and import -- generate and load HTTP Archive files."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def _headers_to_har(headers: dict[str, str]) -> list[dict[str, str]]:
    """Convert a flat header dict to HAR name/value list."""
    return [{"name": k, "value": v} for k, v in headers.items()]


def _headers_size(headers: dict[str, str]) -> int:
    """Estimate header size in bytes."""
    if not headers:
        return -1
    # Each header: "Name: Value\r\n" + final "\r\n"
    return sum(len(k) + len(v) + 4 for k, v in headers.items()) + 2


def _timing_to_har(timing: dict[str, float]) -> dict[str, float]:
    """Convert CDP timing dict to HAR timings object."""
    return {
        "blocked": -1,
        "dns": max(timing.get("dnsEnd", 0) - timing.get("dnsStart", 0), 0) if timing.get("dnsStart", -1) >= 0 else -1,
        "connect": max(timing.get("connectEnd", 0) - timing.get("connectStart", 0), 0) if timing.get("connectStart", -1) >= 0 else -1,
        "send": max(timing.get("sendEnd", 0) - timing.get("sendStart", 0), 0) if timing.get("sendStart", -1) >= 0 else -1,
        "wait": max(timing.get("receiveHeadersEnd", 0) - timing.get("sendEnd", 0), 0) if timing.get("sendEnd", -1) >= 0 else -1,
        "receive": -1,  # Not directly available from CDP timing
        "ssl": max(timing.get("sslEnd", 0) - timing.get("sslStart", 0), 0) if timing.get("sslStart", -1) >= 0 else -1,
    }


def build_har(requests: list, page_url: str = "", page_title: str = "") -> dict[str, Any]:
    """Build a HAR 1.2 JSON object from a list of NetworkRequest dataclass instances.

    Args:
        requests: List of NetworkRequest dataclass objects from NetworkInspector._requests.
        page_url: The page URL for the HAR page entry.
        page_title: Optional page title.

    Returns:
        A dict conforming to HAR 1.2 spec, ready for json.dumps().
    """
    entries = []

    for req in requests:
        # start time as ISO 8601
        started = datetime.fromtimestamp(req.start_time, tz=timezone.utc).isoformat()

        # total time in ms
        if req.end_time and req.start_time:
            total_time = (req.end_time - req.start_time) * 1000
        else:
            total_time = 0

        # request object
        har_request: dict[str, Any] = {
            "method": req.method,
            "url": req.url,
            "httpVersion": req.protocol or "HTTP/1.1",
            "cookies": [],
            "headers": _headers_to_har(req.request_headers),
            "queryString": [],  # Would need URL parsing to populate
            "headersSize": _headers_size(req.request_headers),
            "bodySize": len(req.request_body) if req.request_body else 0,
        }
        if req.request_body:
            har_request["postData"] = {
                "mimeType": req.request_headers.get("Content-Type", ""),
                "text": req.request_body,
            }

        # response object
        status = req.response_status or 0
        content_type = req.response_headers.get("Content-Type", req.response_headers.get("content-type", ""))
        body_size = req.response_size or 0

        har_response: dict[str, Any] = {
            "status": status,
            "statusText": _status_text(status),
            "httpVersion": req.protocol or "HTTP/1.1",
            "cookies": [],
            "headers": _headers_to_har(req.response_headers),
            "content": {
                "size": body_size,
                "mimeType": content_type,
            },
            "redirectURL": req.response_headers.get("Location", req.response_headers.get("location", "")),
            "headersSize": _headers_size(req.response_headers),
            "bodySize": body_size,
        }

        # include response body text if captured
        if req.response_body:
            har_response["content"]["text"] = req.response_body

        # timings
        timings = _timing_to_har(req.timing) if req.timing else {
            "blocked": -1, "dns": -1, "connect": -1,
            "send": 0, "wait": total_time, "receive": 0, "ssl": -1,
        }

        entry: dict[str, Any] = {
            "startedDateTime": started,
            "time": total_time,
            "request": har_request,
            "response": har_response,
            "cache": {},
            "timings": timings,
        }

        # optional fields
        if req.remote_ip:
            entry["serverIPAddress"] = req.remote_ip
        if req.protocol:
            entry["connection"] = req.protocol

        # initiator as comment
        if req.initiator:
            init_type = req.initiator.get("type", "")
            init_url = req.initiator.get("url", "")
            if init_type:
                entry["comment"] = f"initiator: {init_type}"
                if init_url:
                    entry["comment"] += f" ({init_url})"

        entries.append(entry)

    # sort by start time
    entries.sort(key=lambda e: e["startedDateTime"])

    # build page entry
    page_id = "page_1"
    page_started = entries[0]["startedDateTime"] if entries else datetime.now(tz=timezone.utc).isoformat()

    har: dict[str, Any] = {
        "log": {
            "version": "1.2",
            "creator": {
                "name": "pagescope",
                "version": "0.1.0",
            },
            "pages": [
                {
                    "startedDateTime": page_started,
                    "id": page_id,
                    "title": page_title or page_url or "Captured Page",
                    "pageTimings": {
                        "onContentLoad": -1,
                        "onLoad": -1,
                    },
                }
            ],
            "entries": entries,
        }
    }

    # add pageref to all entries
    for entry in entries:
        entry["pageref"] = page_id

    return har


def export_har(requests: list, path: str, page_url: str = "", page_title: str = "") -> str:
    """Build HAR and write to a file.

    Returns the file path written.
    """
    har = build_har(requests, page_url=page_url, page_title=page_title)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(har, f, indent=2, ensure_ascii=False)
    return path


def _status_text(code: int) -> str:
    """Return standard HTTP status text for a code."""
    texts = {
        200: "OK", 201: "Created", 204: "No Content",
        301: "Moved Permanently", 302: "Found", 304: "Not Modified",
        400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
        404: "Not Found", 405: "Method Not Allowed",
        500: "Internal Server Error", 502: "Bad Gateway",
        503: "Service Unavailable",
    }
    return texts.get(code, "")


# ── HAR Import ──


def _har_headers_to_dict(har_headers: list[dict[str, str]]) -> dict[str, str]:
    """Convert HAR name/value header list to a flat dict."""
    return {h["name"]: h["value"] for h in har_headers if "name" in h and "value" in h}


def _har_timing_to_cdp(timings: dict[str, float]) -> dict[str, float]:
    """Convert HAR timings back to CDP-style timing dict for display.

    HAR stores durations; CDP stores absolute offsets. We synthesize
    offsets starting from 0 so the timing breakdown renders correctly.
    """
    cursor = 0.0
    cdp: dict[str, float] = {}

    dns = timings.get("dns", -1)
    if dns > 0:
        cdp["dnsStart"] = cursor
        cursor += dns
        cdp["dnsEnd"] = cursor
    else:
        cdp["dnsStart"] = -1
        cdp["dnsEnd"] = -1

    connect = timings.get("connect", -1)
    if connect > 0:
        cdp["connectStart"] = cursor
        cursor += connect
        cdp["connectEnd"] = cursor
    else:
        cdp["connectStart"] = -1
        cdp["connectEnd"] = -1

    ssl = timings.get("ssl", -1)
    if ssl > 0:
        cdp["sslStart"] = cdp.get("connectStart", cursor)
        cdp["sslEnd"] = cdp["sslStart"] + ssl
    else:
        cdp["sslStart"] = -1
        cdp["sslEnd"] = -1

    send = timings.get("send", -1)
    if send > 0:
        cdp["sendStart"] = cursor
        cursor += send
        cdp["sendEnd"] = cursor
    else:
        cdp["sendStart"] = cursor
        cdp["sendEnd"] = cursor

    wait = timings.get("wait", -1)
    if wait > 0:
        cursor += wait
        cdp["receiveHeadersEnd"] = cursor
    else:
        cdp["receiveHeadersEnd"] = cursor

    return cdp


def _guess_resource_type(mime: str, url: str) -> str:
    """Guess a CDP-style resource type from MIME type and URL."""
    mime = mime.lower().split(";")[0].strip()
    if "html" in mime:
        return "Document"
    if "javascript" in mime or "ecmascript" in mime:
        return "Script"
    if "css" in mime:
        return "Stylesheet"
    if mime.startswith("image/"):
        return "Image"
    if mime.startswith("font/") or "woff" in mime or "opentype" in mime:
        return "Font"
    if mime.startswith("video/") or mime.startswith("audio/"):
        return "Media"
    if "json" in mime or "xml" in mime:
        return "XHR"
    # fall back to URL extension
    lower_url = url.lower().split("?")[0]
    if lower_url.endswith((".js", ".mjs")):
        return "Script"
    if lower_url.endswith(".css"):
        return "Stylesheet"
    if lower_url.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico")):
        return "Image"
    if lower_url.endswith((".woff", ".woff2", ".ttf", ".otf", ".eot")):
        return "Font"
    return "Other"


def load_har(path: str) -> list:
    """Load a HAR file and return a list of NetworkRequest dataclass instances.

    Works with HAR files from Chrome DevTools, Firefox, pagescope, or any
    HAR 1.2 compliant source.
    """
    with open(path, "r", encoding="utf-8") as f:
        har = json.load(f)
    return import_har(har)


def import_har(har: dict[str, Any]) -> list:
    """Convert a parsed HAR dict into a list of NetworkRequest objects."""
    from pagescope.diagnostics.network import NetworkRequest

    log = har.get("log", har)  # Some files wrap in "log", some don't
    entries = log.get("entries", [])

    requests = []
    for i, entry in enumerate(entries):
        har_req = entry.get("request", {})
        har_resp = entry.get("response", {})
        har_timings = entry.get("timings", {})
        content = har_resp.get("content", {})

        # parse start time
        started_str = entry.get("startedDateTime", "")
        try:
            dt = datetime.fromisoformat(started_str.replace("Z", "+00:00"))
            start_time = dt.timestamp()
        except (ValueError, TypeError):
            start_time = 0.0

        # total time in ms -> end time
        total_ms = entry.get("time", 0)
        end_time = start_time + (total_ms / 1000) if total_ms > 0 else None

        # headers
        req_headers = _har_headers_to_dict(har_req.get("headers", []))
        resp_headers = _har_headers_to_dict(har_resp.get("headers", []))

        # response body
        resp_body = content.get("text", None)

        # request body
        post_data = har_req.get("postData", {})
        req_body = post_data.get("text", None) if post_data else None

        # size
        body_size = content.get("size", 0)
        if body_size <= 0:
            body_size = har_resp.get("bodySize", 0)

        # MIME type for resource type guessing
        mime = content.get("mimeType", "")
        url = har_req.get("url", "")

        # timing
        timing = _har_timing_to_cdp(har_timings) if har_timings else {}

        # protocol
        http_version = har_resp.get("httpVersion", har_req.get("httpVersion", ""))
        protocol = http_version if http_version and http_version != "unknown" else None

        # server IP
        server_ip = entry.get("serverIPAddress", None)

        req_obj = NetworkRequest(
            request_id=f"har-{i}",
            url=url,
            method=har_req.get("method", "GET"),
            resource_type=_guess_resource_type(mime, url),
            start_time=start_time,
            end_time=end_time,
            response_status=har_resp.get("status", 0),
            response_size=body_size if body_size > 0 else None,
            request_headers=req_headers,
            response_headers=resp_headers,
            timing=timing,
            initiator={},
            request_body=req_body,
            response_body=resp_body,
            remote_ip=server_ip,
            protocol=protocol,
        )
        requests.append(req_obj)

    return requests


def get_har_info(path: str) -> dict[str, Any]:
    """Get summary info about a HAR file without fully parsing all entries."""
    with open(path, "r", encoding="utf-8") as f:
        har = json.load(f)
    log = har.get("log", har)
    entries = log.get("entries", [])
    pages = log.get("pages", [])
    creator = log.get("creator", {})

    return {
        "entries": len(entries),
        "pages": len(pages),
        "page_titles": [p.get("title", "") for p in pages],
        "creator": creator.get("name", "unknown"),
        "creator_version": creator.get("version", ""),
    }
