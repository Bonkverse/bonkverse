// my_profile.js — behavior for the My Profile page (my_profile.html)
// Card behavior (menu, zoom, Wear) is static/core/js/bv-cards.js; this file
// adds the tabs, paging, select mode, Edit and Delete.
// Reads the URLs it needs from data attributes on #profile-routes,
// since a plain static file can't use Django's {% url %} tag.

const ROUTES = (() => {
  const el = document.getElementById('profile-routes');
  return {
    skinsPartial: el?.dataset.skinsPartialUrl || '',
    bulkDelete:   el?.dataset.bulkDeleteUrl   || '',
    friendSync:   el?.dataset.friendSyncUrl   || '',
  };
})();

// ── Friend sync progress (right after a login that started a sync) ──
// The server sets data-friend-sync on #profile-routes when there's one to show.
if (document.getElementById('profile-routes')?.dataset.friendSync) {
  const handle = BVToast.show("Syncing your friends\u2026", { type: "info", spinner: true, sticky: true });
  let attempts = 0;
  const poll = () => {
    attempts++;
    fetch(ROUTES.friendSync, { headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then((r) => r.json())
      .then((data) => {
        if (data.status === "done") {
          let friendsText = "Synced " + data.friends_now + " friends";
          const extras = [];
          if (data.added_edges > 0) extras.push(data.added_edges + " new");
          if (data.removed_edges > 0) extras.push(data.removed_edges + " removed");
          if (extras.length) friendsText += " : " + extras.join(", ");

          if (data.corrected_count > 0) {
            // Only this case stays up until the user closes it; every
            // other toast on the page keeps its normal auto-dismiss.
            const fixes = data.corrected_usernames.map((c) => '"' + c.old_username + '" → "' + c.new_username + '"');
            handle.update(
              friendsText + ". Also fixed " + data.corrected_count +
              " outdated username(s) from before a data cleanup: " + fixes.join(", "),
              { type: "success", sticky: true }
            );
          } else {
            handle.update(friendsText, { type: "success" });
          }
          return;
        }
        if (attempts < 10) {
          setTimeout(poll, 1200);
        } else {
          handle.update("Friend sync is taking longer than usual", { type: "info" });
        }
      })
      .catch(() => handle.dismiss());
  };
  setTimeout(poll, 1200);
}

// The My Skins grid is replaced wholesale on every AJAX page swap, so
// nothing should hold a stale reference to it — always look it up fresh.
function getSkinsGrid() {
  return document.getElementById('skins-grid');
}

// ── Tabs ────────────────────────────────────────────────────
document.querySelectorAll('.profile-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.profile-tab').forEach(t => t.classList.toggle('active', t === tab));
    document.querySelectorAll('.profile-panel').forEach(p => p.classList.toggle('active', p.id === 'panel-' + tab.dataset.tab));
  });
});

// ── My Skins: instant pagination (no full page reload) ───────────────
//
// Selecting cards to bulk-delete only makes sense if navigating between
// pages doesn't wipe the selection. A normal <a href="?page=2"> reloads
// the whole page, destroying all JS state (select mode, selected ids)
// along with it. Fetching just the card grid + pagination and swapping
// it in keeps everything else — including selectedIds below — alive.
const skinsPanelBody = document.getElementById('skins-panel-body');
const skinsPanelWrap = document.getElementById('skins-panel-wrap');

let skinsPageLoading = false;

function showSkinsLoading() {
  if (skinsPanelWrap.querySelector('.skins-loading-overlay')) return;
  const overlay = document.createElement('div');
  overlay.className = 'skins-loading-overlay';
  overlay.innerHTML = '<div class="spinner-pos"><div class="spinner-lg"></div></div>';
  skinsPanelWrap.appendChild(overlay);
}

function hideSkinsLoading() {
  skinsPanelWrap.querySelector('.skins-loading-overlay')?.remove();
}

async function loadSkinsPage(page) {
  if (skinsPageLoading) return; // ignore clicks while a page is already loading
  skinsPageLoading = true;
  showSkinsLoading();

  const url = `${ROUTES.skinsPartial}?page=${page}`;
  let html;
  try {
    const r = await fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
    if (!r.ok) throw new Error('bad status');
    html = await r.text();
  } catch (err) {
    BVToast.show('Failed to load page.', { type: 'error' });
    skinsPageLoading = false;
    hideSkinsLoading();
    return;
  }
  skinsPanelBody.innerHTML = html;
  skinsPageLoading = false;
  hideSkinsLoading();
  if (window.lucide) lucide.createIcons();

  // Re-apply select mode + any selections that were made on other pages —
  // the grid element itself is brand new, so neither survives the swap
  // automatically; selectedIds (a plain JS Set) does, since it was never
  // attached to the old DOM in the first place.
  const grid = getSkinsGrid();
  if (grid) {
    grid.classList.toggle('select-mode', selectMode);
    grid.querySelectorAll('.bv-skin-card').forEach(card => {
      card.classList.toggle('selected', selectedIds.has(card.dataset.id));
    });
  }
  updateBulkBar();

  document.getElementById('panel-skins')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// Intercept pagination link clicks inside My Skins and load via fetch
// instead of letting the browser navigate.
skinsPanelBody.addEventListener('click', (e) => {
  const link = e.target.closest('.site-pagination a');
  if (!link) return;
  e.preventDefault();
  const page = new URL(link.href).searchParams.get('page') || 1;
  loadSkinsPage(page);
});

// Same for the "Go to page" jump input, when it appears on this panel.
skinsPanelBody.addEventListener('keydown', (e) => {
  const input = e.target.closest('.page-jump-input');
  if (!input || e.key !== 'Enter') return;
  const target = parseInt(input.value, 10);
  const max = parseInt(input.max, 10);
  if (isNaN(target) || target < 1 || target > max) return;
  loadSkinsPage(target);
});

// A card's ⋯ menu (opened by ui/ui.js) closes when one of its items opens a modal.
function closeCardMenu(item) {
  const menu = item.closest('.bv-menu');
  if (!menu) return;
  menu.hidden = true;
  document.querySelector(`[aria-controls="${menu.id}"]`)?.setAttribute('aria-expanded', 'false');
}

// ── Select mode ─────────────────────────────────────────────
const selectToggle    = document.getElementById('select-toggle-btn');
const bulkBar         = document.getElementById('bulk-bar');
const bulkCountLabel  = document.getElementById('bulk-count-label');
const bulkDeleteBtn   = document.getElementById('bulk-delete-btn');
const bulkCancelBtn   = document.getElementById('bulk-cancel-btn');

let selectMode = false;
let selectedIds = new Set(); // skin ids — deliberately NOT tied to any page's DOM

function updateBulkBar() {
  bulkCountLabel.textContent = `${selectedIds.size} selected`;
  bulkDeleteBtn.disabled = selectedIds.size === 0;
}

function setSelectMode(on) {
  selectMode = on;
  selectedIds.clear();
  const grid = getSkinsGrid();
  grid?.classList.toggle('select-mode', on);
  selectToggle?.classList.toggle('active', on);
  if (selectToggle) selectToggle.textContent = on ? 'Done' : 'Select';
  bulkBar.classList.toggle('open', on);
  document.body.classList.toggle('bulk-bar-open', on);
  grid?.querySelectorAll('.bv-skin-card.selected').forEach(c => c.classList.remove('selected'));
  updateBulkBar();
}

selectToggle?.addEventListener('click', () => setSelectMode(!selectMode));
bulkCancelBtn.addEventListener('click', () => setSelectMode(false));

// Force a clean, closed state on every load, and again whenever the
// page is restored from the mobile back/forward cache (bfcache) —
// which can bring back old DOM state (an open bulk bar, active select
// mode) without re-running any of this script.
setSelectMode(false);
window.addEventListener('pageshow', (e) => {
  if (e.persisted) setSelectMode(false);
});

// Delegated on document (not the grid element directly) so it keeps
// working after the grid is replaced by an AJAX page swap.
document.addEventListener('click', e => {
  if (!selectMode) return;
  const grid = getSkinsGrid();
  if (!grid) return;
  const card = e.target.closest('.bv-skin-card');
  if (!card || !grid.contains(card)) return;
  const id = card.dataset.id;
  if (selectedIds.has(id)) {
    selectedIds.delete(id);
    card.classList.remove('selected');
  } else {
    selectedIds.add(id);
    card.classList.add('selected');
  }
  updateBulkBar();
});

// ── Delete modal (shared: single-skin + bulk) ────────────────
const deleteModal      = document.getElementById('delete-modal');
const deleteModalTitle = document.getElementById('delete-modal-title');
const deleteModalBody  = document.getElementById('delete-modal-body');
const deleteConfirmBtn = document.getElementById('delete-confirm-btn');

let deleteMode = null;      // 'single' | 'bulk'
let deleteActionUrl = null; // for single

function openSingleDeleteModal(action, name) {
  deleteMode = 'single';
  deleteActionUrl = action;
  deleteModalTitle.textContent = 'Delete Skin';
  // Built from nodes, not innerHTML: the skin name is user text.
  const strong = document.createElement('strong');
  strong.textContent = `"${name}"`;
  deleteModalBody.replaceChildren('Are you sure you want to delete ', strong, '? This cannot be undone.');
  deleteModal.classList.add('open');
  document.body.style.overflow = 'hidden';
}

function openBulkDeleteModal() {
  deleteMode = 'bulk';
  const n = selectedIds.size;
  deleteModalTitle.textContent = n === 1 ? 'Delete 1 Skin' : `Delete ${n} Skins`;
  deleteModalBody.textContent = `Are you sure you want to delete ${n} skin${n === 1 ? '' : 's'}? This cannot be undone.`;
  deleteModal.classList.add('open');
  document.body.style.overflow = 'hidden';
}

function closeDeleteModal() {
  deleteModal.classList.remove('open');
  document.body.style.overflow = '';
  deleteMode = null;
}

document.getElementById('delete-modal-close').addEventListener('click', closeDeleteModal);
document.getElementById('delete-cancel-btn').addEventListener('click', closeDeleteModal);
deleteModal.addEventListener('click', e => { if (e.target === deleteModal) closeDeleteModal(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeDeleteModal(); closeEditModal(); } });

// Delegated (not bound at page load) so it works on cards added by
// AJAX paging, not just the ones present on the very first render.
document.addEventListener('click', (e) => {
  const btn = e.target.closest('.card-delete-btn');
  if (!btn) return;
  e.stopPropagation();
  closeCardMenu(btn);
  openSingleDeleteModal(btn.dataset.action, btn.dataset.name);
});

bulkDeleteBtn.addEventListener('click', () => {
  if (selectedIds.size === 0) return;
  openBulkDeleteModal();
});

function removeCardFromDOM(id) {
  const card = document.querySelector(`.bv-skin-card[data-id="${id}"]`);
  card?.remove();
}

// Keeps the header stat and the "My Skins N" tab count in sync with
// what's actually been deleted, since both are only rendered once from
// server data at page load and nothing else refreshes them.
function decrementSkinsCount(n) {
  if (n <= 0) return;
  const statEl = document.getElementById('stat-total-skins');
  const tabEl  = document.getElementById('tab-count-skins');
  if (statEl) statEl.textContent = Math.max(0, parseInt(statEl.textContent, 10) - n);
  if (tabEl)  tabEl.textContent  = Math.max(0, parseInt(tabEl.textContent, 10) - n);
}

deleteConfirmBtn.addEventListener('click', async () => {
  if (deleteMode === 'single') {
    const { ok, json } = await BVApi.post(deleteActionUrl);
    if (ok && json.ok) {
      removeCardFromDOM(json.deleted_ids[0]);
      selectedIds.delete(String(json.deleted_ids[0]));
      updateBulkBar();
      decrementSkinsCount(json.deleted_ids.length);
      BVToast.show('Skin deleted', { type: 'success' });
    } else {
      BVToast.show('Failed to delete skin.', { type: 'error' });
    }
  } else if (deleteMode === 'bulk') {
    const params = new URLSearchParams();
    selectedIds.forEach(id => params.append('skin_ids', id));
    const { ok, json } = await BVApi.post(ROUTES.bulkDelete, params);
    if (ok && json.ok) {
      // Removes cards for whichever deleted ids happen to be on the
      // currently displayed page; ids from other pages were still
      // deleted server-side and simply won't be present here.
      json.deleted_ids.forEach(id => removeCardFromDOM(id));
      decrementSkinsCount(json.deleted_ids.length);
      BVToast.show(`Deleted ${json.deleted_ids.length} skin${json.deleted_ids.length === 1 ? '' : 's'}`, { type: 'success' });
      setSelectMode(false);
    } else {
      BVToast.show('Failed to delete skins.', { type: 'error' });
    }
  }
  closeDeleteModal();
});

// ── Edit modal ──────────────────────────────────────────────
const editModal    = document.getElementById('edit-modal');
const editFeedback = document.getElementById('edit-feedback');
let editSkinId  = null;
let editAction  = null;

function addEditTag(container, text) {
  const tag = document.createElement('span');
  tag.className = 'tag-bubble';
  tag.textContent = text;

  const removeBtn = document.createElement('button');
  removeBtn.type = 'button';
  removeBtn.textContent = '×';
  removeBtn.onclick = () => tag.remove();

  tag.appendChild(removeBtn);
  container.insertBefore(tag, container.lastChild);
}

function getEditTags(name) {
  const container = document.querySelector(`#edit-modal .tags-container[data-name="${name}"]`);
  return Array.from(container.querySelectorAll('.tag-bubble'))
    .map(tag => tag.childNodes[0].nodeValue.trim());
}

function openEditModal(trigger) {
  const data = trigger.dataset;
  editSkinId = data.skinId;
  editAction = data.action;

  document.getElementById('edit-preview-img').src   = data.image || '/static/images/default_skin.png';
  document.getElementById('edit-name').value        = data.name || '';
  document.getElementById('edit-description').value = data.description || '';
  document.getElementById('edit-style').value       = data.style || '';
  editFeedback.textContent = '';
  editFeedback.className   = 'modal-feedback';

  let labels = {};
  try { labels = JSON.parse(data.labels || '{}'); } catch (e) {}

  document.querySelectorAll('#edit-modal .tags-container').forEach(container => {
    container.innerHTML = '';
    const input = document.createElement('input');
    input.type = 'text';
    input.placeholder = 'Type and press Enter…';
    container.appendChild(input);

    const name = container.dataset.name;
    (labels[name] || []).forEach(tag => addEditTag(container, tag));

    input.addEventListener('keydown', ev => {
      if (ev.key === 'Enter' || ev.key === ',') {
        ev.preventDefault();
        const value = input.value.trim();
        if (value) { addEditTag(container, value); input.value = ''; }
      }
    });
  });

  editModal.classList.add('open');
  document.body.style.overflow = 'hidden';
  lucide.createIcons();
}

function closeEditModal() {
  editModal.classList.remove('open');
  document.body.style.overflow = '';
}

document.getElementById('edit-modal-close').addEventListener('click', closeEditModal);
document.getElementById('edit-cancel-btn').addEventListener('click', closeEditModal);
editModal.addEventListener('click', e => { if (e.target === editModal) closeEditModal(); });

// Delegated for the same reason as delete — cards from AJAX-loaded
// pages didn't exist when the page first loaded.
document.addEventListener('click', (e) => {
  const trigger = e.target.closest('.edit-skin-trigger');
  if (!trigger) return;
  e.stopPropagation();
  closeCardMenu(trigger);
  openEditModal(trigger);
});

async function saveEditSkin() {
  editFeedback.textContent = 'Saving…';
  editFeedback.className   = 'modal-feedback';

  const labels = {
    style:      document.getElementById('edit-style').value.trim(),
    colors:     getEditTags('colors'),
    objects:    getEditTags('objects'),
    themes:     getEditTags('themes'),
    references: getEditTags('references'),
  };

  const { ok, json } = await BVApi.post(editAction, {
    name:        document.getElementById('edit-name').value,
    description: document.getElementById('edit-description').value,
    labels:      JSON.stringify(labels),
  });

  if (!ok || !json.ok) {
    editFeedback.textContent = '❌ ' + (json.error || 'Failed to save.');
    editFeedback.className   = 'modal-feedback error';
    return;
  }

  const card = document.querySelector(`.bv-skin-card[data-id="${editSkinId}"]`);
  if (card) {
    card.querySelector('.bv-skin-card__title').textContent = json.skin.name;

    const trigger = card.querySelector('.edit-skin-trigger');
    if (trigger) {
      trigger.dataset.name        = json.skin.name;
      trigger.dataset.description = json.skin.description;
      trigger.dataset.style       = json.skin.labels.style || '';
      trigger.dataset.labels      = JSON.stringify(json.skin.labels);
    }
  }

  BVToast.show('Skin updated', { type: 'success' });
  closeEditModal();
}

document.getElementById('edit-save-btn').addEventListener('click', saveEditSkin);
