# Agent Board product research and naming shortlist

As of 26 Sep 2026. This compares public descriptions and the Agent Board source at commit `4540e04`. Competitor features below are claims in their documentation, not independently tested behavior. Names are preliminary collision screens, not trademark clearance.

## What the two AgentPulse products do

| Product | Evidence from source | What Agent Board can learn |
| --- | --- | --- |
| [Open-source AgentPulse](https://github.com/jstuart0/agentpulse) | Its README describes live Claude Code/Codex observability, a per-session chat and tool timeline, full-text search, an operator inbox for approvals and stuck sessions, a project digest, and optional launch/control. AI Labs and automated watchers are explicitly experimental and human-in-the-loop by default. | Make the next action and recent context easier to see. Keep control actions separate from observation until users need them. |
| [AvePoint AgentPulse](https://learn.avepoint.com/platform-overview-and-key-features/command-centers/agentpulse/about-agentpulse.html) | Its documentation describes organization-wide activity oversight, usage trends, anomalies, and performance. Its [product blog](https://www.avepoint.com/blog/manage/agentpulse-governance-ai-agents) describes discovery, creator/last-used/data-source metadata, ownership, renewal, and archival. | Add useful context to workstreams: purpose, last activity, source, and explicit owner/next step if the pilot becomes collaborative. Do not copy an enterprise governance model into a personal Mac tool by default. |

## Current Agent Board boundary

The current Mac app reads local Claude Code/Codex session logs, groups linked sessions into workstreams, classifies active/finished/stuck states, offers manual stars/choices/completion, and shows advisory completion suggestions. It has a menu bar view and a board window. It does not provide full-text transcript search, a per-workstream event timeline, session launch/control, cross-machine sync, or an organization-wide inventory. Source: `README.md`, `agent_board.py`, and `agent_board_workstreams.py` at `4540e04`.

## Recommended sequence

| Priority | Change to test | User impact | Effort | Risk / guardrail |
| --- | --- | --- | --- | --- |
| 1 | Add an action inbox combining Asking you, Check me, and Your turn with the reason, last event time, and one clear next action. | High: faster decision about which agent needs attention. | Medium | Keep Done manual; suggestions remain advisory. |
| 1 | Add source freshness and service health indicators; measure status response time and missing-session reports during the colleague pilot. | High: helps explain wrong or slow status before adding features. | Small–medium | Do not call a session stuck solely because it is quiet. |
| 2 | Add a bounded workstream timeline and search across titles, recent prompts, and notes, with links back to the original session. | High for resuming work after a break. | Medium–high | Keep all indexing local; measure memory and scan cost. |
| 3 | Add an optional project digest: active, waiting, and recently finished workstreams plus explicit next steps. | Medium: useful for daily or weekly review. | Medium | Do not equate idle with complete. |
| Later | Agent launch/control, remote sync, and team governance. | Unproven for this pilot. | High | Requires stronger permissions, privacy design, and evidence of demand. |

This is a product hypothesis and sequence, not an implementation commitment. Validate the first two rows with colleague install and use feedback before broadening scope.

## Name shortlist

`AgentPulse` is already used by the two products above, including one covering the same Claude Code/Codex monitoring use case, so it is a poor rename choice.

| Name | Positioning | Quick screen on 26 Sep 2026 | Assessment |
| --- | --- | --- | --- |
| **Turnlume** | Bring every agent turn to light. Energetic and distinctive. | No exact public GitHub repository, npm/PyPI package, or Mac App Store app found; `turnlume.com` returned no registration record from Verisign RDAP. Broad web search found no clear software product. | **Recommended first choice** if pronunciation feels natural. |
| **HandoffNest** | A home for unfinished work and clean handoffs. | No exact public GitHub repository, npm/PyPI package, or Mac App Store app found; `handoffnest.com` returned no registration record from Verisign RDAP. Broad web search found no clear exact-match product. | Clearest job-to-be-done, but less energetic. |
| **TurnCove** | A calm place to watch and return to agent turns. | No exact public GitHub repository, npm/PyPI package, or Mac App Store app found; `turncove.com` returned no registration record from Verisign RDAP. Broad web search found no clear exact-match product. | Friendly and short, but less explicit about agents. |

Screening used Brave Search, GitHub repository search, npm, PyPI, Apple's Mac App Store search API, and Verisign `.com` RDAP. Search indexes and registrations change. Before a public rename, check trademarks in intended markets and the final domain/handle at the time of launch. No code or app branding was renamed in this research step.
