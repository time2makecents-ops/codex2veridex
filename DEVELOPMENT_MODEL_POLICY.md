# Codex terminal model policy

This policy governs development of Veridex in the Codex terminal. It is separate
from model routing inside the Veridex chat application.

At the start of a development task, Codex must visibly state the configured
model and reasoning level, the recommended route, the phase, the reason, and
whether the user must switch. Repeat this only when the required route changes
or a mismatch appears. Codex pauses when the route does not match and must
never claim that it changed the host model itself.

Resolve the configured terminal route before declaring a mismatch. Prefer the
exact launcher evidence in `VERIDEX_CODEX_CONFIGURED_MODEL` and
`VERIDEX_CODEX_CONFIGURED_REASONING`; otherwise inspect explicit model/reasoning
arguments on the current Codex process, then the top-level `model` and
`model_reasoning_effort` in the active Codex `config.toml`. A generic product or
model-family label such as `Codex` or `GPT-5` is not evidence that contradicts a
more precise configured route. If exact runtime metadata is unavailable and the
user confirms the active route, treat that confirmation as the configured route
for the current task. Pause only for a precise conflicting route; missing generic
identity metadata alone is not a mismatch.

| Development phase | Required terminal model | Reasoning |
| --- | --- | --- |
| Routine documentation-only edits from established facts | `gpt-6-luna` | low |
| Planning and architecture | `gpt-6.1-sol` | high |
| Coding, review, and diagnosis | `gpt-6.1-sol` | high |
| Standalone, long, or batched execution of completed tests | `gpt-6-luna` | low |
| Failed or ambiguous test diagnosis | `gpt-6.1-sol` | high |
| Final acceptance, commit, and release | `gpt-6.1-sol` | high |

For routine documentation work, minimize total token use while preserving
accuracy. Use Luna/low for wording, formatting, links, and recording supplied
decisions or observed verification in existing docs, issue logs, and handoffs.
Read only the relevant sections, reuse evidence already in the conversation,
and check the changed text and diff without running application tests unless
the edit affects something executable. Model choice alone does not guarantee
fewer tokens; context size, reasoning, output length, and repeated work also
affect usage.

Documentation-only edits and their focused review may stay on Luna/low through
completion. Escalate to Sol/high when the task requires diagnosis, architecture,
new technical decisions, resolving conflicting evidence, or changes to code,
configuration, or executable commands. Designing or changing this model policy
uses Sol/high; recording an already-approved policy decision may use Luna/low.
Commit and release actions still use Sol/high and require explicit authorization.

A small documentation follow-up may finish on an already-active Sol/high route
when switching models or starting an agent would add more context and work than
the edit. State that exception briefly; do not create an agent just to edit a
few lines. For a standalone routine documentation task, request Luna/low if the
host cannot select it directly, and never claim to have changed the host model.

A narrow deterministic test may run on the active Sol/high development route
when a separate handoff would cost more than the test. Use Luna/low for
standalone, long, or full-suite routine execution, preferably as a bounded agent
without conversation history and with a counts/errors-only result. Any failed,
flaky, ambiguous, or unexpected routine test requires returning to Sol/high
before inspecting the failure or changing code.
