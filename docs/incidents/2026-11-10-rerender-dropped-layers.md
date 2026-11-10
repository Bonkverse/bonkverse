# 2026-11-10: The whole-gallery re-render dropped layers it couldn't draw

**Impact:** for about two hours (07:23 to about 09:10 UTC) 91 skins that use the whisp
(shape 115) showed without it, and 2 skins showed garbled images. 359 skins
kept their old images until the decoder was fixed. All are re-rendered
correctly now.
**Trigger:** re-rendering all 9,410 skins from their codes
(`manage.py rerender_skins`, #76), the first time every stored code went
through the editor's render service.
**Fixed in:** skin-editor #9, #10, #11, #12; bonkverse #78, #79, #80.

## What happened

1. Run 1 (07:23 UTC): 9,051 skins re-rendered, 359 failed. The editor's
   decoder assumed every layer slot holds a layer; layers removed in bonk.io
   leave empty slots. Failed skins kept their old images. Fixed in
   skin-editor #9.
2. Run 2: 9,395 re-rendered, 15 failed. Two of those (166, 543) had
   "succeeded" in run 1 with **garbage images**: their layer list is stored
   in the other AMF3 form (slots past a gap as `"index" → layer` pairs), which
   the old decoder misread without an error. #9's stricter check refused
   them. Fixed in skin-editor #10.
3. The owner noticed skins wearing the whisp had lost it. The whisp's SVG was
   in the editor, but `TOTAL_BONK_SHAPES` stopped at 114, so the render
   service never loaded it, and **the renderer skips a layer it has no shape
   for and still answers `ok`**. Both runs had saved those skins without the
   whisp, replacing BonkLeagues' correct images. Fixed in skin-editor #11.
4. A targeted pass (a shell snippet, 104 skins: the 13 remaining failures and
   the 91 whisp skins) re-rendered all of them with 0 failures, and purged
   just their files from Cloudflare.
5. The last two failures were skins from an earlier security test whose
   "code" was text (`POC-FINAL-002`). The publish API had accepted any text
   as a code. Fixed in #78: codes are checked wherever a client supplies one.
6. `audit_skin_codes` then showed the first rules were too strict (152 real
   skins have more than 16 layers; 9 have NaN values; 2 were saved by the
   editor with a one-byte layer count; 1 is URL-encoded three times). Fixed in
   #79, #80 and skin-editor #12. 9 stored codes remain refused, all broken.

## What changed

- The editor's decoder reads the AMF3 layer array properly (both forms, empty
  slots, the editor encoder's one-byte count), with `npm test` built on real
  codes. bonkverse's `SkinCode.parse()` reads the same format.
- The whisp is in the editor (`TOTAL_BONK_SHAPES = 115`), and a test checks
  every offered shape has an SVG and a center.
- Codes from the editor's publish and BonxBot must parse
  ([bonk/skin-codes.md](../bonk/skin-codes.md)); `audit_skin_codes` reports
  stored codes the rules refuse.
- [ADR 0015](../adr/0015-skin-images-from-skin-codes.md) and
  [architecture/skin-images.md](../architecture/skin-images.md) describe how
  images are made; the runbook's re-render section covers re-rendering a few
  skins and checking shapes first.

## Follow-ups

- The render service should refuse a code with a shape it doesn't have
  (`unknown_shape`) instead of dropping the layer, so a re-render keeps the
  old image. Until then, check `TOTAL_BONK_SHAPES` before a bulk run.
- `integrations/editor_render.py` logs only the status of a 4xx; log the
  editor's `error`/`hint` too.
- `rerender_skins --ids` / `--shape` options, so a targeted pass is one
  command instead of a shell snippet.
- The editor's encoder writes the layer count as one byte, which isn't valid
  AMF3 past 63 layers.
