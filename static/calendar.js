/* =====================================================
   calendar.js — Interactive calendar + agenda events
   Fase 5: rich tooltips on hover, color-coded day backgrounds
   ===================================================== */

(function () {
  const DAYS_ES = ["LUN", "MAR", "MIÉ", "JUE", "VIE", "SÁB", "DOM"];
  const MONTHS_ES = [
    "Enero","Febrero","Marzo","Abril","Mayo","Junio",
    "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre",
  ];

  const today  = new Date();
  let viewYear  = today.getFullYear();
  let viewMonth = today.getMonth();

  let eventsByDate = {};

  const TYPE_COLORS = {
    examen:  "#ef4444",
    tarea:   "#f97316",
    evento:  "#3b82f6",
  };

  const TYPE_LABELS = {
    examen:  "📝 Examen",
    tarea:   "📋 Tarea",
    evento:  "📅 Evento",
  };

  const TYPE_BG = {
    examen:  "#fef2f2",
    tarea:   "#fff7ed",
    evento:  "#eff6ff",
  };

  // ── Tooltip element (singleton) ─────────────────────
  let tooltip = null;
  function ensureTooltip() {
    if (tooltip) return tooltip;
    tooltip = document.createElement("div");
    tooltip.className = "cal-tooltip";
    tooltip.style.display = "none";
    document.body.appendChild(tooltip);
    return tooltip;
  }

  function showTooltip(el, events) {
    const tip = ensureTooltip();
    tip.innerHTML = events.map(ev => {
      const color = TYPE_COLORS[ev.type] || "#3b82f6";
      const bg    = TYPE_BG[ev.type] || "#f3f4f6";
      const label = TYPE_LABELS[ev.type] || "📅 Evento";
      return `
        <div class="cal-tip-item" style="border-left:3px solid ${color};background:${bg}">
          <div class="cal-tip-type" style="color:${color}">${label}</div>
          <div class="cal-tip-title">${escHtml(ev.title)}</div>
          ${ev.subject ? `<div class="cal-tip-subject">${escHtml(ev.subject)}</div>` : ""}
        </div>`;
    }).join("");

    tip.style.display = "block";

    // Position below the day cell
    const rect = el.getBoundingClientRect();
    const tipRect = tip.getBoundingClientRect();
    let left = rect.left + rect.width / 2 - tipRect.width / 2;
    let top  = rect.bottom + 6;

    // Keep within viewport
    if (left < 8) left = 8;
    if (left + tipRect.width > window.innerWidth - 8) left = window.innerWidth - tipRect.width - 8;
    if (top + tipRect.height > window.innerHeight - 8) {
      top = rect.top - tipRect.height - 6;
    }

    tip.style.left = left + "px";
    tip.style.top  = top + "px";
  }

  function hideTooltip() {
    if (tooltip) tooltip.style.display = "none";
  }

  // ── Load events from server ─────────────────────────
  async function loadEvents() {
    try {
      const res   = await fetch("/api/agenda");
      const items = await res.json();
      eventsByDate = {};
      items.forEach(ev => {
        if (!eventsByDate[ev.date]) eventsByDate[ev.date] = [];
        eventsByDate[ev.date].push(ev);
      });
      buildCalendar();
      renderUpcoming();
    } catch (e) {
      console.warn("No se pudieron cargar los eventos de agenda:", e);
      buildCalendar();
    }
  }

  window.calendarRefresh = loadEvents;

  // ── Build the calendar grid ─────────────────────────
  function buildCalendar() {
    const cal   = document.getElementById("calendar");
    const label = document.getElementById("calMonthLabel");
    if (!cal) return;

    label.textContent = `${MONTHS_ES[viewMonth]} ${viewYear}`;
    cal.innerHTML = "";

    const wdRow = document.createElement("div");
    wdRow.className = "cal-weekdays";
    DAYS_ES.forEach(d => {
      const cell = document.createElement("div");
      cell.className = "cal-weekday";
      cell.textContent = d;
      wdRow.appendChild(cell);
    });
    cal.appendChild(wdRow);

    const grid = document.createElement("div");
    grid.className = "cal-days";

    const firstDay    = new Date(viewYear, viewMonth, 1);
    const startOffset = (firstDay.getDay() + 6) % 7;
    const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
    const daysInPrev  = new Date(viewYear, viewMonth, 0).getDate();

    for (let i = startOffset - 1; i >= 0; i--) {
      grid.appendChild(mkDay(daysInPrev - i, true));
    }

    for (let d = 1; d <= daysInMonth; d++) {
      const isToday =
        d === today.getDate() &&
        viewMonth === today.getMonth() &&
        viewYear === today.getFullYear();

      const dateKey = `${viewYear}-${String(viewMonth + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      const events  = eventsByDate[dateKey] || [];

      grid.appendChild(mkDay(d, false, isToday, events, dateKey));
    }

    const total     = startOffset + daysInMonth;
    const remaining = total % 7 === 0 ? 0 : 7 - (total % 7);
    for (let d = 1; d <= remaining; d++) {
      grid.appendChild(mkDay(d, true));
    }

    cal.appendChild(grid);
  }

  function mkDay(num, otherMonth, isToday = false, events = [], dateKey = "") {
    const el = document.createElement("div");
    el.className = "cal-day";
    if (otherMonth) el.classList.add("cal-other-month");
    if (isToday)    el.classList.add("cal-today");
    if (events.length) el.classList.add("cal-has-events");

    // Color-coded background for days with events
    if (events.length && !isToday && !otherMonth) {
      const mainType = events[0].type;
      const color = TYPE_COLORS[mainType] || "#3b82f6";
      el.style.background = color + "18";
      el.style.fontWeight = "700";
      el.style.color = color;
    }

    el.textContent = num;

    if (events.length) {
      const dots = document.createElement("div");
      dots.className = "cal-event-dots";
      events.slice(0, 3).forEach(ev => {
        const dot = document.createElement("span");
        dot.className = "cal-event-dot";
        dot.style.background = TYPE_COLORS[ev.type] || "#3b82f6";
        dots.appendChild(dot);
      });
      el.appendChild(dots);

      // Rich tooltip on hover
      el.addEventListener("mouseenter", () => showTooltip(el, events));
      el.addEventListener("mouseleave", () => hideTooltip());
    }

    return el;
  }

  // ── Upcoming events list ─────────────────────────────
  function renderUpcoming() {
    const container = document.querySelector(".upcoming-panel");
    if (!container) return;

    const todayKey = today.toISOString().slice(0, 10);
    const upcoming = Object.entries(eventsByDate)
      .filter(([date]) => date >= todayKey)
      .sort(([a], [b]) => a.localeCompare(b))
      .flatMap(([date, evs]) => evs.map(ev => ({ ...ev, date })))
      .slice(0, 5);

    container.innerHTML = `<h4 class="upcoming-title">Próximos eventos</h4>`;

    if (!upcoming.length) {
      container.innerHTML += `<p class="upcoming-empty">Sin eventos próximos.</p>`;
      return;
    }

    const list = document.createElement("ul");
    list.style.cssText = "list-style:none;display:flex;flex-direction:column;gap:8px;padding:0";

    upcoming.forEach(ev => {
      const li   = document.createElement("li");
      li.style.cssText = "display:flex;align-items:flex-start;gap:10px;";

      const dt   = new Date(ev.date + "T12:00:00");
      const day  = dt.getDate();
      const mon  = MONTHS_ES[dt.getMonth()].slice(0, 3);
      const color = TYPE_COLORS[ev.type] || "#3b82f6";

      li.innerHTML = `
        <div style="
          flex-shrink:0;width:36px;text-align:center;
          background:${color}15;border-radius:6px;padding:4px 0;
          border-top:2px solid ${color}">
          <div style="font-size:.65rem;font-weight:700;color:${color};text-transform:uppercase">${mon}</div>
          <div style="font-size:.95rem;font-weight:700;color:#1a1a2e">${day}</div>
        </div>
        <div style="flex:1;min-width:0">
          <div style="font-size:.82rem;font-weight:600;color:#1a1a2e;line-height:1.3;word-break:break-word">
            ${escHtml(ev.title)}
          </div>
          ${ev.subject ? `<div style="font-size:.7rem;color:#9ca3af;margin-top:1px">${escHtml(ev.subject)}</div>` : ""}
        </div>
        <button onclick="deleteEvent('${ev.id}')"
          style="background:none;border:none;color:#d1d5db;cursor:pointer;font-size:.8rem;
                 flex-shrink:0;padding:2px;border-radius:4px;transition:color .13s"
          onmouseover="this.style.color='#ef4444'"
          onmouseout="this.style.color='#d1d5db'"
          title="Eliminar">✕</button>
      `;
      list.appendChild(li);
    });

    container.appendChild(list);
  }

  // ── Delete event ─────────────────────────────────────
  window.deleteEvent = async function (id) {
    try {
      await fetch(`/api/agenda/${id}`, { method: "DELETE" });
      loadEvents();
    } catch (e) {
      console.error("deleteEvent:", e);
    }
  };

  function escHtml(str) {
    return String(str || "")
      .replace(/&/g,"&amp;").replace(/</g,"&lt;")
      .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
  }

  // ── Nav arrows ───────────────────────────────────────
  function addNavArrows() {
    const header = document.querySelector(".agenda-header");
    if (!header) return;

    const nav  = document.createElement("div");
    nav.style.cssText = "display:flex;gap:6px;align-items:center;";

    const prev = mkArrow("‹");
    const next = mkArrow("›");

    prev.addEventListener("click", () => {
      viewMonth--;
      if (viewMonth < 0) { viewMonth = 11; viewYear--; }
      buildCalendar();
    });
    next.addEventListener("click", () => {
      viewMonth++;
      if (viewMonth > 11) { viewMonth = 0; viewYear++; }
      buildCalendar();
    });

    nav.appendChild(prev);
    nav.appendChild(next);
    header.appendChild(nav);
  }

  function mkArrow(ch) {
    const btn = document.createElement("button");
    btn.textContent = ch;
    btn.style.cssText = [
      "background:none;border:none;cursor:pointer;",
      "font-size:1.1rem;color:#6b7280;width:24px;height:24px;",
      "display:flex;align-items:center;justify-content:center;",
      "border-radius:4px;transition:background .13s;",
    ].join("");
    btn.addEventListener("mouseover", () => btn.style.background = "#f3f4f6");
    btn.addEventListener("mouseout",  () => btn.style.background = "none");
    return btn;
  }

  // ── Init ─────────────────────────────────────────────
  document.addEventListener("DOMContentLoaded", () => {
    addNavArrows();
    loadEvents();
  });
})();
