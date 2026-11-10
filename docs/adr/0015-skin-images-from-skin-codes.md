# ADR 0015: Skin images are rendered by Bonkverse from the stored skin code, and a code must be a real skin

**Status:** accepted, 2026-11-10 (RFC-0001 Phase 4, step 4.6, and the re-render that followed)

**Context.** A skin's images came from three places, each writing files its
own way: the editor's publish (an SVG sent by the browser), the BonkLeagues /
BonxBot import (images fetched from BonkLeagues), and the staff Re-render
button. 7,303 of 9,410 skins pointed `image_url` at BonkLeagues' image
service instead of our own files, the likeliest cause of "broken" images. The
stored skin code is reused everywhere (wearing on bonk.io, opening in the
editor, re-rendering), yet the publish API stored any text as a code: two
skins from a security test carried `POC-FINAL-002`, next to an SVG with a
`<script>` in it.

**Decision.**
- **Every skin's images are its three files in `/media/skins/`** (`<id>.svg`,
  `<id>.png`, `<id>_thumb.png`), written only by `skins/skin_media.py:
  save_render`. It writes temporary files, moves them into place, then points
  `image_url` and the `SkinImage` rows at them; a failed write leaves the old
  files and rows untouched. `image_url` points at `/media/`.
- **The stored skin code is the source** of a skin's images. Re-rendering
  (`skins/rerender.py: rerender`, the button and `manage.py rerender_skins`)
  sends the code to the editor's render service (`/api/render-bundle`,
  `integrations/editor_render.py`), checks the SVG (`svg_sanitizer.py`) and
  saves it with `save_render`.
- **A code a client supplies must parse as a bonk.io skin**
  (`core.bonk.SkinCode.parse()`): the editor's publish (422) and BonxBot
  imports (`invalid_skin_code`). The rules and format are in
  [bonk/skin-codes.md](../bonk/skin-codes.md); `manage.py audit_skin_codes`
  checks stored codes against them.
- The skin format is read the same way in two places: Python
  (`core/bonk/skin_codes.py`) and the editor's decoder
  (`skin-editor/src/bonk/decode/decodeSkinCore.js`). A change to one gets a
  matching change to the other, with a test built on a real code.
- The shapes Bonkverse accepts (`MAX_SHAPE_ID`, 115) are the shapes the editor
  can draw (`TOTAL_BONK_SHAPES`); they change together.

**Alternatives considered.**
- *Keep BonkLeagues' image URLs*: no render work, but our pages depend on
  another site's uptime and output, and nothing can be re-rendered when a
  shape is fixed.
- *Trust the SVG the browser sends at publish*: what the code did. The SVG is
  checked for scripts, but the stored code could still be anything.
- *Render with a Python copy of the editor's renderer*: no network hop, but a
  second renderer to keep pixel-identical with the editor.

**Consequences.**
- The editor's render service is a dependency of publishing BonxBot skins and
  re-rendering (not of viewing: files are served from `/media/`).
- **The render service draws a skin without any layer whose shape it doesn't
  have, and still answers `ok`.** On 2026-11-10 that made a whole-gallery
  re-render drop the whisp (shape 115) from 91 skins
  ([incident](../incidents/2026-11-10-rerender-dropped-layers.md)). Until the
  service refuses unknown shapes, check `TOTAL_BONK_SHAPES` before a bulk
  re-render; the editor's tests check every offered shape has a file.
- Skin files live on the `bonkverse` service's volume: only it can write them
  (not the worker), and it can't run more than one replica until media moves
  to object storage.
- Skins with a code the rules refuse (9 on 2026-11-10, all broken) keep
  whatever images they have.
