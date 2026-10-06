---
name: retry-handoff-cutover
description: >
  Copilot tool retry_handoff_cutover. Retry the existing saved native handoff
  identity without creating another goal or receiver.
user-invocable: true
---

# retry_handoff_cutover

Reuse the in-session `HANDOFF_SEED` / token. Do not call `save_handoff_prompt`
again. Do not spawn a second successor if one already exists.

If no seed is in this session, recover the existing baton with
`grok-handoff.sh facts` / `/consume-handoff` instead of creating a new one.

Otherwise follow `continue-handoff` with that same seed.
