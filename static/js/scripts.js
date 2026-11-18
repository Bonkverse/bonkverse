document.addEventListener("DOMContentLoaded", function () {
    let notifications = document.querySelectorAll(".notification");
    notifications.forEach(notification => {
        setTimeout(() => {
            notification.style.opacity = "0";
            setTimeout(() => { notification.style.display = "none"; }, 500);
        }, 4000);
    });
});
