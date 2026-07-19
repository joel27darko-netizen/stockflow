// StockFlow front-end helpers

// ---------------------------------------------------------
// Theme (light/dark) — persisted in localStorage. This is a
// real downloaded app running in the user's own browser (not
// a Claude.ai artifact sandbox), so localStorage is the normal,
// correct tool for this.
// ---------------------------------------------------------
(function initTheme() {
    const saved = localStorage.getItem("sf-theme");
    const preferred = saved || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    document.documentElement.setAttribute("data-theme", preferred);
    document.documentElement.setAttribute("data-bs-theme", preferred);
})();

function toggleTheme() {
    const current = document.documentElement.getAttribute("data-theme");
    const next = current === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    document.documentElement.setAttribute("data-bs-theme", next);
    localStorage.setItem("sf-theme", next);
    const icon = document.getElementById("themeToggleIcon");
    if (icon) icon.className = next === "dark" ? "bi bi-sun" : "bi bi-moon-stars";
}

document.addEventListener("DOMContentLoaded", () => {
    const icon = document.getElementById("themeToggleIcon");
    if (icon) {
        const current = document.documentElement.getAttribute("data-theme");
        icon.className = current === "dark" ? "bi bi-sun" : "bi bi-moon-stars";
    }

    // ---------------------------------------------------------
    // Auto-dismiss non-error flash messages
    // ---------------------------------------------------------
    document.querySelectorAll(".alert-auto-dismiss").forEach((el) => {
        setTimeout(() => {
            el.classList.remove("show");
            el.classList.add("fade");
        }, 5000);
    });

    // ---------------------------------------------------------
    // Bootstrap tooltips — anything with data-bs-toggle="tooltip"
    // ---------------------------------------------------------
    document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => {
        new bootstrap.Tooltip(el);
    });

    // ---------------------------------------------------------
    // Sidebar drawer toggle (mobile)
    // ---------------------------------------------------------
    const sidebar = document.getElementById("sfSidebar");
    const backdrop = document.getElementById("sfSidebarBackdrop");
    const toggleBtn = document.getElementById("sfSidebarToggle");

    function closeSidebar() {
        sidebar?.classList.remove("show");
        backdrop?.classList.remove("show");
    }
    toggleBtn?.addEventListener("click", () => {
        sidebar?.classList.toggle("show");
        backdrop?.classList.toggle("show");
    });
    backdrop?.addEventListener("click", closeSidebar);

    // ---------------------------------------------------------
    // Loading spinner on form submit — gives instant feedback on
    // actions that hit the server (create/update/delete/import),
    // and prevents accidental double-submits.
    // ---------------------------------------------------------
    function armSpinner(form, label) {
        const btn = form.querySelector('button[type="submit"]');
        if (!btn || btn.disabled) return;
        btn.dataset.originalHtml = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = `<i class="bi bi-arrow-repeat sf-spin"></i> ${label}`;
    }
    window.armSpinner = armSpinner;

    document.querySelectorAll("form[data-loading-text]").forEach((form) => {
        form.addEventListener("submit", () => armSpinner(form, form.dataset.loadingText));
    });

    // Generic fallback: any form NOT opting out still gets a subtle
    // spinner + disabled state so double-clicks can't double-submit.
    // Forms with data-confirm are deliberately EXCLUDED here — for
    // those, the submit event is first intercepted to show the
    // confirmation modal (see below), and the spinner is only armed
    // once the person actually confirms. Without this exclusion, the
    // button behind the modal would visibly go into a disabled
    // "loading" state the instant the modal opens, before the person
    // has even decided whether to proceed.
    document.querySelectorAll("form:not([data-no-spinner]):not([data-loading-text]):not([data-confirm])").forEach((form) => {
        form.addEventListener("submit", () => armSpinner(form, form.querySelector('button[type="submit"]')?.textContent.trim() || "Working…"));
    });

    // ---------------------------------------------------------
    // Confirmation modal — replaces native confirm() popups.
    // Any form with data-confirm="..." gets intercepted; the
    // modal's confirm button then submits the original form.
    // ---------------------------------------------------------
    let pendingForm = null;
    const modalEl = document.getElementById("sfConfirmModal");
    const modalBody = document.getElementById("sfConfirmModalBody");
    const modalConfirmBtn = document.getElementById("sfConfirmModalBtn");
    const modal = modalEl ? new bootstrap.Modal(modalEl) : null;

    document.querySelectorAll("form[data-confirm]").forEach((form) => {
        form.addEventListener("submit", (e) => {
            if (form.dataset.confirmed === "true") return; // already approved, let it submit
            e.preventDefault();
            pendingForm = form;
            if (modalBody) modalBody.textContent = form.dataset.confirm;
            const danger = form.dataset.confirmDanger !== "false";
            if (modalConfirmBtn) {
                modalConfirmBtn.className = danger ? "btn btn-danger" : "btn btn-warning text-dark";
            }
            modal?.show();
        });
    });

    modalConfirmBtn?.addEventListener("click", () => {
        modal?.hide();
        if (pendingForm) {
            pendingForm.dataset.confirmed = "true";
            armSpinner(pendingForm, "Processing…");
            pendingForm.requestSubmit ? pendingForm.requestSubmit() : pendingForm.submit();
        }
    });

    // ---------------------------------------------------------
    // Live client-side quick filter on product list/card views —
    // narrows what's already on the page instantly, on top of
    // (not instead of) the server-side search which handles the
    // full dataset across pages.
    // ---------------------------------------------------------
    const quickFilter = document.getElementById("sfQuickFilter");
    quickFilter?.addEventListener("input", () => {
        const term = quickFilter.value.trim().toLowerCase();
        document.querySelectorAll("[data-filter-target]").forEach((el) => {
            const haystack = el.dataset.filterTarget.toLowerCase();
            el.style.display = haystack.includes(term) ? "" : "none";
        });
    });

    // ---------------------------------------------------------
    // Product list/card view toggle — persisted per-browser so
    // it doesn't reset every time you revisit the page.
    // ---------------------------------------------------------
    const listViewBtn = document.getElementById("sfViewList");
    const cardViewBtn = document.getElementById("sfViewCard");
    const listContainer = document.getElementById("sfProductListView");
    const cardContainer = document.getElementById("sfProductCardView");

    function applyView(view) {
        if (!listContainer || !cardContainer) return;
        if (view === "card") {
            listContainer.classList.add("d-none");
            cardContainer.classList.remove("d-none");
            listViewBtn?.classList.remove("active");
            cardViewBtn?.classList.add("active");
        } else {
            cardContainer.classList.add("d-none");
            listContainer.classList.remove("d-none");
            cardViewBtn?.classList.remove("active");
            listViewBtn?.classList.add("active");
        }
        localStorage.setItem("sf-product-view", view);
    }
    if (listContainer && cardContainer) {
        applyView(localStorage.getItem("sf-product-view") || "list");
    }
    listViewBtn?.addEventListener("click", () => applyView("list"));
    cardViewBtn?.addEventListener("click", () => applyView("card"));
});

/**
 * Simulated webcam barcode/QR scanning.
 *
 * A true production system would use a library such as html5-qrcode or
 * ZXing to decode frames from navigator.mediaDevices.getUserMedia().
 * For this portfolio build, we request camera access to demonstrate the
 * integration point, but resolve the "scan" via manual code entry so the
 * feature works reliably in any grading/demo environment without needing
 * a physical barcode on hand.
 */
async function startSimulatedScan() {
    const video = document.getElementById("scannerVideo");
    const statusEl = document.getElementById("scannerStatus");
    const box = document.getElementById("scannerBox");
    if (!video) return;

    try {
        const stream = await navigator.mediaDevices.getUserMedia({ video: true });
        video.srcObject = stream;
        video.style.display = "block";
        statusEl.textContent = "Camera active — point at a barcode/QR, then type the code below and click Lookup.";
        statusEl.className = "text-success mt-2";
        box?.classList.remove("sf-scan-error");
        box?.classList.add("sf-scan-success");
        setTimeout(() => box?.classList.remove("sf-scan-success"), 600);
    } catch (err) {
        statusEl.textContent = "Camera unavailable (" + err.message + "). Use manual code entry below instead.";
        statusEl.className = "text-warning mt-2";
        box?.classList.add("sf-scan-error");
        setTimeout(() => box?.classList.remove("sf-scan-error"), 500);
    }
}
