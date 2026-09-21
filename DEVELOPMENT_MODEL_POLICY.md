# Codex terminal model policy

This policy governs development of Veridex in the Codex terminal. It is separate
from model routing inside the Veridex chat application.

At the start of a development task, Codex must visibly state the configured
model and reasoning level, the recommended route, the phase, the reason, and
whether the user must switch. Repeat this only when the required route changes
or a mismatch appears. Codex pauses when the route does not match and must
never claim that it changed the host model itself.

| Development phase | Required terminal model | Reasoning |
| --- | --- | --- |
| Planning and architecture | `gpt-5.6-sol` | high |
| Coding, review, and diagnosis | `gpt-5.6-sol` | high |
| Standalone, long, or batched execution of completed tests | `gpt-5.6-luna` | low |
| Failed or ambiguous test diagnosis | `gpt-5.6-sol` | high |
| Final acceptance, commit, and release | `gpt-5.6-sol` | high |

A narrow deterministic test may run on the active Sol/high development route
when a separate handoff would cost more than the test. Use Luna/low for
standalone, long, or full-suite routine execution, preferably as a bounded agent
without conversation history and with a counts/errors-only result. Any failed,
flaky, ambiguous, or unexpected routine test requires returning to Sol/high
before inspecting the failure or changing code.
