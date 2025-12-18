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


