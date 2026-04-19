/* =====================================================
   lector.js — Fase 5b: Annotation system with color picker
   PDF rendering is handled by the native iframe.
   Since we can't inject into the browser's PDF renderer,
   we use colored annotations in the sidebar + color picker
   for manual input. If the PDF has an accessible text layer
   (some browsers expose it), we attempt to highlight there too.
   Quiz logic is in quiz.js
   ===================================================== */

// ── HIGHLIGHT COLORS ──────────────────────────────────
const HIGHLIGHT_COLORS = [
  { color: "#fde68a", name: "Amarillo" },
  { color: "#bbf7d0", name: "Verde" },
  { color: "#bae6fd", name: "Celeste" },
  { color: "#fbcfe8", name: "Rosa" },
  { color: "#fed7aa", name: "Naranja" },
  { color: "#ddd6fe", name: "Violeta" },
];

let annotations  = [];
let activeTab    = "all";
let selectedColor = "#fde68a";

// ── DOM REFS ──────────────────────────────────────────
const annPanel     = document.getElementById("annPanel");
const annList      = document.getElementById("annList");
const annCountEl   = document.getElementById("annCount");
const commentModal = document.getElementById("commentModal");
const commentInput = document.getElementById("commentInput");
const modalText    = document.getElementById("modalSelectedText");

// ── PANEL OPEN/CLOSE ──────────────────────────────────
document.getElementById("annClose").addEventListener("click", () => annPanel.classList.add("hidden"));
document.getElementById("fabAnn").addEventListener("click",   () => annPanel.classList.toggle("hidden"));

document.getElementById("fabStudy").addEventListener("click", () => {
  document.getElementById("repasoModal").style.display = "flex";
});

// ── TABS ──────────────────────────────────────────────
document.querySelectorAll(".ann-tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".ann-tab").forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    activeTab = tab.dataset.tab;
    rerenderList();
  });
});

// ── BUILD COLOR PICKER IN MANUAL AREA ─────────────────
(function buildColorPicker() {
  const manual = document.querySelector(".ann-manual");
  if (!manual) return;

  // Insert color row before the buttons
  const btnsRow = manual.querySelector(".ann-manual-btns");
  const colorRow = document.createElement("div");
  colorRow.className = "ann-color-row";
  colorRow.innerHTML = `<span class="ann-color-label">Color:</span>` +
    HIGHLIGHT_COLORS.map((c, i) =>
      `<button class="color-swatch${i === 0 ? ' selected' : ''}" data-color="${c.color}" style="background:${c.color}" title="${c.name}"></button>`
    ).join("");
  manual.insertBefore(colorRow, btnsRow);

  // Handle swatch clicks
  colorRow.querySelectorAll(".color-swatch").forEach(btn => {
    btn.addEventListener("click", () => {
      colorRow.querySelectorAll(".color-swatch").forEach(s => s.classList.remove("selected"));
      btn.classList.add("selected");
      selectedColor = btn.dataset.color;
    });
  });
})();

// ── MANUAL ANNOTATION BUTTONS ─────────────────────────
document.getElementById("annManualHL").addEventListener("click", () => {
  const text = document.getElementById("annManualText").value.trim();
  if (!text) return;
  saveAnnotation({ type: "highlight", text, comment: "", color: selectedColor });
  document.getElementById("annManualText").value = "";
});

document.getElementById("annManualCM").addEventListener("click", () => {
  const text = document.getElementById("annManualText").value.trim();
  if (!text) return;
  modalText.textContent = `"${text}"`;
  commentInput.value = "";
  commentModal.style.display = "flex";
  commentModal.dataset.pendingText = text;
  commentModal.dataset.pendingColor = selectedColor;
  setTimeout(() => commentInput.focus(), 80);
});

document.getElementById("modalCancel").addEventListener("click", () => {
  commentModal.style.display = "none";
});

document.getElementById("modalSave").addEventListener("click", async () => {
  const text    = commentModal.dataset.pendingText || "";
  const comment = commentInput.value.trim();
  const color   = commentModal.dataset.pendingColor || "#fbcfe8";
  if (text) {
    await saveAnnotation({ type: "comment", text, comment, color });
  }
  commentModal.style.display = "none";
});

commentModal.addEventListener("click", e => {
  if (e.target === commentModal) commentModal.style.display = "none";
});

// ── CLEAR ALL ─────────────────────────────────────────
document.getElementById("annClearAll").addEventListener("click", async () => {
  if (!annotations.length) return;
  if (!confirm("¿Borrar todas las anotaciones de este documento?")) return;
  try {
    await fetch(
      `/api/annotations/clear?subject=${encodeURIComponent(SUBJECT)}&filename=${encodeURIComponent(FILENAME)}`,
      { method: "DELETE" }
    );
    annotations = [];
    updateCount();
    rerenderList();
  } catch (e) { console.error(e); }
});

// ── API: SAVE ANNOTATION ──────────────────────────────
async function saveAnnotation(payload) {
  try {
    const res = await fetch("/api/annotations", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ subject: SUBJECT, filename: FILENAME, ...payload }),
    });
    if (!res.ok) throw new Error("server error");
    const ann = await res.json();
    annotations.push(ann);
    updateCount();
    prependCard(ann);
    return ann;
  } catch (e) {
    console.error("saveAnnotation:", e);
    return null;
  }
}

// ── API: DELETE ANNOTATION ────────────────────────────
async function deleteAnnotation(id) {
  try {
    await fetch(`/api/annotations/${id}`, { method: "DELETE" });
    annotations = annotations.filter(a => a.id !== id);
    updateCount();
    rerenderList();
  } catch (e) { console.error(e); }
}

// ── RENDER ────────────────────────────────────────────
function prependCard(ann) {
  if (activeTab !== "all" && ann.type !== activeTab) return;
  document.getElementById("annEmpty")?.remove();
  annList.prepend(buildCard(ann));
}

function rerenderList() {
  annList.innerHTML = "";
  const filtered = activeTab === "all"
    ? annotations
    : annotations.filter(a => a.type === activeTab);

  if (!filtered.length) {
    annList.innerHTML = `<p class="ann-empty" id="annEmpty">Sin anotaciones todavía.</p>`;
    return;
  }
  [...filtered].reverse().forEach(ann => annList.appendChild(buildCard(ann)));
}

function buildCard(ann) {
  const card = document.createElement("div");
  card.className = "ann-card";
  card.dataset.id = ann.id;
  const barColor = ann.color || (ann.type === "highlight" ? "#fbbf24" : "#ec4899");
  card.innerHTML = `
    <div class="ann-card-bar" style="background:${barColor}"></div>
    <button class="ann-delete-btn">✕</button>
    <p class="ann-card-text" style="border-left:3px solid ${barColor};padding-left:8px;">"${esc(ann.text)}"</p>
    ${ann.comment ? `<div class="ann-card-comment"><strong>Comentario:</strong> ${esc(ann.comment)}</div>` : ""}
    <p class="ann-card-meta">${ann.created_at}</p>
  `;
  card.querySelector(".ann-delete-btn").addEventListener("click", () => {
    deleteAnnotation(ann.id);
    card.remove();
  });
  return card;
}

function updateCount() {
  const n = annotations.length;
  annCountEl.textContent = `${n} guardada${n !== 1 ? "s" : ""}`;
}

function esc(s) {
  return String(s || "")
    .replace(/&/g,"&amp;").replace(/</g,"&lt;")
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

// ── GENERAR RESUMEN IA ────────────────────────────────
const btnGen    = document.getElementById("btnGenerarResumen");
const genStatus = document.getElementById("genStatus");
const picker    = document.getElementById("pageRangePicker");
const pageTotal = document.getElementById("pageTotal");
const inpFrom   = document.getElementById("pageFrom");
const inpTo     = document.getElementById("pageTo");

async function initPagePicker() {
  if (!FILENAME.toLowerCase().endsWith(".pdf")) return;
  try {
    const res  = await fetch(`/api/pdf-info?subject=${encodeURIComponent(SUBJECT)}&filename=${encodeURIComponent(FILENAME)}`);
    const data = await res.json();
    if (data.pages) {
      inpTo.value       = data.pages;
      inpTo.max         = data.pages;
      inpFrom.max       = data.pages;
      pageTotal.textContent = `/ ${data.pages}`;
      picker.style.display = "flex";
    }
  } catch (e) { /* silent */ }
}
initPagePicker();

btnGen.addEventListener("click", async () => {
  btnGen.disabled = true;
  btnGen.textContent = "⏳ Generando…";
  genStatus.style.display = "block";
  genStatus.className = "pdf-gen-status";

  const pageFrom = parseInt(inpFrom.value) || 1;
  const pageTo   = parseInt(inpTo.value)   || null;
  const nPages   = pageTo ? pageTo - pageFrom + 1 : "?";
  genStatus.textContent = `Generando resumen de ${nPages} páginas… esto puede tardar hasta 1 minuto.`;

  try {
    const res = await fetch("/api/generar-resumen", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ subject: SUBJECT, filename: FILENAME, page_from: pageFrom, page_to: pageTo }),
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      genStatus.className = "pdf-gen-status ok";
      genStatus.innerHTML = `✅ ${data.message} — <a href="${data.url}" target="_blank">Ver resumen →</a>`;
      btnGen.textContent  = "✅ Resumen listo";
    } else {
      genStatus.className = "pdf-gen-status error";
      genStatus.textContent = `❌ ${data.error || "Error desconocido"}`;
      btnGen.disabled   = false;
      btnGen.textContent = "✨ Generar Resumen IA";
    }
  } catch (e) {
    genStatus.className = "pdf-gen-status error";
    genStatus.textContent = `❌ Error de red: ${e.message}`;
    btnGen.disabled   = false;
    btnGen.textContent = "✨ Generar Resumen IA";
  }
});

// ── LOAD ANNOTATIONS ON INIT ──────────────────────────
(async () => {
  try {
    const res = await fetch(
      `/api/annotations?subject=${encodeURIComponent(SUBJECT)}&filename=${encodeURIComponent(FILENAME)}`
    );
    annotations = await res.json();
    updateCount();
    rerenderList();
  } catch (e) { console.error("loadAnnotations:", e); }
})();
