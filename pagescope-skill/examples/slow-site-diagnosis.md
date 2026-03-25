# Web Diagnostic Report: https://example-store.com

## Summary
Page loads in 6.2s due to unoptimized hero image (3.1MB) and render-blocking third-party scripts.

## Findings (by severity)

### ERROR: Largest Contentful Paint exceeds threshold
- **Category:** performance
- **Description:** LCP measured at 5,840ms (threshold: 2,500ms). The LCP element is a hero image at /images/banner-full.png (3.1MB, uncompressed PNG).
- **Recommendation:** Convert to WebP/AVIF format, serve responsive sizes via srcset, and add `fetchpriority="high"`.

### WARNING: Render-blocking scripts detected
- **Category:** network
- **Description:** 3 synchronous script tags in `<head>` block first paint for 1,200ms. Scripts: analytics.js (280KB), chat-widget.js (450KB), tracking.js (120KB).
- **Recommendation:** Add `async` or `defer` attributes. Consider loading chat widget on user interaction instead of page load.

### WARNING: No caching headers on static assets
- **Category:** network
- **Description:** 14 static resources served without Cache-Control headers, forcing full re-download on every visit.
- **Recommendation:** Set `Cache-Control: public, max-age=31536000` for hashed/versioned assets.

### INFO: CLS within acceptable range
- **Category:** performance
- **Description:** CLS measured at 0.04 (threshold: 0.1). No significant layout shifts detected.
- **Recommendation:** No action needed.

## Modules Run
- **performance**: completed (2,340ms) -- Web Vitals, resource timing
- **network**: completed (1,890ms) -- 47 requests, 4.8MB total transfer

## Next Steps
1. Optimize the hero image (biggest single win -- saves ~2.5s)
2. Defer non-critical scripts
3. Add cache headers to static assets
