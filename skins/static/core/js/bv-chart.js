// core/js/bv-chart.js
//
// The one chart component for Bonkverse pages: responsive line/step charts
// and bar charts drawn as SVG at the container's real size, with axes and
// gridlines, a tooltip that follows the pointer (and flips away from the
// edges so it never covers what you're pointing at), and on line charts
// drag-to-zoom: press inside the chart, drag across a stretch, let go, and
// the chart shows only that stretch; "Reset zoom" goes back.
//
//   const chart = BVChart.line(el, { series, xType: "time", height: 380, zoom: true });
//   chart.update({ series });   chart.setDomain([x0, x1]);   chart.reset();
//   BVChart.bars(el, { bars: [{ label, value, highlight, tip }], height: 360 });
//
// Colors come from the series; everything else is styled by .bv-chart in
// css/charts.css. No dependencies.

(function (window) {
  "use strict";

  const NS = "http://www.w3.org/2000/svg";
  const PAD = { top: 16, right: 16, bottom: 30, left: 56 };
  const MONTHS = new Intl.DateTimeFormat(undefined, { month: "short", year: "numeric" });
  const DAYS = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });
  const FULL = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" });
  const YEARS = new Intl.DateTimeFormat(undefined, { year: "numeric" });
  const DAY = 86400000;

  function svg(tag, attrs, parent) {
    const el = document.createElementNS(NS, tag);
    for (const k in attrs) el.setAttribute(k, attrs[k]);
    if (parent) parent.append(el);
    return el;
  }
  function div(cls, parent) {
    const el = document.createElement("div");
    el.className = cls;
    if (parent) parent.append(el);
    return el;
  }
  const compact = (v) => {
    const a = Math.abs(v);
    if (a >= 1e6) return `${+(v / 1e6).toFixed(a >= 1e7 ? 0 : 1)}M`;
    if (a >= 1e4) return `${+(v / 1e3).toFixed(0)}k`;
    return Math.round(v).toLocaleString();
  };

  // ~count "nice" ticks (1, 2, 2.5, 5 × 10^n) covering [lo, hi].
  function niceTicks(lo, hi, count) {
    if (!(hi > lo)) return [lo];
    const raw = (hi - lo) / Math.max(1, count);
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || raw;
    const out = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(+v.toFixed(10));
    return out;
  }
  function timeTicks(t0, t1, count) {
    const span = t1 - t0;
    const out = [];
    if (span > 3 * 365 * DAY) {
      const y0 = new Date(t0).getFullYear(), y1 = new Date(t1).getFullYear();
      const step = Math.max(1, Math.ceil((y1 - y0) / count));
      for (let y = y0; y <= y1; y += step) { const t = new Date(y, 0, 1).getTime(); if (t >= t0 && t <= t1) out.push(t); }
      return { ticks: out, fmt: (t) => YEARS.format(t) };
    }
    if (span > 75 * DAY) {
      const d = new Date(t0); d.setDate(1);
      const months = Math.max(1, Math.round(span / (30.4 * DAY) / count));
      for (let m = new Date(d.getFullYear(), d.getMonth() + 1, 1); m.getTime() <= t1; m = new Date(m.getFullYear(), m.getMonth() + months, 1)) out.push(m.getTime());
      return { ticks: out, fmt: (t) => MONTHS.format(t) };
    }
    const step = Math.max(1, Math.round(span / DAY / count)) * DAY;
    for (let t = Math.ceil(t0 / DAY) * DAY; t <= t1; t += step) out.push(t);
    return { ticks: out, fmt: (t) => DAYS.format(t) };
  }

  // Value of a series at x: the last point at or before x (step), or the
  // straight line between neighbours.
  function valueAt(s, x) {
    const p = s.points;
    if (!p.length || x < p[0][0]) return null;
    let i = 0, lo = 0, hi = p.length - 1;
    while (lo <= hi) { const mid = (lo + hi) >> 1; if (p[mid][0] <= x) { i = mid; lo = mid + 1; } else hi = mid - 1; }
    const last = p.length - 1;
    if (i === last) return x === p[last][0] || s.extend ? p[last][1] : null;
    if (s.step) return p[i][1];
    const [x0, y0] = p[i], [x1, y1] = p[i + 1];
    return y0 + ((y1 - y0) * (x - x0)) / (x1 - x0 || 1);
  }

  function Base(el, opts) {
    el.classList.add("bv-chart");
    el.replaceChildren();
    this.el = el;
    this.opts = opts;
    this.svg = svg("svg", { class: "bv-chart__svg", role: "img", "aria-label": opts.label || "Chart" }, el);
    this.tip = div("bv-chart__tip", el);
    this.tip.hidden = true;
    this.empty = div("bv-chart__empty", el);
    this.empty.hidden = true;
    const ro = new ResizeObserver(() => this.render());
    ro.observe(el);
  }
  Base.prototype.size = function () {
    const w = Math.max(240, this.el.clientWidth);
    const small = w < 520;
    const h = small ? Math.round((this.opts.height || 360) * 0.75) : this.opts.height || 360;
    const pad = { ...PAD, left: small ? 44 : PAD.left };
    return { w, h, pad, iw: w - pad.left - pad.right, ih: h - pad.top - pad.bottom };
  };
  // Put the tooltip next to the pointer, on whichever side has room.
  Base.prototype.showTip = function (px, py, content) {
    const tip = this.tip;
    tip.replaceChildren();
    if (content.title) div("bv-chart__tip-title", tip).textContent = content.title;
    for (const r of content.rows || []) {
      const row = div("bv-chart__tip-row", tip);
      if (r.color) { const sw = document.createElement("span"); sw.className = "bv-chart__sw"; sw.style.setProperty("--c", r.color); row.append(sw); }
      const l = document.createElement("span"); l.textContent = r.label; row.append(l);
      if (r.value != null) { const v = document.createElement("strong"); v.textContent = r.value; row.append(v); }
    }
    tip.hidden = false;
    const w = this.el.clientWidth, h = this.el.clientHeight;
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    let x = px + 16, y = py + 16;
    if (x + tw > w - 4) x = px - tw - 16;
    if (y + th > h - 4) y = py - th - 16;
    tip.style.setProperty("--tx", `${Math.max(4, x)}px`);
    tip.style.setProperty("--ty", `${Math.max(4, y)}px`);
  };
  Base.prototype.hideTip = function () { this.tip.hidden = true; };
  Base.prototype.setEmpty = function (text) {
    this.empty.hidden = !text;
    this.empty.textContent = text || "";
  };
  Base.prototype.update = function (opts) { Object.assign(this.opts, opts); this.render(); };

  // ── Line / step chart ────────────────────────────────────────
  function Line(el, opts) {
    Base.call(this, el, opts);
    this.domain = null;
    this.reset_ = document.createElement("button");
    this.reset_.type = "button";
    this.reset_.className = "bv-chart__reset";
    this.reset_.textContent = "Reset zoom";
    this.reset_.hidden = true;
    this.reset_.addEventListener("click", () => this.reset());
    el.append(this.reset_);
    if (opts.zoom) {
      el.classList.add("bv-chart--zoom");
      const hint = div("bv-chart__hint", el);
      hint.textContent = "Drag across the chart to zoom in";
    }
    this.bind();
    this.render();
  }
  Line.prototype = Object.create(Base.prototype);

  Line.prototype.fullDomain = function () {
    if (this.opts.xDomain) return this.opts.xDomain;
    let a = Infinity, b = -Infinity;
    for (const s of this.opts.series || []) for (const [x] of s.points) { if (x < a) a = x; if (x > b) b = x; }
    if (!isFinite(a)) return null;
    return a === b ? [a - 1, b + 1] : [a, b];
  };
  Line.prototype.setDomain = function (d, silent) {
    this.domain = d;
    this.reset_.hidden = !d;
    this.render();
    if (!silent && this.opts.onZoom) this.opts.onZoom(this.currentDomain(), Boolean(d));
  };
  Line.prototype.reset = function () { this.setDomain(null); };
  Line.prototype.currentDomain = function () { return this.domain || this.fullDomain(); };

  Line.prototype.render = function () {
    const o = this.opts;
    const { w, h, pad, iw, ih } = this.size();
    this.geom = { w, h, pad, iw, ih };
    this.svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    this.svg.setAttribute("width", w);
    this.svg.setAttribute("height", h);
    this.svg.replaceChildren();
    const series = (o.series || []).filter((s) => s.points && s.points.length);
    const dom = this.currentDomain();
    if (!series.length || !dom) { this.setEmpty(o.emptyText || "Nothing to show yet."); return; }
    this.setEmpty("");
    const [x0, x1] = dom;

    // y range over what's visible
    let lo = Infinity, hi = -Infinity;
    for (const s of series) {
      const v0 = valueAt(s, x0);
      if (v0 != null) { lo = Math.min(lo, v0); hi = Math.max(hi, v0); }
      for (const [x, y] of s.points) if (x >= x0 && x <= x1) { lo = Math.min(lo, y); hi = Math.max(hi, y); }
    }
    for (const l of o.hlines || []) { lo = Math.min(lo, l.y); hi = Math.max(hi, l.y); }
    if (o.yMin != null) lo = Math.min(lo, o.yMin);
    if (!isFinite(lo)) { lo = 0; hi = 1; }
    if (hi === lo) { hi += 1; lo -= 1; }
    const padY = (hi - lo) * 0.06;
    lo = o.yFloor != null ? Math.max(o.yFloor, lo - padY) : lo - padY;
    hi += padY;
    const yt = niceTicks(lo, hi, ih > 220 ? 6 : 4);
    lo = Math.min(lo, yt[0]); hi = Math.max(hi, yt[yt.length - 1]);
    const X = (x) => pad.left + ((x - x0) / (x1 - x0)) * iw;
    const Y = (y) => pad.top + ih - ((y - lo) / (hi - lo)) * ih;
    this.scale = { X, Y, x0, x1, lo, hi };

    const grid = svg("g", { class: "bv-chart__grid" }, this.svg);
    const yf = o.yFormat || compact;
    for (const v of yt) {
      svg("line", { x1: pad.left, x2: pad.left + iw, y1: Y(v), y2: Y(v) }, grid);
      svg("text", { x: pad.left - 8, y: Y(v) + 4, "text-anchor": "end", class: "bv-chart__tick" }, grid).textContent = yf(v);
    }
    const xt = o.xType === "time" ? timeTicks(x0, x1, Math.max(2, Math.floor(iw / 110))) : { ticks: niceTicks(x0, x1, Math.max(2, Math.floor(iw / 90))), fmt: o.xFormat || compact };
    const xf = o.xFormat || xt.fmt;
    for (const t of xt.ticks) {
      if (t < x0 || t > x1) continue;
      svg("line", { x1: X(t), x2: X(t), y1: pad.top + ih, y2: pad.top + ih + 5, class: "bv-chart__xtick" }, grid);
      svg("text", { x: X(t), y: h - 8, "text-anchor": "middle", class: "bv-chart__tick" }, grid).textContent = xf(t);
    }

    const clipId = `bvc${Math.random().toString(36).slice(2, 8)}`;
    const defs = svg("defs", {}, this.svg);
    svg("rect", { x: pad.left, y: pad.top - 4, width: iw, height: ih + 8 }, svg("clipPath", { id: clipId }, defs));
    const plot = svg("g", { "clip-path": `url(#${clipId})` }, this.svg);

    for (const l of o.hlines || []) {
      svg("line", { x1: pad.left, x2: pad.left + iw, y1: Y(l.y), y2: Y(l.y), class: "bv-chart__hline" }, plot);
      if (l.label) svg("text", { x: pad.left + iw - 6, y: Y(l.y) - 6, "text-anchor": "end", class: "bv-chart__hlabel" }, plot).textContent = l.label;
    }
    for (const s of series) {
      const pts = [];
      let prev = null;
      for (const [x, y] of s.points) {
        if (s.step && prev != null) pts.push(`${X(x).toFixed(1)},${Y(prev).toFixed(1)}`);
        pts.push(`${X(x).toFixed(1)},${Y(y).toFixed(1)}`);
        prev = y;
      }
      if (s.step && s.extend && prev != null && s.points[s.points.length - 1][0] < x1) pts.push(`${X(x1).toFixed(1)},${Y(prev).toFixed(1)}`);
      if (s.area) {
        svg("polygon", { points: `${X(s.points[0][0]).toFixed(1)},${pad.top + ih} ${pts.join(" ")} ${pts.length ? pts[pts.length - 1].split(",")[0] : 0},${pad.top + ih}`, class: "bv-chart__area", style: `--c: ${s.color}` }, plot);
      }
      svg("polyline", { points: pts.join(" "), class: `bv-chart__line${s.dashed ? " bv-chart__line--dashed" : ""}`, style: `--c: ${s.color}` }, plot);
    }
    for (const m of o.markers || []) {
      if (m.x < x0 || m.x > x1) continue;
      svg("circle", { cx: X(m.x), cy: Y(m.y), r: 6, class: "bv-chart__marker", style: `--c: ${m.color || "#ffb454"}` }, plot);
      if (m.label) svg("text", { x: X(m.x), y: Y(m.y) - 12, "text-anchor": "middle", class: "bv-chart__mlabel" }, plot).textContent = m.label;
    }
    this.hover = svg("g", { class: "bv-chart__hover" }, this.svg);
    this.sel = svg("rect", { class: "bv-chart__sel", x: 0, y: pad.top, width: 0, height: ih }, this.svg);
    this.sel.style.display = "none";
  };

  Line.prototype.xAt = function (clientX) {
    const r = this.svg.getBoundingClientRect();
    const { pad, iw } = this.geom;
    const f = Math.min(1, Math.max(0, (clientX - r.left - pad.left) / iw));
    return { f, x: this.scale.x0 + f * (this.scale.x1 - this.scale.x0), px: clientX - r.left, py: 0 };
  };
  Line.prototype.drawHover = function (clientX, clientY) {
    if (!this.scale) return;
    const o = this.opts;
    const r = this.el.getBoundingClientRect();
    const { x } = this.xAt(clientX);
    const { X, Y } = this.scale;
    const { pad, ih } = this.geom;
    this.hover.replaceChildren();
    svg("line", { x1: X(x), x2: X(x), y1: pad.top, y2: pad.top + ih, class: "bv-chart__cross" }, this.hover);
    const rows = [];
    for (const s of o.series || []) {
      const v = valueAt(s, x);
      if (v == null) { rows.push({ label: s.name, value: "—", color: s.color }); continue; }
      svg("circle", { cx: X(x), cy: Y(v), r: 5, class: "bv-chart__dot", style: `--c: ${s.color}` }, this.hover);
      rows.push({ label: s.name, value: (o.tipValue || o.yFormat || ((n) => Math.round(n).toLocaleString()))(v, s), color: s.color });
    }
    const title = (o.tipTitle || (o.xType === "time" ? (t) => FULL.format(t) : (n) => Math.round(n).toLocaleString()))(x);
    this.showTip(clientX - r.left, clientY - r.top, o.tip ? o.tip(x) : { title, rows });
  };

  Line.prototype.bind = function () {
    let drag = null;
    const svgEl = this.svg;
    svgEl.addEventListener("pointerdown", (e) => {
      if (!this.scale || e.button > 0) return;
      const a = this.xAt(e.clientX);
      drag = { start: a, startClient: e.clientX, moved: false };
      if (this.opts.zoom) svgEl.setPointerCapture(e.pointerId);
      this.drawHover(e.clientX, e.clientY);
    });
    svgEl.addEventListener("pointermove", (e) => {
      if (!this.scale) return;
      if (drag && this.opts.zoom && Math.abs(e.clientX - drag.startClient) > 6) {
        drag.moved = true;
        const { pad } = this.geom;
        const r = svgEl.getBoundingClientRect();
        const a = Math.max(pad.left, Math.min(drag.startClient, e.clientX) - r.left);
        const b = Math.min(pad.left + this.geom.iw, Math.max(drag.startClient, e.clientX) - r.left);
        this.sel.style.display = "";
        this.sel.setAttribute("x", a);
        this.sel.setAttribute("width", Math.max(0, b - a));
      }
      this.drawHover(e.clientX, e.clientY);
    });
    const end = (e) => {
      if (drag && drag.moved && this.opts.zoom) {
        const a = drag.start.x, b = this.xAt(e.clientX).x;
        const lo = Math.min(a, b), hi = Math.max(a, b);
        const minSpan = this.opts.minZoom || (this.opts.xType === "time" ? 2 * DAY : 1);
        this.sel.style.display = "none";
        if (hi - lo >= minSpan) this.setDomain([lo, hi]);
      }
      drag = null;
    };
    svgEl.addEventListener("pointerup", end);
    svgEl.addEventListener("pointercancel", () => { drag = null; this.sel && (this.sel.style.display = "none"); });
    svgEl.addEventListener("pointerleave", (e) => {
      if (drag) return;
      if (e.pointerType === "mouse") { this.hover && this.hover.replaceChildren(); this.hideTip(); }
    });
  };

  // ── Bar chart ────────────────────────────────────────────────
  function Bars(el, opts) {
    Base.call(this, el, opts);
    this.svg.addEventListener("pointermove", (e) => this.pointAt(e));
    this.svg.addEventListener("pointerdown", (e) => this.pointAt(e));
    this.svg.addEventListener("pointerleave", (e) => { if (e.pointerType === "mouse") { this.hideTip(); this.highlight(-1); } });
    this.render();
  }
  Bars.prototype = Object.create(Base.prototype);
  Bars.prototype.render = function () {
    const o = this.opts;
    const { w, h, pad, iw, ih } = this.size();
    this.geom = { w, h, pad, iw, ih };
    this.svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    this.svg.setAttribute("width", w);
    this.svg.setAttribute("height", h);
    this.svg.replaceChildren();
    const bars = o.bars || [];
    if (!bars.length) { this.setEmpty(o.emptyText || "Nothing to show yet."); return; }
    this.setEmpty("");
    const log = o.yScale === "log";
    const f = (v) => (log ? Math.log10(1 + v) : v);
    const top = Math.max(...bars.map((b) => b.value), 1);
    const ticks = log
      ? [0, 1, 10, 100, 1000, 10000, 100000, 1000000].filter((v) => v <= top * 1.2)
      : niceTicks(0, top, ih > 220 ? 5 : 4);
    const hi = Math.max(f(top), f(ticks[ticks.length - 1])) * 1.04;
    const Y = (v) => pad.top + ih - (f(v) / hi) * ih;
    const grid = svg("g", { class: "bv-chart__grid" }, this.svg);
    for (const v of ticks) {
      svg("line", { x1: pad.left, x2: pad.left + iw, y1: Y(v), y2: Y(v) }, grid);
      svg("text", { x: pad.left - 8, y: Y(v) + 4, "text-anchor": "end", class: "bv-chart__tick" }, grid).textContent = (o.yFormat || compact)(v);
    }
    const n = bars.length;
    const slot = iw / n;
    const gap = Math.min(4, slot * 0.2);
    this.slot = slot;
    this.rects = bars.map((b, i) => {
      const y = Y(b.value);
      const rect = svg("rect", {
        x: pad.left + i * slot + gap / 2, y, width: Math.max(1, slot - gap), height: Math.max(b.value ? 2 : 0, pad.top + ih - y), rx: Math.min(4, slot / 4),
        class: `bv-chart__bar${b.highlight ? " is-here" : ""}`,
      }, this.svg);
      if (b.color) rect.style.setProperty("--c", b.color);
      return rect;
    });
    const every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(iw / 70))));
    bars.forEach((b, i) => {
      if ((o.labelAt ? !o.labelAt(b, i) : i % every) ) return;
      svg("text", { x: pad.left + i * slot + slot / 2, y: h - 8, "text-anchor": "middle", class: "bv-chart__tick" }, this.svg).textContent = b.label;
    });
    for (const m of o.markers || []) {
      const i = m.index;
      if (i < 0 || i >= n) continue;
      const x = pad.left + i * slot + slot / 2;
      svg("line", { x1: x, x2: x, y1: pad.top, y2: pad.top + ih, class: "bv-chart__vmark" }, this.svg);
      if (m.label) svg("text", { x: Math.min(x + 6, pad.left + iw - 4), y: pad.top + 12, "text-anchor": x + 120 > pad.left + iw ? "end" : "start", class: "bv-chart__mlabel" }, this.svg).textContent = m.label;
    }
  };
  Bars.prototype.highlight = function (i) {
    (this.rects || []).forEach((r, k) => r.classList.toggle("is-hover", k === i));
  };
  Bars.prototype.pointAt = function (e) {
    if (!this.geom) return;
    const r = this.svg.getBoundingClientRect();
    const i = Math.floor((e.clientX - r.left - this.geom.pad.left) / this.slot);
    const b = (this.opts.bars || [])[i];
    if (!b) { this.hideTip(); this.highlight(-1); return; }
    this.highlight(i);
    const er = this.el.getBoundingClientRect();
    this.showTip(e.clientX - er.left, e.clientY - er.top, b.tip || { title: b.label, rows: [{ label: "Value", value: b.value.toLocaleString() }] });
  };

  window.BVChart = {
    line: (el, opts) => new Line(el, opts),
    bars: (el, opts) => new Bars(el, opts),
    valueAt,
  };
})(window);
