# Changelog

## 1.1.0 - 2026-10-16

- Added an owner- and conversation-scoped, in-process memory-confirmation candidate.
- Added `himeko_memory_propose` for one-at-a-time suggestions about stable preferences,
  long-term goals, agreements, and corrections; it can only persist after a later explicit
  affirmative reply from the same private conversation.
- Tightened natural-language direct-save recognition so negations and quoted mentions do not
  authorize a write.

## 1.0.0 - 2026-10-06

- First public-release candidate with an AstrBot visual configuration schema.
- Added owner-scoped explicit memory, one-shot reminders, and confirmed local attachment Q&A.
- Removed personal profile, knowledge-base, fixed-path, deployment, and cloud-operation dependencies.
- Added Chinese-first and English documentation, privacy guidance, tests, and release audit tooling.
