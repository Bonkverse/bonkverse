// upload.js: the upload page (skins/upload.html).
// Checks the form before it's sent, then swaps it for the "Uploading…" note.
// Opens the "Who made this skin?" dialog when the server asks.

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
    showLoading();
  });

  function showLoading() {
    document.getElementById("loading").hidden = false;
    form.hidden = true;
  }

  // "Who made this skin?": the server renders it when BonkLeagues credits
  // someone else (skins/views/upload.py); open it as a modal right away.
  const creatorCheck = document.getElementById("creator-check");
  if (creatorCheck && typeof creatorCheck.showModal === "function") {
    creatorCheck.showModal();
    document.getElementById("creator-check-form").addEventListener("submit", () => {
      creatorCheck.close();
      showLoading();
    });
  }
})();
