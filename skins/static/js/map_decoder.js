// map_decoder.js: the map decoder tool (tools/map_decoder.html).
// Sends a pasted map string to the decode endpoint (the decode button's
// data-decode-url) and shows the JSON with a short summary.

(function () {
  "use strict";

  const decodeBtn = document.getElementById("decodeBtn");
  const clearBtn = document.getElementById("clearBtn");
  const copyIcon = document.getElementById("copyIcon");
  const statusEl = document.getElementById("status");
  const encodedEl = document.getElementById("encoded");
  const outEl = document.getElementById("out");
  const errEl = document.getElementById("err");
  const summaryEl = document.getElementById("summary");

  function setStatus(text, variant) {
    statusEl.textContent = text;
    statusEl.dataset.variant = variant || "";
  }

  function pill(text) {
    const span = document.createElement("span");
    span.className = "summary-pill";
    span.textContent = text;
    return span;
  }

  function renderSummary(decoded) {
    summaryEl.innerHTML = "";
    try {
      summaryEl.appendChild(pill(`v: ${decoded.v}`));
      summaryEl.appendChild(pill(`name: ${decoded.m?.n ?? ""}`));
      summaryEl.appendChild(pill(`author: ${decoded.m?.a ?? ""}`));
      summaryEl.appendChild(pill(`ppm: ${decoded.physics?.ppm}`));
      summaryEl.appendChild(pill(`shapes: ${decoded.physics?.shapes?.length ?? 0}`));
      summaryEl.appendChild(pill(`fixtures: ${decoded.physics?.fixtures?.length ?? 0}`));
      summaryEl.appendChild(pill(`bodies: ${decoded.physics?.bodies?.length ?? 0}`));
      summaryEl.appendChild(pill(`joints: ${decoded.physics?.joints?.length ?? 0}`));
      summaryEl.appendChild(pill(`spawns: ${decoded.spawns?.length ?? 0}`));
      summaryEl.appendChild(pill(`capZones: ${decoded.capZones?.length ?? 0}`));
    } catch {}
  }

  function setCopyEnabled(enabled) {
    copyIcon.disabled = !enabled;
  }

  // Copy feedback: icon becomes check + label changes, then reverts
  function setCopiedState(on) {
    copyIcon.classList.toggle("copied", on);
  }

  async function copyOut() {
    try {
      await navigator.clipboard.writeText(outEl.textContent);
      setCopiedState(true);
      setTimeout(() => setCopiedState(false), 900);
    } catch {
      errEl.textContent = "Could not copy to clipboard.";
    }
  }

  clearBtn.addEventListener("click", () => {
    encodedEl.value = "";
    outEl.textContent = "{}";
    summaryEl.innerHTML = "";
    errEl.textContent = "";
    setCopyEnabled(false);
    setCopiedState(false);
    setStatus("Idle");
    encodedEl.focus();
  });

  copyIcon.addEventListener("click", copyOut);

  // nice UX: Enter decodes
  encodedEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      decodeBtn.click();
    }
  });

  decodeBtn.addEventListener("click", async () => {
    errEl.textContent = "";
    summaryEl.innerHTML = "";
    setCopyEnabled(false);
    setCopiedState(false);

    const encoded = encodedEl.value.trim();
    if (!encoded) {
      errEl.textContent = "Paste an encoded map string first.";
      return;
    }

    setStatus("Decoding...", "wait");

    const form = new FormData();
    form.append("encoded", encoded);

    try {
      const res = await fetch(decodeBtn.dataset.decodeUrl, {
        method: "POST",
        body: form,
        headers: { "X-CSRFToken": BVApi.getCSRF() },
      });

      const data = await res.json().catch(() => null);

      if (!res.ok) {
        setStatus("Error", "bad");
        const msg = data?.error ? `${data.error}${data.details ? " — " + data.details : ""}` : "Decode failed.";
        errEl.textContent = msg;
        outEl.textContent = JSON.stringify(data ?? { error: msg }, null, 2);
        return;
      }

      setStatus("Done", "good");
      outEl.textContent = JSON.stringify(data, null, 2);
      renderSummary(data);
      setCopyEnabled(true);

      document.querySelector(".out-card").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) {
      setStatus("Error", "bad");
      errEl.textContent = `Request failed: ${String(e)}`;
    }
  });
})();
