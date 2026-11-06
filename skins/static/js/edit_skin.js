// edit_skin.js: the edit skin page (skins/edit_skin.html).
// Tag inputs for each label group, filled from the skin's current labels
// (#initial-labels, a json_script), and packed into the hidden "labels"
// field when the form is saved.

(function () {
  "use strict";

  const initialLabels = JSON.parse(document.getElementById("initial-labels").textContent);

  function addTag(container, text) {
    const tag = document.createElement("span");
    tag.className = "tag-bubble";
    tag.textContent = text;

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.textContent = "×";
    removeBtn.addEventListener("click", () => tag.remove());

    tag.appendChild(removeBtn);
    container.insertBefore(tag, container.lastChild);
  }

  function getTags(name) {
    const container = document.querySelector(`.tags-container[data-name="${name}"]`);
    return Array.from(container.querySelectorAll(".tag-bubble")).map((tag) =>
      tag.childNodes[0].nodeValue.trim()
    );
  }

  document.querySelectorAll(".tags-container").forEach((container) => {
    const name = container.dataset.name;
    const input = document.createElement("input");
    input.type = "text";
    input.placeholder = "Type and press Enter...";
    input.className = "tag-input";
    container.appendChild(input);

    (initialLabels[name] || []).forEach((tag) => addTag(container, tag));

    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === ",") {
        e.preventDefault();
        const value = input.value.trim();
        if (value) {
          addTag(container, value);
          input.value = "";
        }
      }
    });
  });

  document.getElementById("edit-skin-form").addEventListener("submit", () => {
    const labels = {
      style: document.getElementById("style").value.trim(),
      colors: getTags("colors"),
      objects: getTags("objects"),
      themes: getTags("themes"),
      references: getTags("references"),
    };
    document.getElementById("labels").value = JSON.stringify(labels);
  });
})();
