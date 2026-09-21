# Veridex handoffs

Handoffs are intentionally split by task so a new Codex session loads only the
context it needs. Do not read every handoff automatically.

## Available

1. [Single-item sale](single-item-sale.md) — identify, research, price, and
   prepare one item for sale.
2. [Pricing research system](pricing-research.md) — continue the exact-first,
   low-usage price-evaluation controller and historical-sales work.
3. [Image recognition and cropping](image-recognition.md) — improve item
   isolation, enhancement, exact visual matching, and spreadsheet images.
4. [Video inventory](video-inventory.md) — continue frame extraction, crop
   review, duplicate handling, and the 50-item review queue.
5. [Browser and marketplace integrations](browser-marketplaces.md) — continue
   Google, eBay, Facebook, Instagram, connected-account, and popup handling.
6. [Workspace development checkpoint](workspace-checkpoint.md) — resume general
   Veridex development from the current branch and validation checkpoint.

Start a new PowerShell terminal, run `veridex`, and say:

```text
list handoffs
```

Codex will return this numbered list and ask which handoff to use. Reply with
only the number. Codex must then load only that selected handoff.
