// players_directory.js — the Players page (players/directory.html)
//
// The advanced-search rule builder: one line per rule,
// [Where / AND / OR] [field] [condition] [value] [×]. Picking a field swaps
// in its conditions and value box (text, number, year, list); "between"
// adds a second value. Lines can be added (up to the limit) and removed.
// Field names are numbered c0 f0 o0 v0 w0 k0, c1 f1 … as players/search.py
// reads them; on submit, blank lines and default values are left out so the
// address stays short.
//
// Data (#qb-state, from players/selectors.py _builder):
//   fields: [{key, label, value: text|number|year|choice|none,
//             ops: [{key, label}], choices?: [{key, label}], min?, max?, unit?}]
//   rules:  [{conn, field, op, value, value2, case}]
//   max:    how many lines are allowed
//
// Without JavaScript the server-drawn lines still submit; picking another
// field then shows its conditions after Search.

(function () {
  "use strict";

  const form = document.querySelector("[data-dir-form]");
  if (!form) return;

  // Leave blank and default fields out of the address.
  form.addEventListener("submit", () => {
    form.querySelectorAll("[data-rule]").forEach((row) => {
      const value = row.querySelector('[name^="v"]');
      if (value && value.value === "") {
        row.querySelectorAll("input, select").forEach((el) => { el.disabled = true; });
      }
    });
    form.querySelectorAll("input, select").forEach((el) => {
      if (!el.name || el.name === "view" || el.disabled) return;
      if (el.type === "checkbox" && !el.checked) return;
      if (el.value === "") el.disabled = true;
    });
  });
  window.addEventListener("pageshow", () => {
    form.querySelectorAll(":disabled").forEach((el) => { el.disabled = false; });
  });

  const stateEl = document.getElementById("qb-state");
  const list = form.querySelector("[data-rules]");
  const addBtn = form.querySelector("[data-add]");
  if (!stateEl || !list || !addBtn) return;

  const { fields, max } = JSON.parse(stateEl.textContent);
  const byKey = Object.fromEntries(fields.map((f) => [f.key, f]));
  let rules = JSON.parse(stateEl.textContent).rules;

  function el(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === false || v == null) continue;
      if (k === "class") e.className = v;
      else if (k === "text") e.textContent = v;
      else if (v === true) e.setAttribute(k, "");
      else e.setAttribute(k, v);
    }
    e.append(...kids.filter(Boolean));
    return e;
  }
  const hidden = (text) => el("span", { class: "pv-visually-hidden", text });
  function select(name, options, current, label, extraClass) {
    const s = el("select", { name });
    options.forEach((o) => s.append(el("option", { value: o.key, text: o.label, selected: o.key === current })));
    return el("label", { class: `pv-qb__select${extraClass ? " " + extraClass : ""}` }, hidden(label), s);
  }

  function defaults(field) {
    const spec = byKey[field];
    const first = spec.choices ? spec.choices[0].key : "";
    return { op: spec.ops[0].key, value: first, value2: first, case: false };
  }

  function valueCell(rule, i) {
    const spec = byKey[rule.field];
    const cell = el("div", { class: "pv-qb__value" });
    const between = rule.op === "between";
    if (spec.value === "text") {
      cell.append(
        el("label", { class: "pv-qb__input" }, hidden("Value"),
          el("input", { type: "text", name: `v${i}`, value: rule.value, placeholder: "Text", maxlength: "100", autocomplete: "off", autocapitalize: "off", spellcheck: "false" })),
        el("label", { class: "pv-qb__case", title: "Match case" },
          el("input", { type: "checkbox", name: `k${i}`, value: "1", checked: !!rule.case }),
          el("span", { text: "Aa" }), hidden("Match case")),
      );
    } else if (spec.value === "number") {
      const num = (name, v, label) => el("label", { class: "pv-qb__input pv-qb__input--num" }, hidden(label),
        el("input", { type: "number", name, value: v, min: spec.min, max: spec.max, inputmode: "numeric" }));
      cell.append(num(`v${i}`, rule.value, "Value"));
      if (between) cell.append(el("span", { class: "pv-qb__and", text: "and" }), num(`w${i}`, rule.value2, "Second value"));
      if (spec.unit) cell.append(el("span", { class: "pv-qb__unit", text: spec.unit }));
    } else if (spec.value === "year" || spec.value === "choice") {
      cell.append(select(`v${i}`, spec.choices, rule.value, "Value"));
      if (between) cell.append(el("span", { class: "pv-qb__and", text: "and" }), select(`w${i}`, spec.choices, rule.value2, "Second value"));
    }
    return cell;
  }

  function row(rule, i) {
    const spec = byKey[rule.field];
    const conn = el("div", { class: "pv-qb__conn" });
    if (i === 0) conn.append(el("span", { class: "pv-qb__where", text: "Where" }));
    else conn.append(select(`c${i}`, [{ key: "and", label: "AND" }, { key: "or", label: "OR" }], rule.conn, "Join with", "pv-qb__select--conn"));
    const remove = el("button", { type: "button", class: "pv-qb__remove", "aria-label": "Remove this rule", text: "×" });
    const li = el("li", { class: "pv-qb__rule", "data-rule": true },
      conn,
      select(`f${i}`, fields, rule.field, "Field", "pv-qb__field"),
      select(`o${i}`, spec.ops, rule.op, "Condition", "pv-qb__op"),
      valueCell(rule, i),
      remove,
    );
    li.dataset.index = String(i);
    return li;
  }

  function render(focusIndex) {
    list.replaceChildren(...rules.map(row));
    addBtn.hidden = rules.length >= max;
    if (focusIndex != null) {
      const target = list.children[focusIndex];
      const input = target && (target.querySelector('[name^="v"]') || target.querySelector('[name^="f"]'));
      if (input) input.focus();
    }
  }

  // Keep `rules` in step with what's typed, and redraw a line when its
  // field or condition changes.
  list.addEventListener("input", (e) => sync(e.target, false));
  list.addEventListener("change", (e) => sync(e.target, true));
  function sync(target, redraw) {
    const li = target.closest("[data-rule]");
    if (!li || !target.name) return;
    const i = Number(li.dataset.index);
    const rule = rules[i];
    const kind = target.name[0];
    if (kind === "c") rule.conn = target.value;
    else if (kind === "v") rule.value = target.value;
    else if (kind === "w") rule.value2 = target.value;
    else if (kind === "k") rule.case = target.checked;
    else if (kind === "f" && redraw) {
      Object.assign(rule, { field: target.value }, defaults(target.value));
      li.replaceWith(row(rule, i));
      list.children[i].querySelector('[name^="o"]').focus();
    } else if (kind === "o" && redraw) {
      const was = rule.op;
      rule.op = target.value;
      if ((was === "between") !== (rule.op === "between")) {
        li.replaceWith(row(rule, i));
        list.children[i].querySelector('[name^="o"]').focus();
      }
    }
  }

  list.addEventListener("click", (e) => {
    const btn = e.target.closest(".pv-qb__remove");
    if (!btn) return;
    const i = Number(btn.closest("[data-rule]").dataset.index);
    rules.splice(i, 1);
    if (!rules.length) rules.push({ conn: "and", field: "name", ...defaults("name") });
    render(Math.min(i, rules.length - 1));
  });

  addBtn.hidden = false;
  addBtn.addEventListener("click", () => {
    if (rules.length >= max) return;
    rules.push({ conn: "and", field: "name", ...defaults("name") });
    render(rules.length - 1);
  });

  render();
})();
