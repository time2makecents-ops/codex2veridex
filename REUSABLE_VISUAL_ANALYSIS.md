# Future reusable visual-analysis tools

Keep the first implementation inside Veridex while its interfaces settle. After real Museum cases and mocked provider tests confirm stable behavior, extract and register these two tools in the local tool registry:

1. **Provider-neutral visual-evidence normalizer** — accepts bounded visible results from Lens or another reverse-image provider and emits ranked, deduplicated HTTP(S) evidence with explicit completed, limited, blocked, or failed status.
2. **Standalone signature-analysis tool** — accepts a signature crop, creates deterministic OpenCV preprocessing views, runs optional OCR, and returns provenance-labeled literal readings, normalized spellings, cautious model hypotheses, and bounded search-query suggestions.

Do not register either interface until its schema is versioned, its privacy boundary is documented, and its unit tests cover unavailable optional dependencies and malformed provider output.
