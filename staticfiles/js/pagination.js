// static/js/pagination.js
// Renders the same themed pagination used site-wide, for AJAX-driven
// search pages. Mirrors the Django partial's markup/classes exactly.
const BVPagination = (function () {
  const JUMP_THRESHOLD = 5; // matches the threshold in pagination.html

  function elidedRange(current, totalPages, onEachSide = 1, onEnds = 1) {
    if (totalPages <= onEachSide * 2 + onEnds * 2 + 1) {
      return Array.from({ length: totalPages }, (_, i) => i + 1);
    }
    const pages = new Set();
    for (let i = 1; i <= onEnds; i++) pages.add(i);
    for (let i = totalPages - onEnds + 1; i <= totalPages; i++) pages.add(i);
    for (let i = current - onEachSide; i <= current + onEachSide; i++) {
      if (i >= 1 && i <= totalPages) pages.add(i);
    }
    const sorted = Array.from(pages).sort((a, b) => a - b);
    const out = [];
    let prev = null;
    for (const p of sorted) {
      if (prev !== null && p - prev > 1) out.push('…');
      out.push(p);
      prev = p;
    }
    return out;
  }

  function render(container, { page, pageSize, total, onNavigate }) {
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    container.innerHTML = '';
    if (totalPages <= 1) return;

    const nav = document.createElement('nav');
    nav.className = 'bv-pagination';
    nav.setAttribute('aria-label', 'Pagination');

    const prev = document.createElement('button');
    prev.type = 'button';
    prev.className = 'page-nav' + (page <= 1 ? ' disabled' : '');
    prev.textContent = '‹ Prev';
    prev.addEventListener('click', () => { if (page > 1) onNavigate(page - 1); });
    nav.appendChild(prev);

    elidedRange(page, totalPages).forEach(num => {
      if (num === '…') {
        const span = document.createElement('span');
        span.className = 'page-ellipsis';
        span.textContent = '…';
        nav.appendChild(span);
        return;
      }
      const isActive = num === page;
      const btn = document.createElement(isActive ? 'span' : 'button');
      btn.className = 'page-btn' + (isActive ? ' active' : '');
      btn.textContent = num;
      if (!isActive) {
        btn.type = 'button';
        btn.addEventListener('click', () => onNavigate(num));
      }
      nav.appendChild(btn);
    });

    const next = document.createElement('button');
    next.type = 'button';
    next.className = 'page-nav' + (page >= totalPages ? ' disabled' : '');
    next.textContent = 'Next ›';
    next.addEventListener('click', () => { if (page < totalPages) onNavigate(page + 1); });
    nav.appendChild(next);

    // "Go to page" — only past the same threshold the server-rendered
    // partial uses, so small result sets (like a filtered player search)
    // don't get a jump input they'll never need.
    if (totalPages > JUMP_THRESHOLD) {
      const wrap = document.createElement('div');
      wrap.className = 'page-jump-form';

      const label = document.createElement('span');
      label.className = 'page-jump-label';
      label.textContent = 'Go to';
      wrap.appendChild(label);

      const input = document.createElement('input');
      input.type = 'number';
      input.className = 'page-jump-input';
      input.min = '1';
      input.max = String(totalPages);
      input.value = String(page);
      input.setAttribute('aria-label', 'Jump to page');
      input.addEventListener('keydown', e => {
        if (e.key !== 'Enter') return;
        const target = parseInt(input.value, 10);
        if (!isNaN(target) && target >= 1 && target <= totalPages) {
          onNavigate(target);
        }
      });
      wrap.appendChild(input);

      nav.appendChild(wrap);
    }

    container.appendChild(nav);

    const meta = document.createElement('div');
    meta.className = 'bv-pagination-meta';
    const start = total === 0 ? 0 : (page - 1) * pageSize + 1;
    const end = Math.min(page * pageSize, total);
    meta.textContent = `Showing ${start}–${end} of ${total}`;
    container.appendChild(meta);
  }

  return { render };
})();

// Wires up the "Go to page" input that appears in the shared
// pagination partial once a page count crosses the threshold set
// in pagination.html. Works for any server-rendered paginated page —
// navigates via a real URL, since these pages aren't AJAX-driven.
// Pages marked data-ajax handle their own jump input via a delegated
// listener scoped to their swappable container (see my_profile.html),
// so this skips those to avoid double-binding.
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.page-jump-input').forEach(input => {
    if (input.closest('[data-ajax]')) return;
    input.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter') return;
      const target = parseInt(input.value, 10);
      const max = parseInt(input.max, 10);
      if (isNaN(target) || target < 1 || target > max) return;
      const baseQs = input.dataset.baseQs;
      const url = new URL(window.location.href);
      if (baseQs) {
        new URLSearchParams(baseQs).forEach((v, k) => url.searchParams.set(k, v));
      }
      url.searchParams.set('page', target);
      window.location.href = url.pathname + '?' + url.searchParams.toString();
    });
  });
});