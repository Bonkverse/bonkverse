# Frontend: templates, scripts and styles

Bonkverse pages are Django templates with plain JavaScript and CSS. No build
step, no framework. This page is how a page is put together, where each piece
lives, and the rules `tests/test_frontend.py` holds every page to. Why it is
this way: [ADR 0009](../adr/0009-frontend-structure.md).

## What every page gets

Every page extends `skins/templates/skins/base.html`, which loads, in order:

| Where | What | Gives the page |
|---|---|---|
| `<head>` | `css/*.css` (base, forms, navbar, cards, modal, …) | the shared look |
| `<head>` | `{% block extra_head %}` | the page's own stylesheet, if it has one |
| `<head>` | Lucide (pinned version, unpkg), `js/scripts.js`, `js/pagination.js`, particles.js | icons, navbar and carousel behavior, `BVPagination` |
| `<head>` | `js/toast.js` | `BVToast.show(text, {type})` |
| `<head>` | `core/js/bv-api.js` | `BVApi`: every POST from a page script |
| `<head>` | `core/js/bv-wear.js` | `BVWear.wear(url)`: wearing a skin and the bonk.io login modal |
| `<head>` | `core/js/bv-cards.js` | what skin cards do; image zoom and fallback |
| `<head>` | `core/js/bv-report.js` | the report modal, opened by any `[data-report-skin]` |
| end of `<body>` | `core/js/bv-boot.js` | Django messages as toasts, particle background, icons drawn |
| end of `<body>` | `{% block extra_scripts %}` | the page's own script |

The `core/js/` files are the shared ones. Each says at the top what it
handles and what markup it expects.

## The shared pieces

**Requests: `BVApi`** (`core/js/bv-api.js`). `post(url, data)` returns
`{ok, status, json}` and never throws (a network failure is `status: 0`).
`postOrLogin(url, data)` sends a logged-out visitor to the login page and
returns the JSON or `null`. It reads the CSRF cookie itself; no page does.

**Wearing: `BVWear`** (`core/js/bv-wear.js`) with
`skins/partials/_bonk_login_modal.html`. Opens the bonk.io login modal only
when the server says the bonk.io token was refused, retries the wear once
after a login, and never reopens the modal (see
[ADR 0008](../adr/0008-bonk-refusals.md)). A page with a Wear button includes
the modal partial.

**Skin cards.** Two partials, used everywhere cards appear:

- `skins/partials/_skin_card.html`: the full card. `mode='search'` (star,
  voting, Report, staff Re-render), `mode='mine'` (select checkbox, Edit,
  Delete) or `mode='favorite'`. The view feeds it with
  `skins.selectors.decorate_skins_for_user(skins, request.user)`, which adds
  the favorite count and the visitor's vote and favorite in a fixed number of
  queries (`tests/test_query_budgets.py`).
- `skins/partials/_skin_card_compact.html`: the linked tile on the home
  carousels and browse pages.

`core/js/bv-cards.js` handles the ⋯ menu, image zoom, the broken-image
fallback, votes, favorites and Wear, all delegated from `document`, so cards
a page swaps in later work too. In select mode (`.select-mode`, the profile's
bulk delete) a click only selects. Outside cards, `img[data-zoom]` zooms and
`img[data-fallback]` falls back the same way.

**Reporting: `BVReport`** (`core/js/bv-report.js`) with
`skins/partials/_report_skin_modal.html`:

```html
<button data-report-skin="{{ skin.id }}" data-skin-name="{{ skin.name }}">Report</button>
```

**Modals** share `css/modal.css` (`.modal-overlay`, `.modal-box`,
`.modal-subtitle`, `.modal-feedback`, …). Show one by adding `.open`.

## A page's own script and styles

```
skins/templates/skins/skin_detail.html   markup; data in data- attributes
skins/static/js/skin_detail.js           behavior, loaded from {% block extra_scripts %}
skins/static/css/skin_detail.css         styles, if no shared file fits
```

- **Data from the template** goes in `data-` attributes or `json_script`,
  never as template tags inside JavaScript:
  ```html
  <div id="skin-detail" data-wear-url="{% url 'wear_skin' skin.id %}">
  {{ active_tags|json_script:"active-tags" }}
  ```
- **Listeners** are added in the script. No `onclick=""`.
- **Show and hide** with the `hidden` attribute (`base.css` makes it win
  over any `display` a class sets).
- **Styles** go in a shared file when the rule is shared (`modal.css`,
  `cards.css`, `forms.css`), or in the page's file loaded from
  `{% block extra_head %}`. The one inline style allowed is a value the
  template computes, passed as a CSS custom property:
  `style="--bar: 42%"` with `.bar-inner { width: var(--bar) }`.
- Don't write `|escapejs` into an HTML attribute; attributes are already
  escaped, and `escapejs` output shows up literally (`"`).

## What the tests check

`tests/test_frontend.py` reads every template and script:

- no page defines its own `getCSRF`/`postForm`, bonk.io login or report modal;
- only the two card partials write card markup, and only `bv-cards.js`
  selects card buttons;
- no `style=""` (except custom-property values) and no `<style>` blocks;
- no inline `<script>` (except `json_script` data) and no `on*=` handlers;
- pages with cards or Wear load the shared scripts;
- the Lucide version is pinned.

`500.html` is exempt from all of these: it must render even when static files
can't be served.

## Checking a change in a browser

Tests don't run the JavaScript. For a frontend change, also:

1. Screenshot the pages it touches before and after (logged in and out), and
   compare. Moving code should change no pixels.
2. Click through what you changed with the browser console open. A script
   error stops every listener after it on that page.

## Not here yet

React, htmx or a design system: the frontend direction after RFC-0001 is a
separate RFC (RFC-0002).
