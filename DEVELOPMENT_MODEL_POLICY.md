# Codex terminal model policy

This policy governs development of Veridex in the Codex terminal. It is separate
from model routing inside the Veridex chat application.

Before entering a development phase, Codex must visibly state the configured
model and reasoning level, the recommended route, the phase, the reason, and
whether the user must switch. Codex pauses when the route does not match and
must never claim that it changed the host model itself.

| Development phase | Required terminal model | Reasoning |
| --- | --- | --- |
| Planning and architecture | `gpt-5.6-sol` | high |
| Coding, review, and diagnosis | `gpt-5.6-sol` | high |
| Routine execution of completed tests | `gpt-5.6-luna` | low |
| Failed or ambiguous test diagnosis | `gpt-5.6-sol` | high |
| Final acceptance, commit, and release | `gpt-5.6-sol` | high |

Any failed, flaky, ambiguous, or unexpected routine test requires returning to
Sol/high before inspecting the failure or changing code.
