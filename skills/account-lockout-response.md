---
name: account-lockout-response
description: Use when an AD account is locked out (Event 4740) — how to triage the cause and what to tell IT. Read-only advice.
---

When an account locks out:

1. Pull the user's recent login failures (get_login_fails) and any lockout history
   (get_locked_accounts) to see if this is a one-off or repeated.
2. Decide benign vs attack:
   - A handful of fails from the user's own host/IP → likely a fat-finger or a stale
     cached password (phone/mapped drive). Benign.
   - Many fails in a short window, especially from one unexpected IP → possible
     brute-force; treat as security.
3. Tell IT concretely:
   - Benign: ask the user to update the cached credential, then (with IT confirmation)
     unlock. Do NOT unlock automatically — Phase 1 is read-only.
   - Suspicious: keep it locked, note the source IP, and watch for more attempts.
4. Never expose passwords. Report who / which host / how many / from where.
