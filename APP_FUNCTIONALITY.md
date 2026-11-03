# Veridex app functionality

This is a guide to the functionality described by the current repository, not
proof that every integration is connected or every workflow has been tested in a
live session. See [README.md](README.md) for setup and detailed instructions and
[ISSUE_LOG.md](ISSUE_LOG.md) for reported problems and verification status.

## Everyday navigation and assistance

- **Local app:** A single-user web application backed by the authenticated Codex
  CLI, with workspaces and sessions for organizing work. New sessions start in
  the Lobby. The app does not need an OpenAI API key.
- **Rooms and personas:** Select a room in the sidebar or navigate explicitly in
  chat. One room is active per session; Navigator monitors governance decisions.
- **Chat and files:** Conversations persist locally. Files can be attached to a
  session; generated and uploaded artifacts follow verification and ledger rules.
  Stopping a cancellable request records a stopped state.
- **Connected accounts:** The top toolbar opens account connections and status.
  Corporate Gmail is shared. An optional shared-accounts setting also makes the
  designated owner's Gmail, eBay, and Instagram assignments available across
  workspaces; without it, those assignments retain workspace separation.

## Rooms and work surfaces

- **Shared room workspace:** Every room uses Video Production's workspace size
  and header format, with room actions followed by Chat with its persona. The
  floating chat reuses the session conversation and preserves an unsent draft
  when closed. Control Room and Infrastructure expose the existing system log.
  My Office exposes existing email controls; Calendar is explicitly not
  implemented. Room workspaces include a **Jobs** list scoped to the selected
  workspace and room across sessions; image job creation is currently available
  from Visual Design. Separate tool pages keep their existing layouts.
  Chat includes a centered title, minimize/maximize/restore/close controls, and
  a model selector starting on automatic routing marked **(default)**. Manual
  Codex choices and configured text-only Gemini are available for normal chat;
  choices remain scoped to the current browser page's room/session. Gemini is
  labeled unavailable when its Veridex connection is not configured.
  Selecting a Codex model opens a connected reasoning panel with Low, Medium,
  High, Extra high, and Max choices. The usual model level is marked as default;
  automatic routing and the current Gemini adapter keep their existing reasoning.

- **Museum / Leo:** Research item photos, examine identifying details, save
  cases, and compare sourced price evidence. Google Lens upload requires consent
  unless the scoped shopping mode is active. Guidance is not an appraisal.
- **Betting / Slick:** View supported scores, track selected live pages, and keep
  a manual trade journal. The Betting chat has image selection, drag-and-drop,
  and screenshot paste controls. The journal does not place orders or provide
  live market prices; availability of the room depends on administration setup.
- **eBay / Bob:** Maintain seller inventory, item details, photos, drafts,
  listings, orders, and notifications. Publishing and other consequential seller
  actions require explicit confirmation; provider availability and authorization
  determine what works.
- **Art Department:** Generate or edit images, manage projects and lineage, and
  use local finishing tools and configured providers.
- **Visual Design image jobs:** Chat image requests create durable numbered
  drafts with an `rj_` ID. The owner presents its interpretation and assumptions
  and shows **Send to room** and **Keep editing** for each new or revised brief.
  **Keep editing** opens pre-creation refinement, where relevant use, style, or
  caption questions may be asked before the choices appear again. Refinements
  retain the draft ID and increment its version. Production runs separately from chat;
  the room Jobs list shows progress and allows cancellation while chat remains
  usable. Acknowledgment follows validation, and completion or failure appears
  in the originating room/session without navigation. One square PNG is the
  default; requests can specify an aspect, and users can select one to four
  variants. Follow-ups include accepting, revising, creating variants, resizing
  or exporting, comparing versions, and asking Systems. Outputs are reported
  only after path, size, SHA-256, and artifact-ledger checks. One recovered
  request was produced through the existing Codex media route and its output
  was independently checked against the artifact ledger in an earlier
  checkpoint. Current Jobs popup changes passed full automated discovery, but
  current visual browser QA is pending; refresh Veridex to load the new JS/CSS.
  No live generation or poster edit was performed for this update. The current
  layout appearance and other providers remain unverified.
  The Jobs popup provides date, name, source, and type/status sorting, including
  Completed first and Draft first, and keyboard/detail navigation. New unsent
  drafts stay in chat until saved; older drafts remain visible. Typing **send**
  and the Send button open the same Yes/No confirmation. Save as draft preserves
  the request without submitting it. Active jobs appear in workspace tabs;
  completion archives the tab while preserving the job and its results.
  The image history combines chat jobs and verified Art Studio outputs. Renaming
  completed images changes friendly metadata only, preserving canonical files
  and ledger records.
- **HR Resume Studio:** Maintain career profiles, tailor resumes, review ATS
  considerations, and export documents.
- **Video Production and Animation Studio:** Use the repository's video review,
  inventory extraction, and animation workflows as described in the README.
  Audio/video files in the room Files library can be opened in detected VLC on
  the Veridex computer after confirmation, with full computer access enabled.
  Video Production's Production tools panel also opens installed Kdenlive,
  Shotcut, Audacity, HandBrake and OBS. Supported MLT renders and HandBrake
  conversions run as cancellable jobs and import verified outputs. Local OBS
  control and Audacity normalization require their explicit setup first.
  Video Production has a searchable room-media workspace, source player, and
  floating Beta chat. Top-toolbar room intake is separate from attachments beside
  the chat input. Timeline editing is still pending.
  On 2026-11-02, the room, source preview, and Production tools panel were
  observed in Chrome, and the user confirmed browser video playback. Interactive
  upload, seeking, chat behavior, native-editor launches, and live export/import
  still need verification; see ISSUE_LOG.md for the recorded evidence.

## Collection and sales support

- **Item Intake and Capture Companion:** Organize items, photos, documents and
  other files into batches; capture photos on a paired phone; edit derived photos
  without overwriting originals; and explicitly send selected material to a
  Veridex session. Research and listings do not start automatically.
- **Market and social workflows:** Prepare local marketplace drafts and use
  existing governed eBay and Facebook handoffs. Facebook and Instagram browser
  integrations depend on the signed-in dedicated browser session. Marketplace
  actions remain subject to their documented review and confirmation boundaries.
- **Email:** Nancy can work with corporate and assigned Gmail accounts and
  surface relevant notices. Google sign-in, consent, or security challenges may
  still require the user; a reconnect button starts the corporate Gmail flow.

## Browser, privacy, and governance

- The normal launcher and Google, Gmail, Facebook, and Instagram bridges are
  designed to use one dedicated Veridex Chrome profile. Being in that profile
  does not itself guarantee that each external service is signed in.
- Workspace content and rooms stay separate even when account sharing is enabled.
  External actions require the applicable confirmation path. Google Drive is
  not an implemented runtime gateway merely because Google is connected.
- Administration controls rooms and governed changes; provider failures should be
  reported rather than silently rerouted. Local access is the default, with
  separate pairing options for supported remote access.
