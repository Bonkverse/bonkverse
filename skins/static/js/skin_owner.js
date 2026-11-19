// skin_owner.js: managing your own skins on your profile's Skins tab
// (players/skins.html with cards in mode='mine', skins/partials/_skin_owner_dialogs.html).
//
//   Edit       the ⋯ menu's Edit opens a dialog: name and tags (one tag per
//              Enter, × to remove). Saves through the card's data-url and
//              updates the card in place.
//   Delete     the ⋯ menu's Delete asks first, then removes the card.
//   Select     "Select" turns the grid into select mode (core/js/bv-cards.js
//              then leaves clicks to this script): click cards to select,
//              "Select all on this page", "Delete…" asks first and deletes
//              them all. A selection is only for the page you're on.
//
// Copy link is ui/ui.js; Wear, Enlarge and the menu itself are bv-cards.js
// and ui.js. Server answers: {ok, data} or {ok: false, error, message}.

(function () {
  "use strict";

  const root = document.getElementById("skin-owner");
  const grid = document.getElementById("skin-grid");
  if (!root || !grid) return;

  const toast = (text, type) => window.BVToast && BVToast.show(text, { type: type || "success" });

  function closeMenus() {
    document.querySelectorAll(".bv-skin-card .bv-menu:not([hidden])").forEach((menu) => {
      menu.hidden = true;
      const opener = document.querySelector(`[aria-controls="${menu.id}"]`);
      if (opener) opener.setAttribute("aria-expanded", "false");
    });
  }

  function removeCards(ids) {
    ids.forEach((id) => {
      const card = grid.querySelector(`.bv-skin-card[data-id="${id}"]`);
      if (card) card.remove();
    });
    // An emptied page: reload, so the server shows the next page or the empty state.
    if (!grid.querySelector(".bv-skin-card")) window.location.reload();
  }

  // ── Edit ──────────────────────────────────────────────────────
  const editDialog = document.getElementById("skin-edit-dialog");
  const editForm = document.getElementById("skin-edit-form");
  const nameInput = document.getElementById("skin-edit-name");
  const tagInput = document.getElementById("skin-edit-tag");
  const tagList = document.getElementById("skin-edit-tags");
  const editError = document.getElementById("skin-edit-error");
  const saveButton = document.getElementById("skin-edit-save");
  let editing = null; // the Edit menu item of the card being edited

  function tagValues() {
    return [...tagList.querySelectorAll("li")].map((li) => li.dataset.tag);
  }

  function addTag(text) {
    const tag = text.trim().replace(/\s+/g, " ");
    if (!tag) return;
    if (tagValues().some((t) => t.toLowerCase() === tag.toLowerCase())) return;
    const li = document.createElement("li");
    li.className = "bv-pill site-tag-editor__tag";
    li.dataset.tag = tag;
    li.append(tag);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "site-tag-editor__remove";
    remove.setAttribute("aria-label", `Remove ${tag}`);
    remove.textContent = "×";
    remove.addEventListener("click", () => { li.remove(); tagInput.focus(); });
    li.append(remove);
    tagList.append(li);
  }

  tagInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addTag(tagInput.value);
      tagInput.value = "";
    } else if (e.key === "Backspace" && !tagInput.value) {
      const last = tagList.lastElementChild;
      if (last) last.remove();
    }
  });

  function openEdit(item) {
    editing = item;
    nameInput.value = item.dataset.name || "";
    document.getElementById("skin-edit-art").src = item.dataset.image || "";
    tagList.replaceChildren();
    let tags = [];
    try { tags = JSON.parse(item.dataset.tags || "[]"); } catch (e) { /* no tags */ }
    tags.forEach(addTag);
    tagInput.value = "";
    editError.hidden = true;
    editDialog.showModal();
    nameInput.focus();
  }

  editForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!editing) return;
    addTag(tagInput.value); // a tag typed but not yet Entered still counts
    tagInput.value = "";
    saveButton.disabled = true;
    saveButton.setAttribute("aria-busy", "true");
    const { ok, json } = await BVApi.post(editing.dataset.url, {
      name: nameInput.value,
      tags: JSON.stringify(tagValues()),
    });
    saveButton.disabled = false;
    saveButton.removeAttribute("aria-busy");
    if (!ok || !json.ok) {
      editError.textContent = json.message || "That didn't save. Try again in a minute.";
      editError.hidden = false;
      return;
    }
    const { name, tags } = json.data;
    const card = editing.closest(".bv-skin-card");
    card.querySelector(".bv-skin-card__title").textContent = name;
    card.querySelectorAll("[data-name]").forEach((el) => { el.dataset.name = name; });
    editing.dataset.tags = JSON.stringify(tags);
    editDialog.close();
    toast("Saved.");
  });

  // ── Delete (one skin, or the selection) ──────────────────────
  const deleteDialog = document.getElementById("skin-delete-dialog");
  const deleteTitle = document.getElementById("skin-delete-title");
  const deleteText = document.getElementById("skin-delete-text");
  const deleteButton = document.getElementById("skin-delete-confirm");
  let pendingDelete = null; // () => Promise<void>

  function askDelete(title, text, action) {
    deleteTitle.textContent = title; // textContent: skin names are user text
    deleteText.textContent = text;
    pendingDelete = action;
    deleteDialog.showModal();
  }

  deleteButton.addEventListener("click", async () => {
    if (!pendingDelete) return;
    deleteButton.disabled = true;
    deleteButton.setAttribute("aria-busy", "true");
    await pendingDelete();
    deleteButton.disabled = false;
    deleteButton.removeAttribute("aria-busy");
    pendingDelete = null;
    deleteDialog.close();
  });

  function deleteOne(item) {
    const name = item.dataset.name;
    askDelete(`Delete “${name}”?`, "It disappears from Bonkverse for everyone. This can't be undone.", async () => {
      const { ok, json } = await BVApi.post(item.dataset.url);
      if (!ok || !json.ok) { toast("That didn't delete. Try again in a minute.", "error"); return; }
      removeCards(json.data.deleted_ids);
      toast(`Deleted “${name}”.`);
    });
  }

  // ── Menu items (delegated: one listener for every card) ──────
  grid.addEventListener("click", (e) => {
    const edit = e.target.closest("[data-skin-edit]");
    const del = e.target.closest("[data-skin-delete]");
    if (!edit && !del) return;
    e.preventDefault();
    closeMenus();
    if (edit) openEdit(edit);
    else deleteOne(del);
  });

  // ── Select mode ──────────────────────────────────────────────
  const toggle = document.getElementById("skin-select-toggle");
  const bar = document.getElementById("skin-select-bar");
  const count = document.getElementById("skin-select-count");
  const selectAll = document.getElementById("skin-select-all");
  const deleteSelected = document.getElementById("skin-select-delete");
  const selected = new Set();

  function cards() {
    return [...grid.querySelectorAll(".bv-skin-card")];
  }

  function render() {
    cards().forEach((card) => {
      const on = selected.has(card.dataset.id);
      card.classList.toggle("selected", on);
      card.setAttribute("aria-selected", on ? "true" : "false");
    });
    count.textContent = `${selected.size} selected`;
    deleteSelected.disabled = selected.size === 0;
    selectAll.textContent = selected.size === cards().length ? "Clear selection" : "Select all on this page";
  }

  function setSelectMode(on) {
    grid.classList.toggle("select-mode", on);
    bar.hidden = !on;
    if (toggle) {
      toggle.setAttribute("aria-pressed", on ? "true" : "false");
      toggle.textContent = on ? "Done" : "Select";
    }
    selected.clear();
    cards().forEach((card) => {
      if (on) { card.setAttribute("role", "option"); card.tabIndex = 0; }
      else { card.removeAttribute("role"); card.removeAttribute("tabindex"); card.removeAttribute("aria-selected"); }
    });
    grid.setAttribute("aria-multiselectable", on ? "true" : "false");
    if (on) grid.setAttribute("role", "listbox"); else grid.removeAttribute("role");
    closeMenus();
    render();
  }

  function flip(card) {
    const id = card.dataset.id;
    selected.has(id) ? selected.delete(id) : selected.add(id);
    render();
  }

  if (toggle) toggle.addEventListener("click", () => setSelectMode(!grid.classList.contains("select-mode")));
  document.getElementById("skin-select-done").addEventListener("click", () => setSelectMode(false));

  grid.addEventListener("click", (e) => {
    if (!grid.classList.contains("select-mode")) return;
    const card = e.target.closest(".bv-skin-card");
    if (!card || e.target.closest("a.bv-details-link, .bv-creator a")) return;
    e.preventDefault();
    flip(card);
  });
  grid.addEventListener("keydown", (e) => {
    if (!grid.classList.contains("select-mode") || (e.key !== " " && e.key !== "Enter")) return;
    const card = e.target.closest(".bv-skin-card");
    if (!card) return;
    e.preventDefault();
    flip(card);
  });

  selectAll.addEventListener("click", () => {
    const all = cards();
    if (selected.size === all.length) selected.clear();
    else all.forEach((c) => selected.add(c.dataset.id));
    render();
  });

  deleteSelected.addEventListener("click", () => {
    const ids = [...selected];
    const n = ids.length;
    askDelete(`Delete ${n} skin${n === 1 ? "" : "s"}?`, "They disappear from Bonkverse for everyone. This can't be undone.", async () => {
      const body = new URLSearchParams();
      ids.forEach((id) => body.append("skin_ids", id));
      const { ok, json } = await BVApi.post(root.dataset.bulkDeleteUrl, body);
      if (!ok || !json.ok) { toast("Those didn't delete. Try again in a minute.", "error"); return; }
      const done = json.data.deleted_ids.map(String);
      removeCards(done);
      setSelectMode(false);
      toast(`Deleted ${done.length} skin${done.length === 1 ? "" : "s"}.`);
    });
  });

  // Back/forward cache can bring the page back mid-selection: start clean.
  window.addEventListener("pageshow", () => setSelectMode(false));
})();
