function showImage(imageUrl) {
    let modal = document.getElementById("imageModal");
    let zoomedImage = document.getElementById("zoomedImage");
    zoomedImage.src = imageUrl;
    modal.style.display = "flex"; // Show modal
}

function closeImage() {
    document.getElementById("imageModal").style.display = "none"; // Hide modal
}
