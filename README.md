# Codex + Veridex standalone

This repository is a self-contained, single-user Veridex chat application that
uses the locally authenticated Codex CLI. It does not require an OpenAI API key
and does not read from or write to `C:\Office-App`.

## What is included

- A local web UI with no login screen.
- Automatic task routing to Codex models and reasoning levels.
- A visible status strip whenever the model is selected or changed.
- Multiple workspaces and sessions under one local account.
- Every new workspace and session starts in the Lobby with the Receptionist.
- A visible room selector and explicit natural-language room navigation.
- An always-visible Navigator monitor backed by deterministic hard gates.
- Durable NDJSON chat logs stored beneath `data/workspaces/`.
- Session-scoped file attachments saved beside each session transcript.
- Generated images verified, ledgered, previewed, and reported with their exact local path and checksum.
- A full Art Studio with the existing Codex image route, optional free-provider generation, reference editing, local finishing tools, explicit projects, and image lineage.
- A Museum led by Leo for photo-led identification, evidence-linked value research, frame analysis, and conservative thrift-buy guidance.
- An HR Resume Studio with saved career profiles, job tailoring, ATS review, private/federal templates, and verified DOCX/PDF/text exports.
- A Codex MCP bridge for governed requests from an interactive Codex session.
- Independent start, stop, restart, and status commands.

No workspace data, chat logs, secrets, or user accounts are copied from another
application. The first launch creates a fresh local account and workspace.

## Run

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\codex2veridex\veridex.ps1 start
```

The browser opens at <http://127.0.0.1:8765>. Other commands are:

```powershell
.\veridex.ps1 status
.\veridex.ps1 restart
.\veridex.ps1 stop
.\veridex.ps1 tailscale
.\veridex.ps1 gmail-connect
.\veridex.ps1 gmail-status
```

`tailscale` keeps the backend on localhost, exposes it only through the computer's
private Tailscale HTTPS address, and prints a one-time phone pairing URL. The phone
stores an HTTP-only pairing cookie; unpaired remote devices cannot use the UI or APIs.

## Museum

Enter **Museum** to work with Leo. Take or attach item photos, select
them, then choose **Quick research** for in-store triage or **Deep research** for a
broader evidence pass. Useful views include the complete front, signature or maker's
mark, back and labels, frame joints, surface texture, and any damage.

Google Lens image uploads require confirmation for each research run unless you say
`Leo, start shopping mode`. Shopping mode is session- and room-scoped, remains visibly
active, and ends when you say `Leo, end shopping mode`, leave the room, or stop using
it for four hours. Veridex keeps the original locally and sends a resized copy with
EXIF metadata removed. Every completed item is automatically saved as a revisioned
Antiques case.

Leo separates observations, sourced matches, and inference. Values use sold evidence
when available and show the lower of the editable profit calculation or the default
25% conservative-value acquisition cap. Results are research guidance, not certified
authentication or professional appraisal.

## Voice controls

Every assistant reply has a **Read** button that toggles to **Stop** while the
browser reads it aloud. Select **Read automatically** to speak only new replies;
the checkbox preference is remembered in that browser without replaying old
transcript history after reload.

The microphone button beside the message box dictates into the current draft.
Chrome or Edge will request microphone permission the first time it is used.
Veridex stores only the resulting text in the transcript and does not save the
microphone audio.

Veridex starts with full computer access so Codex can use normal local shell
tools across the computer. The `-FullAccess` switch remains accepted for
backward compatibility:

```powershell
.\veridex.ps1 restart -FullAccess
```

The page always displays either `Read-only computer access` or
`Full computer access` beneath the current room. Full access uses Codex's
documented `danger-full-access` sandbox with approvals set to `never`. This lets
Codex search and work with local files. To opt into read-only mode for a run,
use `.\veridex.ps1 restart -ReadOnly`; the next normal start or restart returns
to full access.

Requirements: Python 3 and a working `codex` command authenticated through the
Codex desktop app/CLI. Install the document environment once after cloning or
pulling a version that changes `requirements.txt`:

```powershell
.\scripts\setup.ps1
```

The launcher automatically prefers `.venv\Scripts\python.exe` when present.
Broad, multi-source research requests use the deep-search route and may run for
up to ten minutes before the server reports a timeout.

## Storage

The application creates this local structure, which Git ignores:

```text
data/
  account.json
  workspaces/
    ws_.../
      workspace.json
      governance_state.json
      governance_incidents.ndjson
      artifact_ledger.ndjson
      governance_memos.ndjson
      sessions/
        sess_.../
          session.json
          transcript.ndjson
          files.json
          files/
          generated_staging/
```

Each assistant transcript entry records the provider, exact model, reasoning
effort, and task class used for that response.

Use the `+` button beside the composer to add files. Uploaded files are copied
into the active session's `files/` directory and selected for the next message.
They remain available in that session and can be selected again later.
Uploaded files enter the workspace's numbered artifact ledger before analysis.

While Veridex is working, the Send button becomes a square Stop control in the
same composer position. Stop sends the active request ID to the server, cancels
the running Google/Node or Codex process, and saves `Stopped by you.` in the
session transcript. It does not stop the Veridex server or affect another
session.

For image-generation requests, Veridex assigns a request-specific staging
directory before Codex runs. Codex must copy each final image there. The server
then independently validates the image signature and nonzero size, copies it
into the session's canonical `files/` directory, computes SHA-256, creates a
numbered artifact-ledger entry, and records the exact canonical path in the
assistant transcript. The completion is blocked if any of those checks fail.
Verified images appear directly in the chat with an openable preview.

Generated documents use the same governed staging and ledger boundary. PDF,
DOCX, XLSX, CSV, TXT, and Markdown files are checked by signature, archive
structure, or readable content before they can support a file-creation claim.

## Art Department Studio

Enter **Art Department** and select **Art Studio**. Its four work areas provide:

- automatic generation through the same authenticated Codex image tools used by Art Department chat, with no separate API key;
- Cloudflare Workers AI generation through Fast Draft, Reference Edit, Text/Poster, and Quality modes;
- automatic fallback to Pollinations `flux` or `zimage` when an eligible Cloudflare request hits quota or a transient provider failure;
- one-to-four variants, reusable seeds, negative prompts, style presets, and common aspect ratios;
- reference-based edits using up to four verified Art Department images;
- local resizing, upscaling, cropping, captions, collages, conversion, compression, and CPU background removal;
- optional visual critique, explicit project versions, downloads, and attach-to-chat actions.

The provider registry is strictly allowlisted. The Codex route uses the existing
ChatGPT-authenticated Codex session and does not enable API billing. It never
selects a Pollinations paid-only model. Keep the Cloudflare account on **Workers Free** and use a
Pollinations account without purchased Pollen to preserve the intended
zero-cost optional-provider boundary. Add those optional credentials to ignored `.env.local`:

```text
VERIDEX_CLOUDFLARE_ACCOUNT_ID=...
VERIDEX_CLOUDFLARE_API_TOKEN=...
VERIDEX_POLLINATIONS_API_KEY=...
```

Cloudflare Free stops after its daily allocation; Veridex never enables billing.
When the optional hosted providers are unavailable, Auto uses Codex image tools
in Full computer access mode so the verified result can be saved, while local
Finish tools continue to work. The first background-removal request
downloads its open model and can take longer on this computer. Every result is a
new verified artifact; originals are never overwritten.

## HR Resume Studio

Enter **HR Department** and select **Resume Studio**. The guided workflow can:

- build or explicitly save a reusable career profile;
- import readable PDF, DOCX, TXT, or Markdown resumes already attached to chat;
- paste or safely fetch a public HTTPS job posting;
- compare verified experience with job keywords without presenting a fictional universal ATS score;
- generate private-sector or federal resumes, cover letters, LinkedIn copy,
  recruiter email, and interview talking points;
- block final export while suggested facts or metrics remain unconfirmed; and
- create verified DOCX, PDF, and plain-text files in the HR Department Files library.

Career profiles and application projects persist only after their separate
**Save career profile** or **Save project** actions. Recruiter emails can be
opened in Nancy's composer and retain Nancy's normal final-send confirmation.

## Navigator governance

Navigator is active in every room. The header badge opens a panel showing the
exact rule source, snapshot version and SHA-256 hash, provenance, active gates,
and latest incident. The standalone runtime reads its rules from:

```text
C:\codex2veridex\governance\navigator_governance_v1.0.0.json
```

The snapshot is self-contained; Veridex does not read or modify `C:\Office-App`
at runtime. Attempted hard-rule breaches are blocked with a separate Navigator
message and appended to the workspace's `governance_incidents.ndjson` when an
actual attempted breach needs debugging.

Navigator's file-creation rule does not accept generic command activity as
proof. A response may say that a file was created, generated, rendered,
exported, or saved only when the same response has a verified local path,
nonzero size, SHA-256 checksum, and numbered artifact-ledger record.

Persistent preferences use a two-step governed flow: choose `persistent`, then
reply exactly `SAVE`. Veridex records the approved text in the workspace's
`governance_memos.ndjson` and reports local GOV-SAVE separately from unverified
ChatGPT product memory.

See [DEVELOPMENT_MODEL_POLICY.md](DEVELOPMENT_MODEL_POLICY.md) for the separate
personal model-switch protocol used while coding Veridex in this Codex terminal.

## Gmail for Nancy

Nancy uses a Veridex-owned Gmail OAuth connection and encrypted token store
beneath `data/integrations/`. Veridex does not read another application's token
database at runtime. Configure the OAuth client values in the ignored
`.env.local`, then connect the account once:

```powershell
.\veridex.ps1 gmail-connect
.\veridex.ps1 restart
.\veridex.ps1 gmail-status
```

The browser authorization must use the account configured by
`VERIDEX_GOOGLE_ACCOUNT`. Passwords and OAuth tokens are never written to the
repository or returned in chat responses.

## Rooms

Choose a room from the selector beneath the session title, or type an explicit
command such as `go to Art Department`. Commands such as `list rooms`, `list
room controls`, and `can you list available rooms?` return the authoritative
directory. Room navigation and directory requests are handled deterministically
by Veridex before Codex is called, and every session still has exactly one
active room.

### Governed administration

The Infrastructure Room exposes Administration for global room and program
changes. Navigator handles rule and gate proposals from the Control Room. A
proposal remains a preview until the user approves its exact catalog or policy
version. Amendments and disabling governance require a second confirmation;
the protected approval, audit, truth, and scope kernel cannot be disabled from
inside Veridex.

Applied catalogs and governance snapshots are versioned under ignored
`data/system/administration/` storage. Approved program changes are restricted
to the proposal's repository paths, must pass verification, and never restart
Veridex automatically.

## Model routing

| Task | Default model | Reasoning |
| --- | --- | --- |
| Coding, debugging | `gpt-5.6-sol` | high |
| Architecture, planning | `gpt-5.6-sol` | high |
| Image/video reasoning | `gpt-5.6-sol` | high |
| Resume drafting and refinement | `gpt-5.6-sol` | high |
| High-stakes topics | `gpt-5.6-sol` | xhigh |
| Explicit Google/deep search | `gpt-5.6-sol` | high |
| General search and chat | `gpt-5.6-terra` | medium |
| UI checks and simple testing | `gpt-5.6-luna` | low |
| Greetings and trivial requests | `gpt-5.6-luna` | low |
| Room navigation and room directory | deterministic Veridex router | none |

Routing is automatic. Prompt text cannot directly select an arbitrary model.
Overrides are available in `.env.example`.

## Dedicated Google search profile

Explicit requests such as `check Google for ...`, `search Google for ...`, or
`use a Google search ...` use a real local Chrome window with a dedicated
repository-local browser profile. They do not silently fall back to a generic
web-search provider.

Set up the profile once:

```powershell
.\veridex.ps1 google-profile
```

In the Chrome window that opens, manually sign in as the account configured by
`VERIDEX_GOOGLE_ACCOUNT`. The password is never stored by Veridex; Chrome owns
the resulting browser session. Check readiness with:

```powershell
.\veridex.ps1 google-status
```

The default profile directory is
`C:\codex2veridex\data\browser_profiles\veridex_google`, which is covered by
the repository's ignored `data/` directory. It is separate from ordinary Chrome
profiles and is not copied to GitHub. Search evidence records the provider,
query, timestamp, configured account, and result count in the chat transcript.
Navigator blocks an explicit-Google response if the dedicated browser evidence
is absent or if a generic search provider was substituted. For event searches,
the current local date is injected into the governed prompt and past dates are
blocked from an `upcoming` section. When only that date classification fails,
Navigator visibly performs one evidence-preserving correction and delivers the
repaired answer. Past events remain valid results when the user asks generally
about shows. If the correction still cannot classify dates safely, the completed
Google evidence is returned as unclassified excerpts instead of suppressing the
search; provider and evidence gates remain enforced.

Google follow-ups inherit the most recent explicit Google subject within the
active session. Phrases such as `search again`, `give me the results`, or a
closely related request about the same named artist reuse that subject, so the
user does not need to repeat `Google` on every turn. The resolved query—not the
follow-up filler words—is recorded in transcript evidence.

Explicit Google searches also inspect up to three top result pages through the
same dedicated Chrome profile. Veridex records whether each page opened fully,
was limited by login/access controls, or failed. Sol/high synthesizes the Google
page, opened-source text, and URLs; it must prefer opened source text over a
conflicting snippet and label snippet-only claims. This uses the existing Codex
desktop authentication and does not add an API-key charge.

## Codex MCP bridge

The included config snippet points Codex at `veridex_mcp.py`. Calling
`veridex_activate` starts this standalone server when needed and automatically
uses the default local session if no session ID is configured.

## Test

```powershell
.venv\Scripts\python.exe -m unittest discover -v
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the governance and persistence
boundaries.
