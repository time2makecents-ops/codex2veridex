# OpenAI developer toolkit review

Reviewed 2026-11-04 using official OpenAI documentation. Scope: useful templates,
debugging, prompts and free resources for website work and Veridex. These are
recommendations; public documentation does not establish this account's access
or credits. No account sign-in, API request, dependency install or billing change
was performed for this review.

Project constraint: **zero OpenAI API-credit budget**. Prioritize public
documentation, prompt examples and read-only Docs MCP. Credit-consuming agent
examples and model-based evaluations are outside this toolkit's scope.

## Selected for our workflow

Use the existing frontend/browser skills, the installed local quality tools,
OpenAI frontend/prompting guidance, and the regression-test method illustrated
by the agent improvement example. Docs MCP is the next selected connection to
configure; it remains unconfigured and untested. Agents SDK/tracing and Promptfoo
are reference material for later feature-specific decisions.

The portable selection and installed/pending status live in the canonical
[website resources guide](https://github.com/time2makecents-ops/codex-personal-setup/blob/main/WEBSITE_RESOURCES.md).

## Recommended resources

| Resource | What it gives us | Recommendation and cost boundary |
| --- | --- | --- |
| [Docs MCP](https://developers.openai.com/learn/docs-mcp) | Read-only documentation search and page retrieval directly inside Codex. The public server does not execute OpenAI API requests. | Best immediate connection to add. Public documentation access; inference used by the coding agent remains under that agent's existing plan. Not configured or protocol-tested in this review. |
| [Frontend prompt instructions](https://developers.openai.com/api/docs/guides/frontend-prompt) | A practical UI-quality prompt that emphasizes consistency with the existing application. | Adapt relevant instructions to our existing frontend skill and Veridex's vanilla stack. Public reference; no separate API call needed to read it. The example targets GPT-5.5, so applying it to another model requires testing. |
| [Prompt engineering](https://developers.openai.com/api/docs/guides/prompt-engineering) | Clear instruction/input separation, examples and prompt regression checks. Current guidance keeps production prompts in application code. | Keep reviewed prompts beside the feature they support, versioned and tested. API generation remains metered even when example code is publicly available. |
| [Agents SDK](https://developers.openai.com/api/docs/guides/agents/sdk) | Python/TypeScript agent definitions, tool use, handoffs, state, and human-review boundaries. | Use for a specific new agent workflow when needed. Avoid replacing Veridex's governed request flow as part of a toolkit setup. SDK examples are available publicly; model/tool execution needs eligible access and credits/payment. |
| [SDK tracing](https://developers.openai.com/api/docs/guides/agents/integrations-observability) | Shows model calls, tools, outputs, handoffs and guardrails. Server-side tracing is normally enabled by default. | Useful for diagnosing wrong tools or routing in an SDK-based feature. It does not automatically instrument existing Veridex code. Trace contents must follow the project's privacy and governance rules. Account/dashboard access remains unverified. |
| [Agent improvement loop](https://developers.openai.com/cookbook/examples/agents_sdk/agent_improvement_loop) | Example combining traces, feedback, generated Promptfoo tests and an implementation handoff to Codex. | Reuse the process: reproduce a failure, preserve a synthetic example, define expected behavior, fix, and rerun checks. The full notebook requires dependencies and API credentials; it is not a free inference service. |
| [Promptfoo migration guide](https://developers.openai.com/cookbook/examples/evaluation/moving-from-openai-evals-to-promptfoo) | OpenAI's recommended route from hosted Evals to portable local/CI evaluation configuration. | Consider when we have repeated prompt failures that need a dataset. Evaluation software and model execution have separate cost boundaries; model-based generation/judging can consume credits. Not installed in this review. |

The [agents resource directory](https://developers.openai.com/learn/agents) also
links starter apps and support-agent examples. Review each sample's current
dependencies and migration status before adapting it. Some directory examples
still refer to products being retired.

## Products to avoid adopting as new dependencies

The [official deprecation schedule](https://developers.openai.com/api/docs/deprecations)
sets **November 30, 2026** for Agent Builder, reusable prompt objects/`v1/prompts`,
and the Evals dashboard/API to shut down. Existing hosted evals became read-only
on October 31. The [dataset-backed prompt optimizer](https://developers.openai.com/api/docs/guides/prompt-optimizer)
is part of the Evals transition. ChatKit remains available, but an old
Agent Builder-backed starter needs migration review. Prefer code-managed
prompts, SDK examples and portable evaluation files for new work.

## What the free account establishes

Public guides/examples are useful immediately. Signing up does not establish
unlimited free model or tool execution: [API pricing](https://developers.openai.com/api/docs/pricing)
lists metered usage. Account-specific limits and dashboard access were not
inspected. One explicitly free endpoint is [moderation](https://developers.openai.com/api/docs/guides/moderation),
which classifies harmful content; it is not a general design or debugging model.

If the user also has an eligible paid ChatGPT Pro or Business subscription,
[subscription API credits](https://developers.openai.com/api/docs/guides/chatgpt-api-credits)
may be claimable through an organization they own. That is a separate benefit
with eligibility and activation requirements, not a consequence of free API
enrollment. No eligibility is assumed here.

## Suggested order for our projects

1. Connect and verify Docs MCP when implementing the selected toolkit.
2. Adapt compact website-design and debugging prompts to existing skills and
   project conventions, preserving the shared setup repository as policy authority.
3. Turn observed failures into representative regression cases using existing
   tests first; add a prompt evaluation tool when the task calls for it.
4. Add SDK/tracing only for a defined agent feature, with explicit provider-use
   scope and the application's existing governance/confirmation paths.

Research-only verification: supporting official pages were opened and reviewed;
no sample workflow or API integration was executed. No application code changed,
so no application tests were needed. Source publication follows separate review
and explicit authorization; repository history records published revisions.
