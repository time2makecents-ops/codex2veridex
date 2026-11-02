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
