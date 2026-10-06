---
name: handoff
description: >
  Copilot /handoff. Compose and store a context-handoff baton. Does not launch
  a successor unless this is a context-pressure path with work remaining.
argument-hint: "[title]"
user-invocable: true
---

# /handoff

Follow `skills/context-handoff/SKILL.md`. Collect facts, compose the template,
`save_handoff_prompt`. Print the seed. Launch only via `/handoff-continue` or
when context pressure plus remaining work requires `trigger_handoff` /
`continue_handoff` immediately.
