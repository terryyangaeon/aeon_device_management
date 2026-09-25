// Shared top navbar burger menu — same open/close/position behaviour as OneView's.
(function () {
    var btn = document.getElementById("burgerBtn");
    var menu = document.getElementById("menu");
    if (!btn || !menu) return;

    function close() { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); }
    function place() {
        var br = btn.getBoundingClientRect();
        menu.style.top = (br.bottom + 6) + "px";
        menu.style.right = Math.max(8, window.innerWidth - br.right) + "px";
        menu.style.left = "auto";
    }
    btn.addEventListener("click", function (e) {
        e.stopPropagation();
        var show = menu.hidden;
        if (show) place();
        menu.hidden = !show;
        btn.setAttribute("aria-expanded", String(show));
    });
    window.addEventListener("resize", function () { if (!menu.hidden) place(); });
    document.addEventListener("click", function (e) { if (!menu.contains(e.target)) close(); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") close(); });
})();
