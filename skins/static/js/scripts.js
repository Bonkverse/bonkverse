function showImage(imageUrl) {
    let modal = document.getElementById("imageModal");
    let zoomedImage = document.getElementById("zoomedImage");
    zoomedImage.src = imageUrl;
    modal.style.display = "flex"; // Show modal
}

function closeImage() {
    document.getElementById("imageModal").style.display = "none"; // Hide modal
}

document.addEventListener("DOMContentLoaded", function () {
    let notifications = document.querySelectorAll(".notification");
    notifications.forEach(notification => {
        setTimeout(() => {
            notification.style.opacity = "0";
            setTimeout(() => { notification.style.display = "none"; }, 500);
        }, 4000);
    });
});

// Marquee speed control: lower = faster (seconds for a full loop)
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.carousel').forEach(el => {
    const speed = Number(el.dataset.speed || 20); // seconds
    const track = el.querySelector('.carousel-track');
    if (track) track.style.animationDuration = `${speed}s`;
  });
});

// ── Mobile overlay: open / close ─────────────────────────────
const navToggle     = document.getElementById('nav-toggle');
const mobileOverlay = document.getElementById('mobile-overlay');
const mobileClose   = document.getElementById('mobile-close');

function openOverlay() {
    mobileOverlay.classList.add('open');
    document.body.style.overflow = 'hidden'; // prevent background scroll
}

function closeOverlay() {
    mobileOverlay.classList.remove('open');
    document.body.style.overflow = '';
}

if (navToggle)    navToggle.addEventListener('click', openOverlay);
if (mobileClose)  mobileClose.addEventListener('click', closeOverlay);

// Close on Escape key
document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeOverlay();
});

// ── Mobile dropdowns: toggle on click ────────────────────────
const mobileTriggers = document.querySelectorAll('.mobile-dropdown-trigger');

mobileTriggers.forEach(function (trigger) {
    trigger.addEventListener('click', function () {
        const item = this.closest('.mobile-nav-item');

        // Close all other open items
        mobileTriggers.forEach(function (other) {
            const otherItem = other.closest('.mobile-nav-item');
            if (otherItem !== item) {
                otherItem.classList.remove('open');
            }
        });

        item.classList.toggle('open');
    });
});

// ── Desktop dropdown: still driven by CSS hover ───────────────
// (no JS needed — handled by .nav-item:hover .dropdown-menu in CSS)