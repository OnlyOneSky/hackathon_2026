---
story: hackdemo#40
spec_version: 1
generated: 2026-07-10T03:26:14Z
---
# Feature: Dashboard sign-out link

## Summary
（審查決議：純導航即可；連結文字 Sign out；放置位置不拘。）
Add a "Sign out" link to the dashboard for signed-in users. Activating the link navigates the user back to the login page at `/login`. This is navigation only — consistent with the demo's stubbed login flow, no session or token state is created, read, or cleared.

## Acceptance criteria
- AC-1: When the dashboard page renders, it contains exactly one interactive element with the visible text "Sign out". (§3)
- AC-2: The "Sign out" element is a native `<a>` or `<button>` element, not a click handler on a non-interactive element such as `<div>` or `<span>`. (§3)
- AC-3: Pressing the Tab key while on the dashboard moves keyboard focus to the "Sign out" element. (§3)
- AC-4: Clicking the "Sign out" element navigates the browser to the `/login` route. (§4)
- AC-5: Activating the focused "Sign out" element with the Enter key navigates the browser to the `/login` route. (§3, §4)
- AC-6: The navigation target `/login` is a route registered in `app.routes.ts` that resolves to an existing component. (§4)
- AC-7: Activating "Sign out" does not write, modify, or delete any cookie, `localStorage` entry, or `sessionStorage` entry. (§5)

## Applicable constitution clauses
§3 (Accessibility is not optional), §4 (No dead routes), §5 (Keep the demo stub honest)

## Out of scope
- Session/token logic of any kind — no auth state is created, invalidated, or checked (per story and §5)
- Any change to the stats widget (per story)
- Changes to the login page/component itself
- Backend or API calls triggered by sign-out
- Confirmation dialog before signing out

