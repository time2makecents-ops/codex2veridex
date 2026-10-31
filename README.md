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
- Workspace-scoped eBay seller tools for inventory, listings, orders, finances, and confirmation-gated marketplace actions.
- An HR Resume Studio with saved career profiles, job tailoring, ATS review, private/federal templates, and verified DOCX/PDF/text exports.
- A Codex MCP bridge for governed requests from an interactive Codex session.
- Independent start, stop, restart, and status commands.

No workspace data, chat logs, secrets, or user accounts are copied from another
application. The first launch creates a fresh local account and workspace.

## Run

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\codex2veridex\veridex.ps1 start
```

The browser opens at <http://127.0.0.1:8765> in the repository-local Veridex
Chrome profile. The app launcher and the Google, Gmail, Facebook, and Instagram
bridges reuse that one browser and loopback debugging port instead of opening
separate account windows. Configure it with `VERIDEX_BROWSER_PROFILE_DIR`,
`VERIDEX_BROWSER_PROFILE_DIRECTORY`, and `VERIDEX_BROWSER_DEBUG_PORT`; its data
stays beneath ignored runtime storage and is never pushed to GitHub. Other
commands are:

```powershell
.\veridex.ps1 status
.\veridex.ps1 restart
.\veridex.ps1 stop
.\veridex.ps1 tailscale
.\veridex.ps1 lan
.\veridex.ps1 gmail-connect
.\veridex.ps1 gmail-status
.\veridex.ps1 instagram-profile
.\veridex.ps1 instagram-login
.\veridex.ps1 instagram-status
.\veridex.ps1 facebook-profile
.\veridex.ps1 facebook-login
.\veridex.ps1 facebook-status
```

`tailscale` keeps the backend on localhost, exposes it only through the computer's
private Tailscale HTTPS address, and prints a one-time phone pairing URL. The phone
stores an HTTP-only pairing cookie; unpaired remote devices cannot use the UI or APIs.

`lan` binds the same Veridex port to private local-network adapters and prints a
one-time phone pairing URL such as `http://192.168.x.x:8765/pair?...`. It attempts to
allow TCP 8765 only on Windows **Private** networks. Pairing remains required, but LAN
mode is plain HTTP, so use it only on a trusted home/private Wi-Fi; Tailscale remains
the recommended option away from that network. A normal `start` or `restart` returns
Veridex to loopback-only access.

## Item Intake

The phone-facing **Capture Companion** is a separate paired local-network app at
port 8775. Run `.\veridex.ps1 lan`, then open the printed `http://<PC-IP>:8775/`
address on the paired phone. It captures only a title, notes, ChatGPT/Gemini shared
links, and photos. Reference IDs and the other catalog fields are available under
**Advanced details** in the PC Item Intake workspace. **Remove from phone queue** archives an item
from that phone view without deleting its PC files or catalog record. **Delete from
PC catalog** requires typing `DELETE` and permanently removes that item and its source
folder. The normal
Veridex app remains on port 8765, including its workspace and session controls.

Open <http://127.0.0.1:8765/item-intake> on the PC, or use the paired private URL
from `veridex.ps1 tailscale` or `veridex.ps1 lan` on a phone. Create a batch, then create or select one
active item before adding photos, PDFs, chat exports, text, documents, audio, video,
or other files. Every file added while that item is active stays in its own folder
inside the batch and is also cataloged in the local SQLite database.

Both Item Intake and the phone Capture Companion offer **Camera** for a normal
rear-camera photo and **Close-up** for details such as signatures or marks. Camera
access begins only after tapping one of those controls. Close-up uses browser-exposed
camera zoom when the device supports it; otherwise the app says so and leaves you to
move closer or use the device's macro camera. Captured photos use the same local upload
route and item folder as photos chosen from the library. On a private-LAN `http://`
address where a phone browser disallows live camera access, the same buttons fall back
to the phone's native rear-camera capture flow.

On the PC, each catalog photo has a smartphone-style **Touch up** editor with Crop,
Light, Color, Detail, and AI tabs. Its live preview includes aspect presets, exposure,
brightness, highlights, shadows, saturation, warmth, contrast, definition, sharpness,
and rotation controls. The crop box can be dragged directly over the preview, with
preview zoom for close-up inspection. **Save crop**, **Auto crop**, **Auto adjust**,
**Marketplace auto touch-up**, and
**Save adjustments** run locally, keep the editor open for continued work, and save a
new derived photo, never overwriting the source. Marketplace auto touch-up uses a
conservative local exposure/color/detail pass with limited glare softening and no
generative changes.
The editor also accepts a plain-language **AI touch-up** request. Before that
option lets you explicitly select **Codex image tools** or a configured **Cloudflare
reference-edit** provider, then asks for confirmation before it sends the selected
photo and instruction. The AI result is also stored as a separate derived photo and is
labeled with its source lineage. Frequently used AI instructions can be saved as named
presets and selected or deleted from the same editor.

Item Intake does not automatically run OCR, AI analysis, GPS extraction, external
research, or marketplace actions. Shared-thread links remain local references, and the
PC inbox keeps short findings with the item record. **Export
batch** creates CSV and XLSX inventory files. **Send to Veridex** copies selected item
material plus a source-linked research brief into the current Veridex session and
ledgers those copied files. It does not begin research or create a listing.

Each item also has optional **ChatGPT** and **Gemini shared thread links**. Paste only
that item's `https://chatgpt.com/share/...` or Gemini public-share link (including
`https://g.co/gemini/share/...` and `https://share.gemini.google/...`),
then save the item. Each link is stored in the item's local record, item-folder
`item.json`, exports, and any controlled Veridex handoff brief. The PC Inbox can
explicitly preview a public shared thread and, only after review, save its visible text
and available visible images into the item; it never imports a thread automatically.
The preview also offers **Save + send to Veridex** and a shortcut to **Find eBay listing**.

## Museum

Enter **Museum** to work with Leo. Take or attach item photos, select
them, then choose **Quick research** for in-store triage or **Deep research** for a
broader evidence pass. Useful views include the complete front, signature or maker's
mark, back and labels, frame joints, surface texture, and any damage.

When one photograph contains several objects, choose **Select items**, pick one source
photo, and draw a rectangle around each object. Review, rename, move, or resize up to
12 boxes before starting the batch. Choose **Visual match only** for Google Lens leads
or **Full Leo research** for the normal Google Lens, Google, and eBay evidence flow.
Each box creates a separate Antiques case. Only the ledgered crop is sent to Google
Lens; the full source photograph remains local and is linked as case provenance.

Google Lens image uploads require confirmation for each research run unless you say
`Leo, start shopping mode`. Shopping mode is session- and room-scoped, remains visibly
active, and ends when you say `Leo, end shopping mode`, leave the room, or stop using
it for four hours. Veridex keeps the original locally and sends a resized copy with
EXIF metadata removed. Every completed item is automatically saved as a revisioned
Antiques case.

Quick research uses Lens candidates to seed the Google and eBay searches and performs
one bounded synthesis pass. If Lens does not return completed, usable evidence, the
quick run stops before broad searches and valuation, saves a limited visual record, and
reports the Lens error instead of presenting the run as completed. Deep research keeps
the separate visual-analysis pass and broader source set.

Each case includes a canonical `research_record` that preserves identity fields such as
artist or maker, title, date or period, medium, dimensions, product code, signature or
mark, and condition. It links bounded provenance and correspondence summaries to the
case's attachments, derived evidence artifacts, browser sources, and append-only price
observations. Later partial revisions retain earlier nonempty identity and evidence
instead of replacing it with an incomplete report.

Leo separates observations, sourced matches, and inference. Values use sold evidence
when available and show the lower of the editable profit calculation or the default
25% conservative-value acquisition cap. Results are research guidance, not certified
authentication or professional appraisal.

Saved Antiques cases also keep normalized price evidence. Possible repeat appearances
of the physical item are labeled separately from same-model or same-edition examples;
visually similar items are withheld from the expected-resale calculation. Sold records,
active asking prices, estimates, venue, date, and source stay distinct. Only exact-tier
sold records linked to captured source evidence can set the expected-resale range or
maximum-buy guidance. When no exact result is available, Leo asks before expanding to
similar items.

Each saved case has a background **Find prices** control. The default scope is **Exact
only**. **All likeness** is an explicit expansion that still searches and displays exact
matches first, then similar candidates in a separate section that is not used for exact
valuation. Search depth presets are Fast (90-second exact / 6-minute all-likeness),
Standard (3-minute / 12-minute), and Extended (5-minute / 20-minute). Jobs report
progress and can be canceled. Price-only rechecks do not upload the case photographs.
The same workflow is available through `antiques.price_search_start`,
`antiques.price_search_get`, and `antiques.price_search_cancel`.

### Video inventory extraction

`video_inventory.py` provides a local, review-first bridge from a table or estate-sale
video to the existing inventory spreadsheet format. It samples bounded frames, favors
sharp and stable views, removes only near-identical full-frame duplicates, and writes a
numbered contact sheet plus a provenance manifest. It does not claim that a candidate
view is an identified item; a human approves the useful views before workbook creation.

Create a new project folder for one video:

```powershell
.venv\Scripts\python.exe video_inventory.py extract `
  "C:\path\to\items.mp4" `
  "$env:USERPROFILE\Documents\Veridex\Video Inventory\items_001"
```

Create a second-stage review package that groups only similar adjacent scenes, shows
all four rotation choices, and proposes whole-region lassos:

```powershell
.venv\Scripts\python.exe video_inventory.py proposals `
  "$env:USERPROFILE\Documents\Veridex\Video Inventory\items_001\manifest.json" `
  "$env:USERPROFILE\Documents\Veridex\Video Inventory\items_001_proposals" `
  --rotate "view_011=90"
```

Rotation values are clockwise and must be `0`, `90`, `180`, or `270`. An override on
any member of a grouped scene applies to that scene; conflicting overrides are
rejected. `orientation_review.jpg` shows every option, and
`item_proposals_contact_sheet.jpg` overlays the proposed lassos. Frame-edge and weak
boundary risks are recorded in `proposal_manifest.json`. These outputs remain
unverified proposals and do not automatically create spreadsheet rows.

After checking the orientation and full-item boundaries, create a workbook from the
approved view IDs:

```powershell
.venv\Scripts\python.exe video_inventory.py workbook `
  "$env:USERPROFILE\Documents\Veridex\Video Inventory\items_001\manifest.json" `
  "$env:USERPROFILE\Documents\Veridex\Video Inventory\items_001.xlsx" `
  --crops-dir "$env:USERPROFILE\Documents\Veridex\Video Inventory\items_001_crops" `
  --select "view_001:boxed slot bank" `
  --select "view_004:glass decanter"
```

The command-line workbook step uses the complete approved frame. Code callers can pass
rectangle or freehand points with `VideoInventorySelection` to isolate one item when a
frame contains several objects and can set `rotation_degrees` for accepted orientation.
Multiple distinct approved regions may come from one frame. Source videos and candidate
frames are hash-checked and never overwritten.

### Review database and 50-item queue

Use the SQLite-backed review queue for duplicate removal and crop correction. The
database is the durable working state; XLSX is a later export of accepted items.

Initialize one database beside the video project:

```powershell
.venv\Scripts\python.exe video_inventory_review.py init `
  "C:\path\to\item_proposals\proposal_manifest.json" `
  "C:\path\to\video_review\review.sqlite3" `
  --corrections-dir "C:\path\to\video_review\corrected_crops" `
  --batch-size 50
```

Start the loopback-only review screen:

```powershell
.venv\Scripts\python.exe video_inventory_review.py serve `
  "C:\path\to\video_review\review.sqlite3" `
  --port 8771
```

Open <http://127.0.0.1:8771>. Each fixed batch contains up to 50 proposal images.
Decisions are `Keep`, `Duplicate`, `Partial`, `Trash`, `New crop`, and `Unsure`.
Duplicate rows require the retained proposal ID. The crop editor draws against the
accepted frame orientation and saves a new revision without overwriting the original.
All decisions and crop revisions append audit events in SQLite. This records review
feedback for later heuristic improvements; it does not claim that a model retrains
itself automatically.

### iPhone media archive and cleanup

`iphone_media_manager.py` is a separate, loopback-only Windows workspace for
reviewing accessible iPhone media before copying or deleting anything. It scans an
unlocked, trusted iPhone's DCIM camera storage through the Windows portable-device
surface, plus user-approved iCloud Photos, iCloud Drive, Voice Memos export, and
other media folders. Voice Memos and app documents that Apple does not expose to
Windows must first be exported to a configured inbox.

Create a private runtime database and open the app:

```powershell
.venv\Scripts\python.exe iphone_media_manager.py init `
  "data\iphone_media\archive.sqlite3"

.venv\Scripts\python.exe iphone_media_manager.py serve `
  "data\iphone_media\archive.sqlite3" --open
```

The browser opens at <http://127.0.0.1:8773>. Add one or more sources, choose and
verify any writable local drive/folder, scan, mark each item's plan, and download
the selected items. Each job writes a `.partial` file, checks the expected size,
calculates SHA-256 during transfer, rereads the completed file, and only then
promotes it to the immutable archive. Optional total-job and single-file limits
are configured in **Settings**.

On this workstation, the PowerShell profile exposes the short launch command:

```powershell
iphone
```

It starts the loopback server in a hidden process if needed, waits for its status
endpoint, and opens the app. Use `iphone -Port 8774` only when the default port is
occupied.

Google Drive is the independent second-copy gate for phone deletion. Install its
optional dependencies, create a Google Desktop OAuth client, and select its private
client JSON in Settings:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-iphone-media.txt
```

The OAuth token is stored through Windows Credential Manager rather than in the
repository. The app uses `drive.file`, resumable upload, remote size, and remote
checksum verification. Immediately before any phone deletion it rereads the local
SHA-256 and requests current remote Drive metadata. Deletion requires the explicit
`Download + delete` plan, a fresh ten-minute preview, and the displayed typed
confirmation. Unsupported direct deletions remain truthful guided-manual tasks.

Google Drive is optional when a second local drive is available. In **Settings →
Another drive**, choose a folder on a different drive letter or network share. Each
selected original is copied from the verified primary archive into the mirrored
second-drive folder, reread, and required to have the same size and SHA-256. A second
folder on the primary volume does not satisfy the two-copy deletion gate. The app
rechecks both local files immediately before allowing deletion from the phone.

Transcription is not part of download or deletion. To enable it later, install the
separate local component and select verified archived audio in the app:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-transcription.txt
```

The local CPU model is downloaded only when a transcription job is first requested.
Transcripts are versioned sidecars; the original audio is never changed.

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

## Token-efficient Codex development

Use `DEVELOPMENT_MODEL_POLICY.md` as the single model-routing authority. State
the route once when a task begins and repeat it only if the required route
changes or does not match. Read only relevant documentation sections and do not
reread unchanged instruction files during the same task.

Run narrow tests while iterating and one full suite per completed cross-cutting
slice or final checkpoint. Reserve Luna/low subagents for bounded, substantial
routine work; give them no conversation history when practical and request only
counts and errors. A small deterministic command should stay in the active
development session when creating an agent would cost more than running it.

Price evaluation starts with cached evidence and exact-identity searches across
the core sources. Broader or thorough searching is an escalation after an exact
match fails or when the user requests it. Start an unrelated major feature in a
fresh conversation with a concise checkpoint handoff rather than carrying a
long task history forward. Keep only plugin bundles that are actively useful.

### Start a fully configured terminal session

A current-user PowerShell profile command starts Codex in this repository so
the personal `config.toml`, this workspace's `AGENTS.md`, and the development
model policy are discovered automatically. Open a new PowerShell terminal and
run:

```powershell
veridex
```

Optional Codex arguments pass through unchanged, for example `veridex --search`.
The launcher resolves the effective top-level model and reasoning effort from
the base `config.toml`, an optional named `--profile`, and explicit `--model` or
`--config` overrides. It prints that exact configured route at startup and makes
it available to the session as `VERIDEX_CODEX_CONFIGURED_MODEL`,
`VERIDEX_CODEX_CONFIGURED_REASONING`, and `VERIDEX_CODEX_ROUTE_SOURCE`. To inspect
the route without starting another session, run:

```powershell
.\start_codex.ps1 -PrintRoute
```

The launcher validates that the required rule files exist before starting. It
also starts Codex with `danger-full-access` and approval mode `never`, so the
session has unrestricted local filesystem access and does not pause for command
approval. Use this command only for this trusted workspace; the launcher prints
a permission warning on every start.

To choose a focused task handoff instead of loading the full project history,
say:

```text
list handoffs
```

Codex returns a numbered list, asks which handoff to use, and loads only the
handoff number supplied in the next message. The stable index is
`handoffs/README.md`.

## Gmail for Nancy

Nancy supports two deliberately separate account scopes:

- The Veridex corporate Gmail connection uses the encrypted token store beneath
  `data/integrations/` and is available from every workspace. Name `Veridex
  Corp`, `corporate`, `shared`, or the corporate address to select it.
- A workspace may own one separately authorized Gmail account beneath that
  workspace's `integrations/` directory. Generic Gmail requests use the assigned
  workspace account; when none is assigned, the connected corporate account is
  the safe default.

Veridex starts a read-only background monitor with the server. It checks important
mail immediately at startup and then once per hour; core/account health runs every
thirty minutes. Nancy scans
the shared corporate Gmail and each assigned workspace Gmail for recent offers,
sold-item notices, buyer questions, and account-security warnings such as new
sign-ins, password changes, suspicious activity, and verification codes. It
deduplicates results by account and Gmail
message ID, and shows them in My Office until dismissed. New mail flashes the
sidebar envelope three times and then leaves it solid until My Office is opened.
The monitor never marks Gmail messages read, sends mail, or stores credentials or
message bodies.

If a core or expected account check needs attention, the browser shows one combined
prompt asking whether to speak to Navigator. **Yes** explicitly enters the Control
Room; **No** closes the prompt without changing rooms. Facebook and Instagram checks
never launch profiles or attempt login automatically.

An account assigned to one workspace is never exposed to another, and the
corporate account cannot be claimed by a single workspace. Every Gmail result
records both `account_scope` and `account_email` as evidence. Veridex does not
read another application's token database at runtime. Configure the OAuth
client values in the ignored `.env.local`, then connect the corporate account
once:

```powershell
.\veridex.ps1 gmail-connect
.\veridex.ps1 restart
.\veridex.ps1 gmail-status
```

The browser authorization must use the account configured by
`VERIDEX_GOOGLE_ACCOUNT`. The reconnect command opens that authorization in the
same unified Veridex Chrome profile used by the application and explicit Google
work, not the Windows default browser profile. Passwords and OAuth tokens are
never written to source or returned in chat responses.

The dedicated Google search profile is also repository-wide. Google Drive is
not yet implemented as a Veridex runtime gateway, so Veridex must not claim
Drive access merely because the corporate Google identity is connected.

## Rooms

Choose a room from the selector beneath the session title, or type an explicit
command such as `go to Art Department`. Commands such as `list rooms`, `list
room controls`, and `can you list available rooms?` return the authoritative
directory. Room navigation and directory requests are handled deterministically
by Veridex before Codex is called, and every session still has exactly one
active room.

### eBay

The eBay room is hosted by Bob. Open **eBay · Bob → Open inventory** after navigating
there to make a named List, then add individual items to that List. The room shows the
selected List as a board or table without rendering its photos; photos remain inside the
individual item's workspace. Each item holds its photos, listing copy, price, research,
questions and working notes, ChatGPT/Gemini shared-thread links, and listing preparation.
Opening the inventory
automatically refreshes the connected seller's active, scheduled, sold, and unsold
listings through eBay's Trading API; **Refresh eBay** repeats that read manually.
Unmatched listings stay in a review queue. The operator can link one to an existing
item or explicitly approve an import that creates an Item Intake record and stores
local copies of up to twelve listing photos. The public listing URL or item number can
also be used for manual linking.

Opening an item replaces the board with a compact, URL-addressable workspace. Its tabs
are **Item**, **Gallery**, **Research & Questions**, **Market**, **AI Chat Threads**, and
**Groups**. Groups is a reusable Facebook-group directory: paste each group's rules,
record requirements and allowed item types, choose a review status, and target the
current item with an item-specific note. Rules are passed to Bob as item context, but
an unreviewed group is never treated as permission to post.
Fetching group information uses a temporary background page in the signed-in unified
Veridex browser and closes it after the read; the operator does not need to keep a
Facebook tab open. Fetch reads the group's About page, expands available **See more**
controls, and places a detected Rules section in the Rules field for operator review.
The Item tab is the home page for the record: it keeps master details, status, value,
counts, and next-workspace links in one place. Gallery
keeps source photos in a scrollable library beside the ordered **Listing photos** rail;
the first selected image is the intended main image. Photos and ZIPs can be selected or
dragged onto the same page. The saved ordered set is used for channel preparation without
moving or replacing originals.
Bob's workspace also includes non-destructive crop, auto-crop, auto-adjust, and
confirmation-gated AI touch-up tools. AI links and working notes save independently;
the green workspace **Save** button is always available, and switching tabs or leaving
the item workspace automatically saves the current tab's edits when there is enough
information to persist them.
Research & Questions keeps General notes at the bottom, while titled questions each
have their own findings panel. Leo can review the selected question and propose a
finding; the operator must choose Yes or No before a proposal is saved.
each saved thread has an in-page **View** action, while public shared links also have
**Extract media**, **Find listing**, and **Analyze** actions. Analyze adds the reviewed
thread material to the item, performs a governed Bob analysis, and keeps the response in
that item's conversation; it does not silently turn thread claims into verified findings.
**Find listing** reads the visible shared-thread proposal into separately editable eBay
and Facebook Marketplace drafts; it does not invent missing facts or publish either
listing. Private links remain view-only locally. The item-specific Bob panel stores its
messages in the governed session transcript and shows only messages attached to that
item; a reviewed response can be saved as an item finding. A separate control can look up a connected-seller listing by URL or item
number, show its verified facts, populate the item fields, and optionally extract listing
media into the source gallery. Inventory API publication is fixed-price and still
requires an explicit confirmation; Seller Hub handoff and Facebook Marketplace
preparation stop for the operator's final Publish click. Facebook preparation copies
only the ordered Listing photos into the session artifact ledger before filling the form.
The Market tab starts with Craigslist, Facebook Marketplace, eBay, and Etsy. OfferUp,
Mercari, Poshmark, Depop, and custom marketplaces can be added per item. Every form is a
local, photo-bound draft; only the existing eBay and Facebook governed handoffs perform
provider work.

Each item's photo workspace supports individual uploads, multi-file uploads, and ZIP
intake. Bob keeps the original ZIP with the item, safely extracts up to 500 contained
files within a 200 MiB expanded-content limit, and verifies stored sizes and SHA-256
checksums before reporting success. After a successful extract, the operator may choose
to delete the stored ZIP while keeping the extracted files. Use **Add to listing** on
source photos, then reorder the adjacent Listing photos sequence; deletion requires a
confirmation and affects only that item.

### Video Production

Video Production is directed by Beta. It provides governed chat and room-scoped
files for scripting, footage review, edit planning, post-production, captions,
export specifications, and delivery. This foundation does not include an embedded
timeline or render interface; Beta must distinguish proposed work from completed,
artifact-verified edits and exports.

### Animation Studio

Animation Studio is also directed by Beta and is specialized for reusable sets,
character rigs, recorded voice-over, mouth-cue generation, shot blocking, and
render handoff. Its starter project is **Eternia Late Night**, configured as a
commercial-safe 1920x1080, 24 fps, 2.5D cut-out production with desk and band
sets plus reusable host, co-host, guest, and band templates.

The studio detects Synfig Studio, Rhubarb Lip Sync, FFmpeg, GIMP,
Audacity, Kdenlive, and Glaxnimate on the local computer and reports unavailable
tools truthfully.
Rhubarb 1.14.0 is installed in the private `.runtime/tools/rhubarb/` tree with
its archive hash and install manifest. Project plans can be saved explicitly
before the other applications are installed.

To build a functional lip-sync take, load the character/base image and the
separate mouth drawings, create a character rig, map required Rhubarb shapes
A-F, and optionally map G, H, and X. Choose a voice-over, choose English word
recognition or phonetic recognition for another language, optionally provide
the exact script, then generate the cues. MP3, M4A, FLAC, and AAC inputs are
converted to a temporary analysis WAV with FFmpeg; the original audio is never
changed. The preview swaps the mapped mouth images in time with the voice-over,
and its cue timeline can seek to an individual cue. Jaw placement has independent
position, width, vertical scale, and internal anchor controls; the preview crosshair shows
the hinge point that remains pinned while the jaw is resized. New or changed rigs remain
uncalibrated until the operator confirms the visible jaw fit; lip-sync generation is blocked
until that registration step is complete. The closed jaw is directly draggable in a visible
selection box, and its corner resize handle updates the shared placement inherited by every
mapped mouth pose. Confirming the closed X pose scans each mapped image's transparency and
registers its visible upper span to the closed jaw, so differently padded source canvases do
not shift the hinge during playback. The preview remains visible beside the controls. Save the project to retain
the rig and generated take. The bound JSON cue sheet enters the normal
room-scoped artifact ledger before it is reported as complete. Final edit and
delivery remain in Video Production.

Skeletor rigs default to the measured `desk_host` stage placement from the
project's `host.png` reference: 80.97% horizontal, 43.12% vertical, and 22%
canvas width. These values are a reusable starting position rather than a lock;
shot-level placement may override them without changing the character rig.

Each explicit project save creates a read-only saved-version snapshot before the
current project is updated. Choose an older `saved version` from the project
selector to inspect or restore its jaw placement and other settings; saving that
restored state creates a new current version.

For a limited-animation character such as Skeletor, choose **Simple jaw flap**.
That mode uses one closed lower-jaw image and keeps its hinge fixed while the cue
track drives three opening amounts. The saved **Jaw opening** control scales those
amounts without changing cue timing or placement; Skeletor defaults to 200% while
other new rigs default to 100%. Place the jaw directly in the preview,
confirm it once, and keep the phoneme map and fine-adjustment sliders collapsed unless
an advanced character rig actually needs them.

The browser preview intentionally uses the native audio control and automatic cue track
only. The waveform, Quick Fix, and range-based manual-performance controls are disabled;
they do not decode the voice file or run an independent timeline. The automatic jaw preview
reads the native audio element's current time directly. Jaw sizing and anchoring remain
available separately through **Adjust jaw placement**. Save the calibrated rig and use the
bounded Synfig handoff for rendered shot timing.

When an Audio Suite dialogue track already has a bound lip-sync take, its Play control and
the Voice Performance Play control both drive that same take. Starting either one pauses the
other, so there is no silent second player or duplicate audio to put the jaw out of sync.

Project images can be loaded directly into the studio as ledgered session
artifacts. Full filenames remain visible in the asset list and on hover. The
project stores non-destructive role, scale, horizontal position,
vertical position, and opacity settings; it never overwrites the source image.
Storyboard shots place a selected project image beside the scene description,
with camera and editing notes beneath it. Shots can be reordered and can be
referenced by dialogue, music, and sound-effect tracks.

Each shot can be exported as a bounded Synfig package containing the selected
source media, placement metadata, audio timing, and lip-sync cues. Synfig is used
for movement and rendering one shot at a time; the rendered video or still can be
imported back into that shot as a versioned, ledgered artifact. Final assembly
stays in Video Production, so the two rooms do not maintain competing timelines.

The built-in audio surface is intentionally small: preview, episode start time,
trim points, gain, pan, fades, mute, solo, character, and storyboard-shot
assignment. GIMP and Audacity remain the full editors. Opening either program
requires explicit confirmation, and an edited version must be reimported so the
original Veridex artifact remains unchanged. Opening an image in Synfig creates a
ledgered `.sif` starter document that references the original image; Synfig is
never given the PNG as if it were an XML project.

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
`use a Google search ...` use the real local Chrome window owned by Veridex.
They do not silently fall back to a generic web-search provider.

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

The default user-data directory is
`C:\codex2veridex\data\browser_profiles\veridex_browser`, which is covered by
the repository's ignored `data/` directory. It is separate from ordinary Chrome
profiles and is not copied to GitHub. An existing signed-in Chrome identity may
be copied there once, after which Veridex owns and reuses the copy without
competing with ordinary Chrome. Search evidence records the provider,
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

## Dedicated Instagram bridge

Veridex can inspect profiles and compose future outreach through the unified
Veridex Chrome profile. In **Connected accounts**, enter the Instagram
username and choose **Open or reconnect Instagram**. Sign in directly on Instagram
in the dedicated Chrome window; Veridex never receives or stores the password.
The command-line profile and status helpers remain available:

```powershell
.\veridex.ps1 instagram-profile
.\veridex.ps1 instagram-status
```

If Instagram requests a security code or identity check, complete it in that
visible Chrome window. The social bridges use the unified profile configured by
`VERIDEX_BROWSER_PROFILE_DIR`, `VERIDEX_BROWSER_PROFILE_DIRECTORY`, and
`VERIDEX_BROWSER_DEBUG_PORT`, so Facebook and Instagram see the same saved
browser identity and sessions. The profile remains
local and is never pushed to GitHub. Veridex
tools expose status, bounded profile inspection, confirmation-gated follows,
message composition, and message sending. Composition leaves the text visible
for review; following and sending are separate actions that require
`confirm=true`.

## Dedicated Facebook bridge

Veridex can inspect a Facebook profile and compose outreach through the unified
Veridex Chrome profile. Put `FACEBOOK_USERNAME` (or `FACEBOOK_EMAIL`)
and `FACEBOOK_PASSWORD` only in ignored `local.env` or `.env.local`, then initialize
and sign in:

```powershell
.\veridex.ps1 facebook-profile
.\veridex.ps1 facebook-login
.\veridex.ps1 facebook-status
```

If Facebook requests a security code, approval, or identity check, complete it in
the visible Chrome window. Profile reads are bounded, message
composition leaves the text visible for review, and sending is a separate action
that requires `confirm=true`.

The same dedicated session appears in **Connected accounts**. That panel can open
or reconnect Facebook and refresh its status, but it never displays the configured
password. The configured login label identifies the local credentials; successful
session evidence confirms sign-in without claiming an independently verified profile
identity.

The **Sell on Facebook** panel adds a review-first Marketplace workflow. Drafts are
workspace-scoped and may start from an existing Museum case or newly ledgered photos.
Veridex can suggest an editable price from saved research, manage an explicit allowlist
of buy/sell group URLs, and fill the visible Marketplace form in the dedicated Facebook
profile. It never clicks Marketplace **Next** or **Publish**. After the operator publishes,
**Resume after publishing** requires matching visible listing evidence before a group
share can be prepared. Group preparation opens one approved group, composes the listing
link, and stops before **Post**. The first version is local-pickup only and uses the
location already configured by Facebook; Veridex does not store a pickup address.

## eBay seller tools

Connect eBay from **Connected accounts**. Veridex uses eBay OAuth rather than storing
an eBay password, encrypts reusable tokens in the active workspace, and defaults new
connections to eBay Sandbox. Configure an eBay Developer keyset and register the
deployed Worker's `/ebay/oauth/accepted` HTTPS route as the RuName accept URL; that
route forwards the one-time result to the loopback callback. Then add
the client ID, client secret, RuName, environment, marketplace, and the shared
integration-encryption key to ignored `.env.local` using `.env.local.example`.
eBay OAuth reuses the unified Veridex browser configured by
`VERIDEX_BROWSER_PROFILE_DIR`, `VERIDEX_BROWSER_PROFILE_DIRECTORY`, and
`VERIDEX_BROWSER_DEBUG_PORT`, so authorization cannot fall into an unsigned
default-browser window. `VERIDEX_EBAY_CHROME_PROFILE_DIRECTORY` remains a
legacy fallback when no unified browser is configured.

Read-only tools expose connection status, Inventory API records, SKU-scoped offers,
Seller Hub and API-created seller listings, orders, policies, and financial transactions.
`ebay.offer_list` requires a SKU because eBay's `getOffers` operation requires one;
`ebay.seller_listing_list` uses `GetMyeBaySelling` for the complete seller view.
Listing preview is local. Publishing and withdrawing fixed-price listings, recording
fulfillment, issuing refunds, and sending seller offers require an explicit confirmed
tool call. Buyer purchases and bidding are not supported. Inventory API listings remain
API-managed and cannot subsequently be revised through Seller Hub, so migrate existing
live listings only after a deliberate review.

Before publishing, the seller account must opt into eBay Business Policies, create at
least one payment, fulfillment/shipping, and return policy for the target marketplace,
and have an enabled Inventory API warehouse location. A warehouse location can use only
postal code and country; do not place its address in repository configuration. The
Developer Portal's manual token generator and consent preview are not part of the
application flow. A successful Veridex authorization-code exchange plus authenticated
seller API calls are the connection evidence.

The production notification receiver lives under `cloudflare/ebay-notifications/`.
It verifies eBay signatures, queues events for the `provenancepending` workspace in
Cloudflare D1, deletes acknowledged events, and expires unclaimed events after seven
days. Keep the generated verification and queue secrets only in ignored `.env.local`
and Cloudflare Worker secrets. The eBay destination URL is the deployed Worker's
`/ebay/notifications` route.

The local consumer starts with Veridex and automatically checks every explicitly
assigned eBay workspace once per minute. **Connected accounts → Check notifications**
and the `ebay.notification_check` tool remain available for an immediate manual check.
Automatic and manual checks are serialized against the workspace database so they
cannot drain the same queue concurrently. The consumer rejects a relay response whose workspace
does not exactly match `VERIDEX_EBAY_WORKER_WORKSPACE_ID`, commits each verified event
to the active workspace's `integrations/ebay_notifications.db`, and only then
acknowledges the remote queue copy. Notification IDs make retries idempotent. Raw
Marketplace Account Deletion payloads are not retained locally: Veridex records only
a SHA-256 digest, a non-identifying disposition, and whether the event matched the
workspace's assigned seller. Other webhook bodies are also reduced to bounded alert
summaries plus a digest rather than copied wholesale. `ORDER_CONFIRMATION`,
`BUYER_QUESTION`, and `NEW_MESSAGE` events become governed seller alerts. The Production
seller has enabled user subscriptions for all three topics using the
`commerce.notification.subscription` OAuth scope. eBay-generated test events completed
the Worker, D1, local persistence, mapping, and acknowledgement path on 2026-09-24;
that test evidence is not a claim that a real buyer message or sale has occurred.
Set `VERIDEX_EBAY_NOTIFICATION_AUTO_POLL=false` to disable the background loop,
`VERIDEX_EBAY_NOTIFICATION_POLL_SECONDS` to change its 15–3600 second interval, or
`VERIDEX_EBAY_NOTIFICATION_POLL_MAX_EVENTS` to change the 1–500 event limit per check.
Each assigned workspace also has a persisted **Turn on/off automatic checks** control in
Connected accounts. Turning a workspace back on wakes the poller for an immediate check;
turning it off does not disable the manual **Check now** action.

The production RuName uses the Worker's `/ebay/oauth/accepted` and
`/ebay/oauth/declined` routes. Its privacy URL is the independently hosted public page
at `https://time2makecents-ops.github.io/veridex-privacy/`; eBay rejected the otherwise
valid `workers.dev/privacy` URL during portal validation. The Worker's local `/privacy`
route remains informational but is not the registered RuName privacy URL.

## Codex MCP bridge

The included config snippet points Codex at `veridex_mcp.py`. Calling
`veridex_activate` starts this standalone server when needed and automatically
uses the default local session if no session ID is configured. Passing an explicit
workspace ID selects that workspace's most recently updated session and pins later
governed calls to the matching workspace/session pair.

## Test

```powershell
.venv\Scripts\python.exe -m unittest discover -v
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the governance and persistence
boundaries.
