# Google tools for free website design and development

Research snapshot: 2026-11-04. Primary sources only; quotas and product availability can change.


## Selected project resources

Use the existing frontend/browser workflows, installed local quality tools,
Google accessibility/LCP skills and public OpenAI prompting references. OpenAI
Docs MCP is configured and its standalone search/fetch checks passed; the
running Codex client needs a configuration reload. DevTools MCP still needs
connection/browser validation. The toolkit has a zero OpenAI API-credit budget.
See [OpenAI review](OPENAI_TOOLKIT_REVIEW.md) and the canonical setup repository's
[website resources guide](https://github.com/time2makecents-ops/codex-personal-setup/blob/main/WEBSITE_RESOURCES.md).

## Google Developer Program

- Standard membership is no-cost and offers developer learning/profile features and Gemini assistance in Google developer documentation/tools. It does not itself provide paid API usage or Cloud billing. [Benefits FAQ](https://developers.google.com/profile/help/benefits?hl=en)
- Premium benefits are distinct from Standard membership. Google says personal-account premium benefits are being consolidated into Google AI Pro/Ultra; Workspace accounts retain Premium. Any credits, vouchers, or increased product quota are tied to the applicable paid subscription and terms, not mere enrollment. [Benefits FAQ](https://developers.google.com/profile/help/benefits?hl=en)
- Firebase Studio documentation describes more workspaces for Standard membership but states new workspace creation has been disabled since June 22, 2026; this makes the advertised workspace counts historical for new users. [Firebase Studio pricing and limits](https://firebase.google.com/docs/studio/pricing)

## Design and coding tools

- **Stitch** is Google Labs' AI design canvas for generating and iterating high-fidelity interfaces from natural language, building interactive prototypes, and importing/exporting design rules through `DESIGN.md`. Google describes it as experimental; the cited announcement does not promise unlimited free usage or publish quota/billing terms. [Google Labs announcement](https://blog.google/innovation-and-ai/models-and-research/google-labs/stitch-ai-ui-design/)
- **Gemini CLI** status changed: Google's official repository says that since June 18, 2026, the free individual and Google AI Pro/Ultra routes moved to Antigravity CLI. Gemini CLI remains open source, but its supported access is enterprise Code Assist licenses or paid Gemini / Agent Platform API keys. A historical quota/pricing page may still show individual free quotas, so use the current repository status and transition announcement. [Current Gemini CLI README](https://github.com/google-gemini/gemini-cli) · [transition notice](https://github.com/google-gemini/gemini-cli/discussions/27274)
- **Chrome DevTools MCP** is an open-source MCP server/CLI for coding agents to inspect and control Chrome, capture screenshots/traces, debug network/console, and analyze performance. It requires Node.js LTS, npm, and current Chrome; the software is free, but agent/model access is separate. It is technically usable from Windows/Codex if Codex supports configuring MCP servers and Node/npm/Chrome are already available; no installation was performed here. [Official GitHub repository](https://github.com/ChromeDevTools/chrome-devtools-mcp)
- **Google AI Studio** offers free access to eligible Gemini API models within model-specific rate limits. Paid tier requires linking Cloud Billing and, where prompted, prepaying at least $5; paid usage is token-metered. Free-tier terms state prompts/responses may be used to improve Google products, unlike paid tier. Direct Build mode deployment has a separate Google Cloud Starter Tier: up to two full-stack apps without a Cloud project or billing account. [Gemini API billing and tiers](https://ai.google.dev/gemini-api/docs/billing) · [pricing](https://ai.google.dev/gemini-api/docs/pricing)

## Firebase Studio and hosting

- Firebase Studio access was no-cost, but Google disabled new workspace creation on June 22, 2026. Existing workspaces may remain accessible; the page's former quotas are not usable to claim new access. Some integrations, including App Hosting, require Cloud Billing. Linking billing upgrades the project to Blaze; usage beyond no-cost allowances can incur charges and Gemini Developer API usage becomes paid tier. [Studio limits and billing](https://firebase.google.com/docs/studio/pricing)
- Firebase Hosting static sites include CDN, SSL, and custom-domain support. Current documented no-cost quotas: 10 GB hosting storage and 10 GB/month data transfer. On Spark, exceeding storage prevents new deploys; exceeding transfer can disable sites until the next month (after a grace period). Blaze allows paid overages. Dynamic Cloud Functions/Cloud Run integration requires a billing account even where usage has a free quota. [Hosting quotas](https://firebase.google.com/docs/hosting/usage-quotas-pricing) · [dynamic hosting billing](https://firebase.google.com/docs/hosting/serverless-overview)
- Firebase Spark is a no-cost plan with no payment method required for eligible products; Blaze is pay-as-you-go and requires billing setup. Do not interpret Google Developer Program membership or Cloud promotional credit as a guarantee that an integration is free. [Firebase pricing](https://firebase.google.com/pricing)

## Windows/Codex relevance

For local Windows implementation and QA, Chrome DevTools MCP is the directly relevant free tool, subject to prerequisites and Codex MCP support. Stitch is a hosted design/prototyping aid; AI Studio is a hosted model playground/build/deploy path with free-tier and billing boundaries. Firebase Hosting can serve static sites without a billing account within Spark limits. Firebase Studio is not currently a viable new-workspace starting point per Google's June 2026 notice. No sign-ins, installs, account actions, deployments, or billing changes were made for this research.
