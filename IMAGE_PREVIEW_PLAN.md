# General image preview and editing plan

Status: implemented and locally ready on this machine. Full unittest discovery passed 517 tests with zero failures/errors and no skips reported; JavaScript syntax checks passed. Background removal uses rembg 2.0.67 with U2NET CPU inference. The model is downloaded and its upstream MD5 verified here. A successful unmocked inference check passed on a synthetic 256x256 image. Real user-photo review and desktop/narrow visual QA remain unverified. Codex CLI was installed and signed in through ChatGPT; Veridex health reported full access. No dedicated touch-up skill was found. The shared local adjustment engine is extracted from Item Intake without requiring `item_id`; the existing Item Intake JPEG wrapper remains unchanged.

## User-approved experience

- Open previews from session **View files**, room **Files**, and Visual Design **Images**. Show **Touch up** for automatic general local adjustment that preserves framing and resolution; **Remove background** creates a transparent unsaved preview. **Restore background** toggles removal off while keeping other adjustments. **Revert** discards unsaved adjustments. The Visual Design destination library is **Images**; other room destinations use **Files**.
- **Edit** opens a full local editor with Crop, quarter-turn Rotate, Light, Color, and Detail. Sliders preview changes on release or when **Apply preview** is selected; **Compare with original** shows the source. No generative AI editing is included; background removal uses local U2NET.
- Edits remain unsaved until **Save copy**. Closing or switching with unsaved changes offers **Save copy**, **Discard**, or **Keep editing**.
- **Send** defaults to the current workspace and allows choosing any workspace and room except Lobby. Visual Design receives the image in **Images**; other rooms receive it in **Files**. It does not navigate or create chat, tasks, or hidden sessions. For an unsaved edit, **Save copy and send** saves first, then sends. If sending fails, retry the same request without duplicating the source save.

## Image and artifact rules

Support static JPEG, PNG, and WebP. Preserve source resolution, transparency, orientation, and color profile during preview. Manual Crop may intentionally change output dimensions. Saved edits are PNG in sRGB; orientation and alpha are maintained. Originals remain immutable. Source IDs are scoped; callers cannot supply arbitrary paths. Preview data is transient and does not create a persistent artifact or hidden session. `POST /api/room/images/preview` accepts the additive `recipe.remove_background` boolean and returns PNG bytes without persisting; scoped `POST /api/room/images/save` and `/send` use existing artifact machinery. `GET /api/room/images/content` serves room copies that have no session source.

Save a unique, verified derivative and a separate destination copy with lineage. Verify path, nonzero size, SHA-256, and artifact ledger. Guard duplicate submissions with request IDs persisted in artifact-ledger metadata across server restarts. This does not persist unsaved browser editor state across page reloads. Validate canonical room/destination and scoped source IDs with SHA checks; save/send require explicit confirmation and Navigator preflight for each affected workspace. On send failure, allow retry without creating another source save.

## Validation status and preparation

Background-removal checks: 11 backend tests plus one Web UI test passed; six Node interaction scenarios passed. Full unittest discovery passed 517 tests with zero failures/errors and no skips reported. The earlier 515-test run is historical. An unmocked CPU U2NET inference on a synthetic 256x256 item produced an RGBA result with unchanged dimensions and a nontrivial mask (minimum below 128, maximum above 128); source RGB pixels and original bytes remained exactly unchanged. First-call fixture inference took 8.3 seconds; this is one fixture result, not a performance guarantee. No actual user photo or browser visual workflow was tested.

`scripts/prepare_background_removal.py` downloads the fixed upstream GitHub model, verifies its published MD5, and prints its SHA-256. On this machine, `C:\Users\kgwamadmin\.u2net\u2net.onnx` is 175,997,641 bytes, passed upstream MD5 verification, and has SHA-256 `8d10d2f3bb75ae3b6d527c77944fc5e7dcd94b29809d47a739a7a728a912b491`. Weights are not in the repository; other machines must prepare their own copy under local `U2NET_HOME` or `~/.u2net`. The editing path lazily caches the model, serializes CPU inference, and refuses missing/corrupt weights without downloading them automatically.

Operator acceptance on a real item: in any of the three preview surfaces, select a supported image, check Remove background and Restore background alongside other adjustments, then Save copy or Save copy and send and verify the destination. Review edges/details, especially glass and fine structures. The source remains immutable. No generative AI, external image service, or photo upload is involved. Desktop/narrow visual QA is still pending. No new ports, providers, paid services, or model routes were added.

## Remaining acceptance checklist

- [ ] On desktop and a narrow browser, validate real user photos from session **View files**, room **Files**, and Visual Design **Images**.
- [ ] In all three surfaces, check **Touch up/Revert**, **Remove background/Restore background**, and the manual editor. Review mask edges, glass, and fine details before saving.
- [ ] Save a copy and send across workspaces; verify the destination library and confirm the original remains unchanged.
- [ ] Prepare and verify the dependency/model on each additional workstation before using background removal there.

Generative AI editing, including any Sunburst option, is explicitly deferred by the user's local-first decision; this plan makes no implementation promise for it.

## Research and local checks

- [eBay seller photo tips](https://www.ebay.com/sellercenter/listings/photo-tips)
- [Etsy image requirements and best practices](https://help.etsy.com/hc/en-us/articles/115015663347-Requirements-and-Best-Practices-for-Images-in-Your-Etsy-Shop): accurate color/condition and disclose defects; at least one unedited photo of the actual item against a real background is required, with possible exceptions.
- [Pillow ImageEnhance](https://pillow.readthedocs.io/en/stable/reference/ImageEnhance.html)
- [OpenAI image generation guide](https://developers.openai.com/api/docs/guides/image-generation): no generative AI is used for this feature.
- [rembg project documentation](https://github.com/danielgatis/rembg): local background-removal package reference.

The implementation adds shared `web/image_preview.js` and CSS mounted in the three approved surfaces. Static JPEG, PNG, and WebP are supported; animated and unsupported formats are rejected. Source limit is 50 MB and edit limit is 40 megapixels. The rembg dependency and verified model are installed on this machine; model weights must be prepared separately on other machines using the fixed-upstream checksum-verified helper. There are no model routes, paid services, or port changes. Pillow 12.3/ImageCms and a synthetic auto-adjust check were verified earlier; actual item images still need user review for mask quality, especially glass and fine details.
