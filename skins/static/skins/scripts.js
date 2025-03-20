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

