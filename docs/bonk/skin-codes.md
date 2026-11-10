# Skin codes

A skin code is the string bonk.io stores for an avatar: base64 of an AMF3
object. Bonkverse stores one per skin (`Skin.skin_code`), sends it to bonk.io
when a player wears the skin, and renders images from it (the skin editor's
`/api/render-bundle`).

`core.bonk.SkinCode` is the one place that knows the format:
`SkinCode(raw).decoded` removes URL-encoding, and `SkinCode(raw).parse()`
reads the skin or raises `InvalidSkinCode`.

## Format

| Bytes | Meaning |
|---|---|
| `0a 07 03 61` | object, externalizable, class `"a"` |
| 2 bytes | format version |
| `09` + array | the layer list (below) |
| `01` … | AMF3 nulls, only on skins saved with no layers |
| 4 bytes | base color, `0x00RRGGBB` |

The layer list is an AS3 array, written as:

1. a variable-length integer, the **dense** slot count × 2 + 1;
2. **index → layer pairs** for slots past a gap, ended by an empty string
   (`01`). AS3 writes slots this way once a layer in the middle has been
   removed in bonk.io;
3. the dense slots `0 … n-1`.

Any slot can be empty (`01` null or `00` undefined). Each layer is `0a`, then
the class (`07 05 61 6c` = class `"al"` for the first layer in the bytes,
`05` for a reference to it after that), then `00 01`, shape id (2 bytes),
scale, angle, x, y (4-byte floats), flipX, flipY (1 byte each), color
(4 bytes). Layers are drawn in slot order. The skin editor's
`src/bonk/decode/decodeSkinCore.js` reads the same format.

## What a code must pass

Wherever a client supplies a code (the editor's publish API, BonxBot
submissions), it must `parse()`. Otherwise the request is refused (publish: 422
"That isn't a bonk.io skin code"; bot: 422 `invalid_skin_code`, not
retryable). A code that passes:

- is base64, at most `MAX_CODE_LENGTH` (12000) characters (URL-encoding included);
- has the format above and nothing after the base color;
- has at most `MAX_LAYERS` (128) layers. bonk.io's own editor stops at 16,
  but the gallery has real skins with up to 51, so this is only a sanity
  bound. NaN or infinite layer values are allowed: some real skins have them;
- uses only shapes `1 … MAX_SHAPE_ID` (115, the editor's shapes; 115 is the
  whisp, which bonk.io's own editor doesn't list but skins can wear).
  Raise `MAX_SHAPE_ID` together with the editor's `TOTAL_BONK_SHAPES`.

Why: two skins were once published through the API with text
(`POC-FINAL-002`) as their code, alongside an SVG carrying a script (stopped
by the SVG check, `skins/svg_sanitizer.py`). The code is reused everywhere
(wear, editor, re-render), so it is checked the same way.

Codes from BonkLeagues (fetched by the BL skin fetcher) aren't checked: they
come with BonkLeagues' own render.

After changing the rules, check the stored codes (read-only):

```bash
python manage.py audit_skin_codes          # counts by reason, with example ids
python manage.py audit_skin_codes --ids    # every refused id
```

A real skin refused there would be refused when someone publishes one like it.
