// map_decoder.js — the map decoder (site_pages/map_decoder.html).
// Sends the pasted map string to the decode endpoint (the form's
// data-decode-url) and shows the JSON with a short summary. Copying is
// ui.js's data-bv-copy; this only enables the button once there's JSON.

(function () {
  "use strict";

  const form = document.querySelector("[data-decode-form]");
  if (!form) return;
  const input = document.getElementById("encoded");
  const out = document.querySelector("[data-out] code");
  const errorEl = form.querySelector("[data-error]");
  const statusEl = form.querySelector("[data-status]");
  const summary = document.querySelector("[data-summary]");
  const copy = document.querySelector("[data-copy]");
  const decode = form.querySelector("[data-decode]");

  function reset() {
    errorEl.textContent = "";
    statusEl.textContent = "";
    input.removeAttribute("aria-invalid");
    summary.replaceChildren();
    summary.hidden = true;
    copy.disabled = true;
  }

  function fail(message) {
    errorEl.textContent = message;
    input.setAttribute("aria-invalid", "true");
    statusEl.textContent = "";
  }

  function showSummary(map) {
    const physics = map.physics || {};
    const count = (list) => (Array.isArray(list) ? list.length : 0);
    const facts = [
      ["Name", map.m && map.m.n],
      ["Author", map.m && map.m.a],
      ["Version", map.v],
      ["Pixels per metre", physics.ppm],
      ["Shapes", count(physics.shapes)],
      ["Fixtures", count(physics.fixtures)],
      ["Bodies", count(physics.bodies)],
      ["Joints", count(physics.joints)],
      ["Spawns", count(map.spawns)],
      ["Capture zones", count(map.capZones)],
    ];
    summary.replaceChildren(...facts
      .filter(([, value]) => value !== undefined && value !== null && value !== "")
      .map(([label, value]) => {
        const li = document.createElement("li");
        li.className = "bv-pill";
        const name = document.createElement("span");
        name.className = "md-summary__label";
        name.textContent = label;
        li.append(name, document.createTextNode(String(value)));
        return li;
      }));
    summary.hidden = !summary.children.length;
  }

  form.querySelector("[data-clear]").addEventListener("click", () => {
    input.value = "";
    out.textContent = "{}";
    reset();
    input.focus();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    reset();
    const encoded = input.value.trim();
    if (!encoded) { fail("Paste a map string first."); return; }

    statusEl.textContent = "Decoding…";
    decode.disabled = true;
    decode.setAttribute("aria-busy", "true");
    const body = new FormData();
    body.append("encoded", encoded);
    try {
      const response = await fetch(form.dataset.decodeUrl, {
        method: "POST",
        body,
        headers: { "X-CSRFToken": window.BVApi ? window.BVApi.getCSRF() : "" },
        credentials: "same-origin",
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        const detail = data && data.details ? `: ${data.details}` : "";
        fail(data && data.error ? `${data.error}${detail}` : "That map string couldn't be decoded.");
        return;
      }
      out.textContent = JSON.stringify(data, null, 2);
      showSummary(data);
      copy.disabled = false;
      statusEl.textContent = "Decoded.";
    } catch (err) {
      fail("Couldn't reach Bonkverse. Check your connection and try again.");
    } finally {
      decode.disabled = false;
      decode.removeAttribute("aria-busy");
    }
  });
})();
