// upload.js: the upload page (skins/upload.html).
// Checks the form before it's sent, then swaps it for the "Uploading…" note.

(function () {
  "use strict";

  const form = document.getElementById("upload-form");
  const errorMessage = document.getElementById("error-message");
  const BONKLEAGUES_URL = /^https:\/\/bonkleagues\.io\/s\/[A-Za-z0-9]{7}$/;

  function refuse(text) {
    errorMessage.innerText = text;
    errorMessage.hidden = false;
  }

  form.addEventListener("submit", (e) => {
    const skinName = document.getElementById("skin_name").value.trim();
    const link = document.getElementById("bonkleagues_link").value.trim();

    let problem = null;
    if (!skinName || !link) problem = "All fields are required.";
    else if (skinName.length > 1000) problem = "Skin name must be under 1000 characters.";
    else if (!BONKLEAGUES_URL.test(link)) problem = "Invalid Bonkleagues link format.";

    if (problem) {
      e.preventDefault();
      refuse(problem);
      return;
    }
    document.getElementById("loading").hidden = false;
    form.hidden = true;
  });
})();
