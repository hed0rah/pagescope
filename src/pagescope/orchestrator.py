"""Orchestrator -- maps symptoms to diagnostic flows via decision trees."""

from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import Sequence

from pagescope.models.common import Finding, Severity
from pagescope.models.console import ConsoleLevel, ConsoleReport
from pagescope.models.network import NetworkReport
from pagescope.models.performance import PerformanceReport
from pagescope.models.report import DiagnosticFlow, DiagnosticReport
from pagescope.session import DiagnosticSession


class Symptom(str, Enum):
    """High-level symptoms that map to diagnostic flows."""

    SLOW_PAGE = "slow_page"
    BROKEN_LAYOUT = "broken_layout"
    API_FAILURES = "api_failures"
    CONSOLE_ERRORS = "console_errors"
    SECURITY_WARNINGS = "security_warnings"
    ACCESSIBILITY_ISSUES = "accessibility_issues"
    INTERACTIVE_ISSUES = "interactive_issues"
    GENERAL_HEALTH = "general_health"


# decision trees: symptom -> ordered list of modules to run
DECISION_TREES: dict[Symptom, list[str]] = {
    Symptom.SLOW_PAGE: ["performance", "network", "dom"],
    Symptom.BROKEN_LAYOUT: ["console", "network", "dom"],
    Symptom.API_FAILURES: ["network", "console", "security"],
    Symptom.CONSOLE_ERRORS: ["console", "network"],
    Symptom.SECURITY_WARNINGS: ["security", "network", "console"],
    Symptom.ACCESSIBILITY_ISSUES: ["accessibility", "dom", "console"],
    Symptom.INTERACTIVE_ISSUES: ["interactive", "console", "dom", "network"],
    Symptom.GENERAL_HEALTH: ["console", "network", "performance", "security", "accessibility"],
}


class Orchestrator:
    """Runs diagnostic flows based on symptoms and decision trees.

    Given symptom(s), the orchestrator:
    1. Resolves the decision tree to determine which modules to run
    2. Sets up all modules first (so CDP listeners capture from the start)
    3. Runs analysis in the prescribed order
    4. Merges results into a unified DiagnosticReport with findings
    """

    def __init__(self, session: DiagnosticSession) -> None:
        self._session = session
        self._module_map = {
            "network": session.network,
            "performance": session.performance,
            "console": session.console,
            "security": session.security,
            "dom": session.dom,
            "accessibility": session.accessibility,
            "interactive": session.interactive,
        }

    async def diagnose(
        self,
        url: str | None = None,
        symptoms: Sequence[Symptom] | None = None,
        modules: Sequence[str] | None = None,
    ) -> DiagnosticReport:
        if modules:
            to_run = list(dict.fromkeys(modules))
        elif symptoms:
            to_run = self._resolve_symptoms(symptoms)
        else:
            to_run = DECISION_TREES[Symptom.GENERAL_HEALTH]

        # Set up all modules BEFORE navigation so CDP listeners capture everything
        for name in to_run:
            module = self._module_map.get(name)
            if module:
                try:
                    await module.setup()
                except Exception:
                    pass

        # navigate after listeners are in place
        if url:
            await self._session.navigate(url)

        flows: list[DiagnosticFlow] = []
        for name in to_run:
            module = self._module_map.get(name)
            if module is None:
                continue
            t0 = time.monotonic()
            try:
                timeout_s = self._session.config.module_timeout_ms / 1000
                report = await asyncio.wait_for(module.analyze(), timeout=timeout_s)
                duration = (time.monotonic() - t0) * 1000
                flows.append(
                    DiagnosticFlow(
                        module=name,
                        report=report.model_dump(),
                        status="completed",
                        duration_ms=round(duration, 2),
                    )
                )
            except asyncio.TimeoutError:
                duration = (time.monotonic() - t0) * 1000
                flows.append(
                    DiagnosticFlow(
                        module=name,
                        report=None,
                        status="error",
                        error=f"module timed out after {self._session.config.module_timeout_ms}ms",
                        duration_ms=round(duration, 2),
                    )
                )
            except Exception as exc:
                duration = (time.monotonic() - t0) * 1000
                flows.append(
                    DiagnosticFlow(
                        module=name,
                        report=None,
                        status="error",
                        error=str(exc),
                        duration_ms=round(duration, 2),
                    )
                )

        findings = self._extract_findings(flows)
        recommendations = self._generate_recommendations(findings)

        return DiagnosticReport(
            url=self._session.page.url,
            flows=flows,
            findings=findings,
            recommendations=recommendations,
        )

    def _resolve_symptoms(self, symptoms: Sequence[Symptom]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for symptom in symptoms:
            for module in DECISION_TREES.get(symptom, []):
                if module not in seen:
                    seen.add(module)
                    result.append(module)
        return result

    def _extract_findings(self, flows: list[DiagnosticFlow]) -> list[Finding]:
        findings: list[Finding] = []

        for flow in flows:
            if flow.status != "completed" or flow.report is None:
                if flow.status == "error":
                    findings.append(
                        Finding(
                            severity=Severity.ERROR,
                            category=flow.module,
                            title=f"{flow.module} diagnostic failed",
                            description=flow.error or "Unknown error",
                        )
                    )
                continue

            if flow.module == "console":
                findings.extend(self._findings_from_console(flow.report))
            elif flow.module == "network":
                findings.extend(self._findings_from_network(flow.report))
            elif flow.module == "performance":
                findings.extend(self._findings_from_performance(flow.report))
            elif flow.module == "security":
                findings.extend(self._findings_from_security(flow.report))
            elif flow.module == "dom":
                findings.extend(self._findings_from_dom(flow.report))
            elif flow.module == "accessibility":
                findings.extend(self._findings_from_accessibility(flow.report))
            elif flow.module == "interactive":
                findings.extend(self._findings_from_interactive(flow.report))

        # sort by severity
        severity_order = {
            Severity.CRITICAL: 0,
            Severity.ERROR: 1,
            Severity.WARNING: 2,
            Severity.INFO: 3,
        }
        findings.sort(key=lambda f: severity_order.get(f.severity, 99))
        return findings

    def _findings_from_console(self, data: dict) -> list[Finding]:
        findings = []
        summary = data.get("summary", {})

        if summary.get("exceptions", 0) > 0:
            exceptions = data.get("exceptions", [])
            for exc in exceptions[:5]:  # Cap at 5
                findings.append(
                    Finding(
                        severity=Severity.ERROR,
                        category="console",
                        title="Unhandled exception",
                        description=exc.get("message", "Unknown"),
                        details={"stack_trace": exc.get("stack_trace", "")},
                    )
                )

        if summary.get("errors", 0) > 0:
            error_count = summary["errors"]
            findings.append(
                Finding(
                    severity=Severity.ERROR,
                    category="console",
                    title=f"{error_count} console error(s)",
                    description="Page logged errors to the console.",
                    details={
                        "count": error_count,
                        "sample": [
                            e.get("text", "")
                            for e in data.get("entries", [])
                            if e.get("level") == ConsoleLevel.ERROR.value
                        ][:3],
                    },
                )
            )

        if summary.get("warnings", 0) > 5:
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    category="console",
                    title=f"{summary['warnings']} console warnings",
                    description="High number of console warnings.",
                )
            )

        return findings

    def _findings_from_network(self, data: dict) -> list[Finding]:
        findings = []
        failed = data.get("failed_requests", [])
        slow = data.get("slow_requests", [])
        summary = data.get("summary", {})

        for req in failed[:5]:
            severity = Severity.ERROR if req.get("status", 0) >= 500 else Severity.WARNING
            findings.append(
                Finding(
                    severity=severity,
                    category="network",
                    title=f"Failed request: {req.get('status', 0)} {req.get('url', '')[:80]}",
                    description=req.get("failure") or f"HTTP {req.get('status', 0)}",
                    details=req,
                )
            )

        if slow:
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    category="network",
                    title=f"{len(slow)} slow request(s)",
                    description="Requests exceeding the slow threshold.",
                    details={
                        "count": len(slow),
                        "urls": [s.get("url", "")[:80] for s in slow[:5]],
                    },
                )
            )

        total_bytes = summary.get("total_transfer_bytes", 0)
        if total_bytes > 5_000_000:  # 5MB
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    category="network",
                    title=f"Large page weight: {total_bytes / 1_000_000:.1f}MB",
                    description="Total transfer size exceeds 5MB.",
                    details={"bytes": total_bytes, "by_type": summary.get("requests_by_type", {})},
                    recommendation="Optimize images, enable compression, remove unused resources.",
                )
            )

        return findings

    def _findings_from_performance(self, data: dict) -> list[Finding]:
        findings = []
        vitals = data.get("web_vitals", {})

        lcp = vitals.get("lcp_ms")
        if lcp is not None and lcp > 2500:
            severity = Severity.CRITICAL if lcp > 4000 else Severity.WARNING
            findings.append(
                Finding(
                    severity=severity,
                    category="performance",
                    title=f"Slow LCP: {lcp:.0f}ms",
                    description=f"Largest Contentful Paint is {lcp:.0f}ms (target: <2500ms).",
                    recommendation="Optimize the largest visible element -- compress images, preload critical resources.",
                )
            )

        fcp = vitals.get("fcp_ms")
        if fcp is not None and fcp > 1800:
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    category="performance",
                    title=f"Slow FCP: {fcp:.0f}ms",
                    description=f"First Contentful Paint is {fcp:.0f}ms (target: <1800ms).",
                    recommendation="Reduce render-blocking resources, inline critical CSS.",
                )
            )

        cls = vitals.get("cls")
        if cls is not None and cls > 0.1:
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    category="performance",
                    title=f"High CLS: {cls:.3f}",
                    description=f"Cumulative Layout Shift is {cls:.3f} (target: <0.1).",
                    recommendation="Add width/height to images, avoid dynamic content injection.",
                )
            )

        ttfb = vitals.get("ttfb_ms")
        if ttfb is not None and ttfb > 800:
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    category="performance",
                    title=f"Slow TTFB: {ttfb:.0f}ms",
                    description=f"Time to First Byte is {ttfb:.0f}ms (target: <800ms).",
                    recommendation="Server is slow to respond -- check backend, enable caching, use CDN.",
                )
            )

        return findings

    def _findings_from_security(self, data: dict) -> list[Finding]:
        findings = []
        summary = data.get("summary", {})

        if summary.get("mixed_content_count", 0) > 0:
            mc = data.get("mixed_content", [])
            findings.append(
                Finding(
                    severity=Severity.ERROR,
                    category="security",
                    title=f"{len(mc)} mixed content issue(s)",
                    description="HTTP resources loaded from an HTTPS page.",
                    details={"urls": [m.get("url", "")[:80] for m in mc[:5]]},
                    recommendation="Ensure all resources use HTTPS URLs.",
                )
            )

        if summary.get("csp_violation_count", 0) > 0:
            csp = data.get("csp_violations", [])
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    category="security",
                    title=f"{len(csp)} CSP violation(s)",
                    description="Content-Security-Policy blocked resources.",
                    details={"violations": [
                        {"url": v.get("blocked_url", ""), "directive": v.get("violated_directive", "")}
                        for v in csp[:5]
                    ]},
                )
            )

        if summary.get("insecure_form_count", 0) > 0:
            forms = data.get("insecure_forms", [])
            findings.append(
                Finding(
                    severity=Severity.ERROR,
                    category="security",
                    title=f"{len(forms)} insecure form(s)",
                    description="Forms submit data over unencrypted HTTP.",
                    details={"forms": forms},
                    recommendation="Change form actions to HTTPS URLs.",
                )
            )

        state = summary.get("security_state", "unknown")
        if state == "insecure":
            findings.append(
                Finding(
                    severity=Severity.CRITICAL,
                    category="security",
                    title="Page is insecure",
                    description="The page or its resources are served over unencrypted HTTP.",
                    recommendation="Enable HTTPS with a valid TLS certificate.",
                )
            )

        return findings

    def _findings_from_dom(self, data: dict) -> list[Finding]:
        findings = []
        summary = data.get("summary", {})
        size = data.get("size_metrics", {})

        node_count = size.get("total_elements", 0)
        if node_count > 1500:
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    category="dom",
                    title=f"Large DOM: {node_count} elements",
                    description=f"DOM has {node_count} elements (recommended: <1500).",
                    recommendation="Reduce DOM size -- remove unnecessary wrappers, virtualize long lists.",
                )
            )

        max_depth = size.get("max_depth", 0)
        if max_depth > 32:
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    category="dom",
                    title=f"Deep DOM nesting: {max_depth} levels",
                    description=f"DOM nesting depth is {max_depth} (recommended: <32).",
                    recommendation="Flatten component hierarchy to reduce nesting.",
                )
            )

        css = data.get("css_coverage", {})
        unused_pct = css.get("unused_pct", 0)
        if unused_pct > 50:
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    category="dom",
                    title=f"{unused_pct:.0f}% CSS unused",
                    description=f"{unused_pct:.0f}% of CSS rules are unused on this page.",
                    recommendation="Purge unused CSS with a tool like PurgeCSS or use CSS code splitting.",
                )
            )

        layout_issues = data.get("layout_issues", [])
        for issue in layout_issues[:5]:
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    category="dom",
                    title=issue.get("issue_type", "Layout issue"),
                    description=issue.get("details", ""),
                )
            )

        if not summary.get("has_viewport", True):
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    category="dom",
                    title="Missing viewport meta tag",
                    description="Page has no <meta name='viewport'> -- mobile rendering will be incorrect.",
                    recommendation="Add <meta name='viewport' content='width=device-width, initial-scale=1.0'>.",
                )
            )

        return findings

    def _findings_from_accessibility(self, data: dict) -> list[Finding]:
        findings = []
        summary = data.get("summary", {})

        if not summary.get("has_lang", True):
            findings.append(
                Finding(
                    severity=Severity.ERROR,
                    category="accessibility",
                    title="Missing lang attribute",
                    description="<html> element has no lang attribute. Screen readers need this to set the correct language.",
                    recommendation='Add lang="en" (or appropriate language) to the <html> element.',
                )
            )

        if not summary.get("has_title", True):
            findings.append(
                Finding(
                    severity=Severity.ERROR,
                    category="accessibility",
                    title="Missing or empty page title",
                    description="<title> is missing or empty. This is the first thing screen readers announce.",
                    recommendation="Add a descriptive <title> to the page.",
                )
            )

        if not summary.get("has_landmarks", True):
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    category="accessibility",
                    title="Missing landmark regions",
                    description="Page is missing header/main/footer landmarks. Screen readers use these for navigation.",
                    recommendation="Use <header>, <main>, and <footer> elements (or ARIA landmark roles).",
                )
            )

        if not summary.get("has_skip_link", True):
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    category="accessibility",
                    title="No skip navigation link",
                    description="Page has no skip-to-content link. Keyboard users must tab through all navigation.",
                    recommendation='Add a "Skip to main content" link as the first focusable element.',
                )
            )

        img_issues = data.get("image_issues", [])
        if img_issues:
            findings.append(
                Finding(
                    severity=Severity.ERROR,
                    category="accessibility",
                    title=f"{len(img_issues)} image(s) without alt text",
                    description="Images must have alt attributes for screen readers.",
                    details={"images": [i.get("src", "")[:60] for i in img_issues[:5]]},
                    recommendation="Add descriptive alt text to informative images, or alt='' for decorative ones.",
                )
            )

        form_issues = data.get("form_issues", [])
        if form_issues:
            findings.append(
                Finding(
                    severity=Severity.ERROR,
                    category="accessibility",
                    title=f"{len(form_issues)} form input(s) without labels",
                    description="Form inputs need associated <label> elements or aria-label attributes.",
                    details={"inputs": [f.get("selector", "") for f in form_issues[:5]]},
                    recommendation="Add <label for='id'> or aria-label to all form inputs.",
                )
            )

        heading_issues = data.get("heading_issues", [])
        for h in heading_issues[:3]:
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    category="accessibility",
                    title=f"Heading issue: {h.get('issue', '')}",
                    description=h.get("details", ""),
                )
            )

        contrast = data.get("contrast_issues", [])
        if contrast:
            findings.append(
                Finding(
                    severity=Severity.ERROR,
                    category="accessibility",
                    title=f"{len(contrast)} contrast issue(s)",
                    description="Text elements don't meet WCAG AA contrast ratio requirements.",
                    details={"samples": [
                        {"text": c.get("text_sample", ""), "ratio": c.get("contrast_ratio", 0)}
                        for c in contrast[:5]
                    ]},
                    recommendation="Increase color contrast between text and background (min 4.5:1 for normal text).",
                )
            )

        aria = data.get("aria_issues", [])
        if aria:
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    category="accessibility",
                    title=f"{len(aria)} ARIA issue(s)",
                    description="ARIA roles are used incorrectly or missing keyboard support.",
                    details={"issues": [a.get("details", "") for a in aria[:5]]},
                )
            )

        return findings

    def _findings_from_interactive(self, data: dict) -> list[Finding]:
        findings = []
        summary = data.get("summary", {})
        tested_elements = data.get("tested_elements", [])
        interaction_log = data.get("interaction_log", {})

        # check for failed interactions
        failed_interactions = 0
        for element in tested_elements:
            if element.get("action") == "click" and not element.get("success"):
                failed_interactions += 1
            elif element.get("action") == "form_test":
                if not element.get("fill_success") or not element.get("submission", {}).get("success"):
                    failed_interactions += 1

        if failed_interactions > 0:
            findings.append(
                Finding(
                    severity=Severity.ERROR,
                    category="interactive",
                    title=f"{failed_interactions} interactive element(s) failed",
                    description=f"Failed to interact with {failed_interactions} buttons, forms, or other interactive elements.",
                    details={"failed_count": failed_interactions, "total_tested": len(tested_elements)},
                    recommendation="Check JavaScript errors, element visibility, and click handlers.",
                )
            )

        # check for forms that couldn't be filled
        forms_with_issues = []
        for element in tested_elements:
            if element.get("action") == "form_test":
                submission = element.get("submission", {})
                if submission.get("error_messages"):
                    forms_with_issues.append({
                        "form": element.get("element", {}).get("selector", ""),
                        "errors": submission.get("error_messages", [])
                    })

        if forms_with_issues:
            findings.append(
                Finding(
                    severity=Severity.ERROR,
                    category="interactive",
                    title=f"{len(forms_with_issues)} form(s) have submission issues",
                    description="Forms are submitting but returning error messages.",
                    details={"forms": forms_with_issues},
                    recommendation="Check form validation, required fields, and server-side processing.",
                )
            )

        # check for missing interactive elements
        total_elements = summary.get("total_elements", 0)
        forms_found = summary.get("forms_found", 0)
        buttons_found = summary.get("buttons_found", 0)

        if total_elements == 0:
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    category="interactive",
                    title="No interactive elements found",
                    description="Page appears to have no forms, buttons, or other interactive elements.",
                    recommendation="Consider adding interactive elements if this is a user-facing application.",
                )
            )

        # check interaction log for errors
        interaction_events = interaction_log.get("events", [])
        error_events = [e for e in interaction_events if e.get("action") == "error"]

        if error_events:
            findings.append(
                Finding(
                    severity=Severity.ERROR,
                    category="interactive",
                    title=f"{len(error_events)} interaction error(s)",
                    description="Errors occurred during interaction attempts.",
                    details={"errors": [e.get("details", "") for e in error_events[:5]]},
                    recommendation="Review JavaScript console for errors and fix interaction handlers.",
                )
            )

        # check for modals that might be blocking interactions
        modals_found = summary.get("modals_found", 0)
        if modals_found > 0:
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    category="interactive",
                    title=f"{modals_found} modal(s) detected",
                    description="Page contains modals that might block interactions with underlying elements.",
                    recommendation="Ensure modals don't interfere with user interactions and have proper focus management.",
                )
            )

        return findings

    def _generate_recommendations(self, findings: list[Finding]) -> list[str]:
        recs = []
        for f in findings:
            if f.recommendation:
                recs.append(f.recommendation)
        return recs
