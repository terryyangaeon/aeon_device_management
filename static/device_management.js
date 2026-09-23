// Device Management page — Site filter applies to BOTH laptops and SIMs

let allLaptops = [];
let allSims    = [];
let selectedSite = "";   // empty = all

// ── Mapping helpers ────────────────────────────────────────────
// Laptop "category" formats:
//   "ADG-HK-BO"           → "BO"
//   "ADG-HK-Site-CHT"     → "CHT"
//   "ADG-HK-Site-PWH"     → "PWH"
// SIM "contract_site":
//   "PWH", "MC6", "MC6 " (trim), etc.
function categoryToSite(cat) {
    if (!cat) return null;
    cat = String(cat).trim();
    if (cat === "ADG-HK-BO") return "BO";
    if (cat.startsWith("ADG-HK-Site-")) return cat.substring("ADG-HK-Site-".length);
    if (cat.startsWith("ADG-HK-")) return cat.substring("ADG-HK-".length);
    return cat;   // fallback — display as-is
}
// Aliases — different naming for the same site between the two source tables
const SITE_ALIASES = {
    "MC6": "BO",         // SIM "MC6" maps to laptop "BO" (same site, different code in each table)
};

// Site display names — used as the title prefix when filter is active
const SITE_NAMES = {
    "BO":   {en: "Back Office",          zh: "總辦工室"},
    "CHT":  {en: "Cross Harbour Tunnel", zh: "紅磡海底隧道"},
    "KTT":  {en: "Kai Tak Tunnel",       zh: "啓德隧道"},
    "KWH":  {en: "Kwong Wah Hospital",   zh: "廣華醫院"},
    "LRT":  {en: "Lion Rock Tunnel",     zh: "獅子山隧道"},
    "PWH":  {en: "Prince of Wales",      zh: "威爾斯親王醫院"},
    "SMT":  {en: "Shing Mun Tunnel",     zh: "城門隧道"},
    "TKOT": {en: "Tseung Kwan O Tunnel", zh: "將軍澳隧道"},
    "TKOK": {en: "Tseung Kwan O Tunnel", zh: "將軍澳隧道"},   // alias if any source ever uses TKOK
};

const BASE_TITLE_ZH = "電腦及SIM卡管理";
const BASE_TITLE_EN = "Laptops & SIM Card Management";

function updateTitle() {
    const h1 = document.querySelector(".header-center h1");
    const h2 = document.querySelector(".header-center h2");
    if (!h1 || !h2) return;

    if (!selectedSite) {
        h1.textContent = BASE_TITLE_ZH;
        h2.textContent = BASE_TITLE_EN;
        return;
    }
    const friendly = SITE_NAMES[selectedSite];
    if (friendly) {
        h1.textContent = friendly.zh + BASE_TITLE_ZH;
        h2.textContent = friendly.en + " " + BASE_TITLE_EN;
    } else {
        // Unknown site (e.g. TKOT) — fall back to showing site code as prefix
        h1.textContent = selectedSite + " " + BASE_TITLE_ZH;
        h2.textContent = selectedSite + " " + BASE_TITLE_EN;
    }
}
function simSite(r) {
    if (!r.contract_site) return null;
    const s = String(r.contract_site).trim();
    return SITE_ALIASES[s] || s;
}
function laptopSite(r) {
    return categoryToSite(r.category);
}

// ── Load ───────────────────────────────────────────────────────
async function load() {
    try {
        const r = await fetch("/api/device-management", { cache: "no-store" });
        const j = await r.json();
        if (!j.ok) throw new Error(j.message || "API error");
        allLaptops = j.data.laptops || [];
        allSims    = j.data.sims    || [];
        buildSitePills();
        const ls = j.data.last_synced;
        document.getElementById("last-synced").textContent =
            ls ? new Date(ls).toLocaleString() : "Never synced";
        render();
    } catch (e) {
        console.error(e);
        document.getElementById("last-synced").textContent = "Error: " + e.message;
    }
}

// ── Build pills: union of laptop-derived sites + SIM contract_sites ──
function buildSitePills() {
    const lapCounts = {};
    allLaptops.forEach(r => {
        const s = laptopSite(r) || "(none)";
        lapCounts[s] = (lapCounts[s] || 0) + 1;
    });
    const simCounts = {};
    allSims.forEach(r => {
        const s = simSite(r) || "(none)";
        simCounts[s] = (simCounts[s] || 0) + 1;
    });
    const allSites = new Set([...Object.keys(lapCounts), ...Object.keys(simCounts)]);
    allSites.delete("(none)");   // drop blank-site bucket from the visible pill row
    const sortedSites = [...allSites].sort();

    const container = document.getElementById("category-pills");
    container.innerHTML = "";

    // "All" pill
    container.appendChild(makePill(
        "All 全部",
        `${allLaptops.length}💻 / ${allSims.length}📱`,
        ""
    ));

    sortedSites.forEach(site => {
        const lc = lapCounts[site] || 0;
        const sc = simCounts[site] || 0;
        container.appendChild(makePill(
            site,
            `${lc}💻 / ${sc}📱`,
            site
        ));
    });
    updateActivePill();
}

function makePill(label, count, value) {
    const btn = document.createElement("button");
    btn.className = "category-pill";
    btn.dataset.site = value;
    btn.innerHTML = `${escapeHtml(label)} <span class="pill-count">${count}</span>`;
    btn.addEventListener("click", () => {
        selectedSite = value;
        updateActivePill();
        render();
    });
    return btn;
}

function updateActivePill() {
    document.querySelectorAll(".category-pill").forEach(p => {
        p.classList.toggle("active", (p.dataset.site || "") === selectedSite);
    });
}

// ── Render ─────────────────────────────────────────────────────
function render() {
    updateTitle();

    // Filter laptops + SIMs by selected site
    const laptops = selectedSite
        ? allLaptops.filter(r => laptopSite(r) === selectedSite)
        : allLaptops.slice();

    const sims = selectedSite
        ? allSims.filter(r => simSite(r) === selectedSite)
        : allSims.slice();

    // ── Laptops ──
    const isSpared = r => {
        const n = (r.primary_user_display_name || "").trim().toLowerCase();
        return n === "" || n === "-" || n.includes("spare");
    };
    const sparedRows = laptops.filter(isSpared);

    document.getElementById("laptop-total").textContent  = laptops.length;
    document.getElementById("laptop-spared").textContent = sparedRows.length;

    const sparedTbody = document.getElementById("spared-tbody");
    sparedTbody.innerHTML = "";
    if (sparedRows.length === 0) {
        sparedTbody.innerHTML = `<tr><td colspan="3" class="empty-row">—</td></tr>`;
    } else {
        sparedRows.forEach(r => {
            const tr = document.createElement("tr");
            tr.innerHTML = `<td>${esc(r.manufacturer)}</td><td title="${escAttr(r.model)}">${esc(r.model)}</td><td>${esc(r.serial_number)}</td>`;
            sparedTbody.appendChild(tr);
        });
    }

    const lt = document.getElementById("laptop-tbody");
    lt.innerHTML = "";
    if (laptops.length === 0) {
        lt.innerHTML = `<tr><td colspan="7" class="empty-row">No laptops at this site.</td></tr>`;
    } else {
        laptops.forEach(r => {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td>${esc(r.serial_number)}</td>
                <td>${esc(r.device_name)}</td>
                <td>${esc(r.manufacturer)}</td>
                <td title="${escAttr(r.model)}">${esc(r.model)}</td>
                <td>${esc(r.primary_user_display_name)}</td>
                <td>${fmtDate(r.enrollment_date)}</td>
                <td>${esc(r.status) || ''}</td>
            `;
            lt.appendChild(tr);
        });
    }

    // ── SIMs ──
    document.getElementById("sim-total").textContent    = sims.length;
    const expiring30 = sims.filter(r =>
        r.count_day_of_sim_contract_end !== null &&
        r.count_day_of_sim_contract_end <= 30).length;
    document.getElementById("sim-expiring").textContent = expiring30;

    const st = document.getElementById("sim-tbody");
    st.innerHTML = "";
    if (sims.length === 0) {
        st.innerHTML = `<tr><td colspan="8" class="empty-row">No SIMs at this site.</td></tr>`;
    } else {
        sims.forEach(r => {
            const days = r.count_day_of_sim_contract_end;
            const daysClass = (days !== null && days <= 30) ? "alert-text" :
                              (days !== null && days <= 90) ? "warn-text"  : "";
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td>${esc(r.telcom)}</td>
                <td>${esc(r.sim_no)}</td>
                <td>${esc(r.contract_no)}</td>
                <td>${r.monthly_fee != null ? r.monthly_fee : '—'}</td>
                <td>${esc(r.sim_owner)}</td>
                <td>${fmtDate(r.contract_start_date)}</td>
                <td>${fmtDate(r.contract_end_date)}</td>
                <td class="${daysClass}">${days != null ? days : '—'}</td>
            `;
            st.appendChild(tr);
        });
    }
}

function esc(v) {
    if (v === null || v === undefined) return "—";
    return escapeHtml(String(v));
}
function escAttr(v) { return v == null ? "" : String(v).replace(/"/g, "&quot;"); }
function escapeHtml(s) {
    return s.replace(/[&<>"']/g, c => ({
        '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
}
function fmtDate(v) {
    if (!v) return "—";
    try { return new Date(v).toISOString().slice(0, 10); } catch (e) { return v; }
}

document.getElementById("refresh-btn").addEventListener("click", load);

// ── Excel upload ──────────────────────────────────────────────
const uploadBtn   = document.getElementById("upload-btn");
const uploadInput = document.getElementById("upload-input");
uploadBtn.addEventListener("click", () => uploadInput.click());

uploadInput.addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    if (!confirm(`Upload "${file.name}" and replace all device-management data?`)) {
        uploadInput.value = "";
        return;
    }

    const origText = uploadBtn.textContent;
    uploadBtn.disabled = true;
    uploadBtn.textContent = "⏳ Uploading…";

    try {
        const fd = new FormData();
        fd.append("file", file);
        const r = await fetch("/api/device-management/upload", { method: "POST", body: fd });
        const j = await r.json();
        if (!j.ok) throw new Error(j.message || `HTTP ${r.status}`);
        alert(`✅ Sync complete\n\nLaptops: ${j.laptops_count}\nSIM Cards: ${j.sims_count}`);
        await load();
    } catch (err) {
        alert(`❌ Upload failed:\n\n${err.message}`);
        console.error(err);
    } finally {
        uploadBtn.disabled = false;
        uploadBtn.textContent = origText;
        uploadInput.value = "";   // reset so same file can be uploaded again
    }
});

load();
