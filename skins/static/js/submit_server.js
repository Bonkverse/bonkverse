// submit_server.js: the "Submit a Discord server" page (skins/submit_server.html).
// Clicking a tag bubble selects it; each selected tag is sent as a hidden
// "tags" field.

(function () {
  "use strict";

  const selected = new Set();
  const selectedTagsDiv = document.getElementById("selected-tags");

  document.querySelectorAll(".selectable-tag").forEach((tag) => {
    tag.addEventListener("click", () => {
      const name = tag.dataset.tag;
      if (selected.has(name)) {
        selected.delete(name);
        tag.classList.remove("active");
      } else {
        selected.add(name);
        tag.classList.add("active");
      }

      selectedTagsDiv.replaceChildren(
        ...[...selected].map((t) => {
          const input = document.createElement("input");
          input.type = "hidden";
          input.name = "tags";
          input.value = t;
          return input;
        })
      );
    });
  });
})();
