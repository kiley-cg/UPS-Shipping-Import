/* ── App Data ──────────────────────────────────────────────── */
const APPS = [
  {
    id: 1,
    name: "Metrics Dashboard",
    description: "Real-time KPIs, revenue trends, and cohort analysis across all products.",
    icon: "📊",
    iconBg: "#eef2ff",
    iconBgDark: "#1e1f3a",
    category: "analytics",
    status: "live",
    owner: "Data Team",
    url: "#",
  },
  {
    id: 2,
    name: "Deploy Console",
    description: "One-click deployments, rollbacks, and environment management.",
    icon: "🚀",
    iconBg: "#fef3c7",
    iconBgDark: "#29210a",
    category: "devtools",
    status: "live",
    owner: "Platform",
    url: "#",
  },
  {
    id: 3,
    name: "Expense Tracker",
    description: "Submit, approve, and track team expenses with policy checks built in.",
    icon: "💳",
    iconBg: "#ecfdf5",
    iconBgDark: "#0a1f16",
    category: "finance",
    status: "live",
    owner: "Finance",
    url: "#",
  },
  {
    id: 4,
    name: "Headcount Planner",
    description: "Model hiring scenarios, track headcount budget, and manage open roles.",
    icon: "👥",
    iconBg: "#f0fdf4",
    iconBgDark: "#0c1f0f",
    category: "hr",
    status: "live",
    owner: "People Ops",
    url: "#",
  },
  {
    id: 5,
    name: "Incident Board",
    description: "Track active incidents, assign owners, and post status page updates.",
    icon: "🔥",
    iconBg: "#fff1f2",
    iconBgDark: "#2a0a0d",
    category: "ops",
    status: "live",
    owner: "SRE",
    url: "#",
  },
  {
    id: 6,
    name: "Campaign Manager",
    description: "Plan, launch, and measure marketing campaigns across all channels.",
    icon: "📣",
    iconBg: "#fdf4ff",
    iconBgDark: "#1e0a24",
    category: "marketing",
    status: "live",
    owner: "Marketing",
    url: "#",
  },
  {
    id: 7,
    name: "Query Lab",
    description: "Write and share SQL queries against the data warehouse. No ETL needed.",
    icon: "🔬",
    iconBg: "#eff6ff",
    iconBgDark: "#0a1629",
    category: "devtools",
    status: "beta",
    owner: "Data Team",
    url: "#",
  },
  {
    id: 8,
    name: "AI Copilot",
    description: "Internal LLM assistant fine-tuned on your docs, wikis, and runbooks.",
    icon: "🤖",
    iconBg: "#f5f3ff",
    iconBgDark: "#12102a",
    category: "devtools",
    status: "beta",
    owner: "AI Team",
    url: "#",
  },
  {
    id: 9,
    name: "Invoice Generator",
    description: "Auto-generate client invoices from contract data and send via email.",
    icon: "🧾",
    iconBg: "#ecfdf5",
    iconBgDark: "#0a1f16",
    category: "finance",
    status: "beta",
    owner: "Finance",
    url: "#",
  },
  {
    id: 10,
    name: "Org Chart Builder",
    description: "Interactive org chart editor synced with your HRIS in real time.",
    icon: "🗂️",
    iconBg: "#fff7ed",
    iconBgDark: "#231608",
    category: "hr",
    status: "internal",
    owner: "People Ops",
    url: "#",
  },
  {
    id: 11,
    name: "Feature Flags",
    description: "Toggle features per user, segment, or environment without a deploy.",
    icon: "🚩",
    iconBg: "#fff1f2",
    iconBgDark: "#2a0a0d",
    category: "devtools",
    status: "internal",
    owner: "Platform",
    url: "#",
  },
  {
    id: 12,
    name: "Content Calendar",
    description: "Plan, schedule, and review content across blog, social, and email.",
    icon: "📅",
    iconBg: "#fdf4ff",
    iconBgDark: "#1e0a24",
    category: "marketing",
    status: "internal",
    owner: "Marketing",
    url: "#",
  },
];

/* ── State ─────────────────────────────────────────────────── */
let activeCategory = "all";
let activeStatus   = "all";
let searchQuery    = "";

/* ── Helpers ───────────────────────────────────────────────── */
function isDark() {
  return document.documentElement.getAttribute("data-theme") === "dark";
}

function statusLabel(s) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function buildCard(app) {
  const bg = isDark() ? app.iconBgDark : app.iconBg;

  return `
    <article class="app-card" data-id="${app.id}">
      <div class="card-header">
        <div class="app-icon" style="background:${bg}">${app.icon}</div>
        <span class="badge badge-${app.status}">${statusLabel(app.status)}</span>
      </div>
      <p class="app-name">${escape(app.name)}</p>
      <p class="app-desc">${escape(app.description)}</p>
      <div class="card-footer">
        <span class="app-meta">${escape(app.owner)}</span>
        <button class="btn-open" onclick="openApp(${app.id})">
          Open
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="2" y1="6" x2="10" y2="6"/>
            <polyline points="7,3 10,6 7,9"/>
          </svg>
        </button>
      </div>
    </article>
  `;
}

function escape(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* ── Render ────────────────────────────────────────────────── */
function render() {
  const q = searchQuery.trim().toLowerCase();

  const filtered = APPS.filter(app => {
    const matchCat    = activeCategory === "all" || app.category === activeCategory;
    const matchStatus = activeStatus === "all"   || app.status   === activeStatus;
    const matchSearch = !q ||
      app.name.toLowerCase().includes(q) ||
      app.description.toLowerCase().includes(q) ||
      app.owner.toLowerCase().includes(q);
    return matchCat && matchStatus && matchSearch;
  });

  const grid  = document.getElementById("appGrid");
  const empty = document.getElementById("emptyState");

  if (filtered.length === 0) {
    grid.innerHTML = "";
    empty.hidden = false;
  } else {
    empty.hidden = true;
    grid.innerHTML = filtered.map(buildCard).join("");
  }

  // Update page subtitle count
  document.getElementById("pageSubtitle").textContent =
    `${filtered.length} app${filtered.length !== 1 ? "s" : ""} available`;
}

/* ── Category nav ──────────────────────────────────────────── */
function initCategoryNav() {
  document.getElementById("categoryList").addEventListener("click", e => {
    const item = e.target.closest(".nav-item[data-category]");
    if (!item) return;
    e.preventDefault();

    const cat = item.dataset.category;
    if (cat === "recent" || cat === "favorites") {
      // placeholder — no data yet
      return;
    }

    activeCategory = cat;

    document.querySelectorAll(".nav-item[data-category]").forEach(el => {
      el.classList.toggle("active", el === item);
    });

    // Update page title
    const labels = {
      all: "All Apps", analytics: "Analytics", devtools: "Dev Tools",
      finance: "Finance", hr: "HR", ops: "Operations", marketing: "Marketing",
    };
    document.getElementById("pageTitle").textContent = labels[cat] ?? cat;

    render();
  });
}

/* ── Status filter tabs ────────────────────────────────────── */
function initFilterTabs() {
  document.querySelectorAll(".filter-tab").forEach(btn => {
    btn.addEventListener("click", () => {
      activeStatus = btn.dataset.status;
      document.querySelectorAll(".filter-tab").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      render();
    });
  });
}

/* ── Search ────────────────────────────────────────────────── */
function initSearch() {
  const input = document.getElementById("searchInput");

  input.addEventListener("input", () => {
    searchQuery = input.value;
    render();
  });

  // ⌘K / Ctrl+K focus shortcut
  document.addEventListener("keydown", e => {
    if ((e.metaKey || e.ctrlKey) && e.key === "k") {
      e.preventDefault();
      input.focus();
      input.select();
    }
    if (e.key === "Escape" && document.activeElement === input) {
      input.blur();
    }
  });
}

/* ── Dark mode ─────────────────────────────────────────────── */
function initTheme() {
  const stored = localStorage.getItem("theme");
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const theme = stored ?? (prefersDark ? "dark" : "light");
  document.documentElement.setAttribute("data-theme", theme);

  document.getElementById("themeToggle").addEventListener("click", () => {
    const next = isDark() ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("theme", next);
    // Re-render to swap icon bg colors
    render();
  });
}

/* ── Sidebar toggle ────────────────────────────────────────── */
function initSidebar() {
  const sidebar  = document.getElementById("sidebar");
  const main     = document.getElementById("main");
  const btn      = document.getElementById("sidebarToggle");
  const isMobile = () => window.innerWidth <= 900;

  // Create overlay for mobile
  const overlay = document.createElement("div");
  overlay.className = "sidebar-overlay";
  document.body.appendChild(overlay);

  btn.addEventListener("click", () => {
    if (isMobile()) {
      sidebar.classList.toggle("mobile-open");
      overlay.classList.toggle("active");
    } else {
      sidebar.classList.toggle("collapsed");
      main.classList.toggle("sidebar-collapsed");
    }
  });

  overlay.addEventListener("click", () => {
    sidebar.classList.remove("mobile-open");
    overlay.classList.remove("active");
  });
}

/* ── Open App ──────────────────────────────────────────────── */
function openApp(id) {
  const app = APPS.find(a => a.id === id);
  if (!app) return;
  if (app.url && app.url !== "#") {
    window.open(app.url, "_blank", "noopener,noreferrer");
  } else {
    // Demo feedback
    const card = document.querySelector(`.app-card[data-id="${id}"]`);
    if (!card) return;
    const btn = card.querySelector(".btn-open");
    const orig = btn.innerHTML;
    btn.textContent = "Opening…";
    btn.style.opacity = "0.7";
    setTimeout(() => {
      btn.innerHTML = orig;
      btn.style.opacity = "";
    }, 1200);
  }
}

/* ── Init ──────────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  initSidebar();
  initCategoryNav();
  initFilterTabs();
  initSearch();
  render();

  // Update "All Apps" count badge in sidebar
  document.getElementById("allCount").textContent = APPS.length;
});
