# Image recognition and cropping handoff

## Scope

Continue item isolation, crop verification, evidence-preserving enhancement,
OCR/signature work, exact visual matching, and inventory spreadsheet images.
Do not load video-review runtime data for this work.

## Required identification behavior

- Default to exact identity. Distinguish a possible same physical item from the
  same model, edition, pattern, or catalog identity.
- If no exact result exists, ask before searching for similar items.
- If the user asks for all likeness, return exact results first and similar
  results separately.
- Ignore an artist signature only when the user explicitly asks; otherwise keep
  it as evidence and analyze it separately from the depicted subject.
- Report unreadable or ambiguous regions and, when useful, return an annotated
  image showing what needs a closer photograph.

## Crop procedure

1. Isolate the whole item with rectangle, freehand lasso, path, or edge-assisted
   selection. Include protrusions, handles, cords, packaging, and labels.
2. Composite the selection onto a transparent or neutral blank background.
3. Verify the crop against the source at useful zoom before accepting it. Reject
   tiny fragments, clipped edges, neighboring objects, and partial-item crops.
4. For spreadsheet corrections, replace the embedded image with a verified crop
   from the original source; do not merely repair the crop-folder copy.
5. Preserve the untouched source and record crop provenance. Derived images must
   never overwrite the original.

## Enhancement procedure

- Begin with conservative, evidence-preserving variants: scale up about 40%,
  modest sharpening, contrast/local-contrast, denoise, and multiple overlay
  opacity levels against the unmodified layer.
- Compare every enhanced result beside the untouched crop.
- If conservative variants fail, explicitly offer an increased-enhancement pass
  that may slightly alter identifying evidence. Label those outputs as search
  aids, not identity evidence.
- GIMP 3 is available locally for free-select/path masks, transparency, layer
  compositing, sharpening, scaling, edge detection, and batch export.

## Quality gate

Before delivering an XLSX, verify every embedded crop for whole-item coverage,
source correspondence, readable orientation, nonzero dimensions, and correct
row assignment. Use known inventory spreadsheets such as GS2 when appropriate;
do not use the previously poor video-review crops as test inputs.

## Relevant files

- `REUSABLE_VISUAL_ANALYSIS.md`
- `batch_inventory.py`
- `visual_evidence.py`
- `museum_visual_analysis.py`
- `signature_analysis.py`
- `requirements-ocr.txt`
- `test_batch_inventory.py`
- `test_visual_evidence.py`
- `test_museum_visual_analysis.py`
- `test_signature_analysis.py`
