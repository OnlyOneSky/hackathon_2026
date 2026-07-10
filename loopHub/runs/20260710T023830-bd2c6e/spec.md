---
story: hackdemo#39
spec_version: 1
generated: 2026-07-10T00:00:00Z
---
# Feature: Dashboard stats widget

## Summary
（審查決議：靜態示範數值即可；顯示格式不拘；不需 loading 狀態。）
Add a standalone `StatsWidget` Angular component to the dashboard so that a signed-in user can see three key numbers at a glance: Active users, Open tickets, and Deploys today. The widget displays static demo values with no backend or API calls. The login page is not touched.

## Acceptance criteria
- AC-1: A component file exists at `src/app/dashboard/stats-widget/stats-widget.ts`.
- AC-2: The `StatsWidget` component declares the selector `app-stats-widget`.
- AC-3: The `StatsWidget` component is a standalone Angular component (`standalone: true` or Angular ≥19 default standalone).
- AC-4: The dashboard component template contains exactly one `<app-stats-widget>` element.
- AC-5: The rendered widget contains a stat with the visible label text `Active users` and an accompanying numeric value. (§3)
- AC-6: The rendered widget contains a stat with the visible label text `Open tickets` and an accompanying numeric value. (§3)
- AC-7: The rendered widget contains a stat with the visible label text `Deploys today` and an accompanying numeric value. (§3)
- AC-8: All stat values are rendered via Angular template binding (interpolation or property binding), with no use of `innerHTML` or `bypassSecurityTrust*`. (§2)
- AC-9: The `StatsWidget` component does not inject `HttpClient` and issues zero HTTP requests when rendered.
- AC-10: No files under the login page's directory are modified by this change. (§5)

## Applicable constitution clauses
§2 (Validate and encode all user input), §3 (Accessibility is not optional), §5 (Keep the demo stub honest)

## Out of scope
- No backend/API calls — stat values are hardcoded static demo values.
- No changes to the login page or the login stub's behavior.
- No new routes in `app.routes.ts`; the widget renders inside the existing dashboard.
- No live/refreshing data, polling, or real-time updates (inferred).
- No user configuration of which stats are shown (inferred).
- No authentication or visibility-gating logic beyond what the dashboard already has (inferred).

