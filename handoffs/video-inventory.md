# Video inventory handoff

## Scope

Continue the review-first workflow that extracts item views from estate-sale or
table videos and turns accepted items into inventory records and later XLSX
exports.

## Implemented

- Bounded frame sampling with sharp/stable-view preference.
- Near-identical full-frame duplicate removal, contact sheets, and provenance
  manifests.
- Similar adjacent-scene grouping, four-way orientation review, and proposed
  whole-region lassos with boundary-risk flags.
- Approved rectangle/freehand selection and rotation support.
- SQLite-backed review queue with `Keep`, `Duplicate`, `Partial`, `Trash`, `New
  crop`, and `Unsure` decisions.
- Append-only review/crop audit events and batches of up to 50 proposals.

## Known limitation

The earlier Facebook-video review produced too many bad or partial crops to use
as a validation dataset. Do not reuse those crops or review decisions to test
new image-recognition, pricing, or controller work. The database remains the
durable review state, but acceptance requires a new visual quality pass.

## Next work

- Improve scene/object segmentation so proposed crops contain the complete item
  rather than a small salient fragment.
- Add an automatic crop QA pass for clipped boundaries, very small foreground
  coverage, implausible aspect/area, and neighboring-object contamination.
- Require source-versus-crop visual verification before a proposal enters the
  50-item review queue or an XLSX export.
- Keep duplicate detection separate from partial/trash classification and retain
  user corrections as auditable evidence, not automatic model training claims.
- Validate on synthetic fixtures or newly approved clean material first.

## Relevant files

- `video_inventory.py`
- `video_inventory_review.py`
- `web/video_review/index.html`
- `web/video_review/app.js`
- `web/video_review/styles.css`
- `test_video_inventory.py`
- `test_video_inventory_review.py`
- `README.md` video inventory and review database sections
