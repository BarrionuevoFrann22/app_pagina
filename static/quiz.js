/* =====================================================
   quiz.js — Repaso/Quiz shared logic
   Works in both lector.html and resumenes.html
   ===================================================== */
(function () {
  const repasoModal = document.getElementById("repasoModal");
  const quizModal   = document.getElementById("quizModal");
  const quizBody    = document.getElementById("quizBody");
  const fabStudy    = document.getElementById("fabStudy");
  const btnRepaso   = document.getElementById("btnRepaso");

  if (!repasoModal || !quizModal) return; // page doesn't have quiz modals

  let selectedMode = "multiple_choice";
  let questions    = [];
  let currentQ     = 0;
  let score        = 0;

  // Open repaso from FAB (lector page)
  fabStudy?.addEventListener("click", () => {
    repasoModal.style.display = "flex";
  });

  // Open repaso from button (resumenes page)
  btnRepaso?.addEventListener("click", () => {
    repasoModal.style.display = "flex";
  });

  document.getElementById("repasoClose")?.addEventListener("click", () => {
    repasoModal.style.display = "none";
  });

  repasoModal.addEventListener("click", (e) => {
    if (e.target === repasoModal) repasoModal.style.display = "none";
  });

  quizModal.addEventListener("click", (e) => {
    if (e.target === quizModal) quizModal.style.display = "none";
  });

  // Option selection
  document.querySelectorAll(".repaso-option").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".repaso-option").forEach(b => b.classList.remove("selected"));
      btn.classList.add("selected");
      selectedMode = btn.dataset.mode;
    });
  });

  // Start quiz
  document.getElementById("repasoStart")?.addEventListener("click", async () => {
    repasoModal.style.display = "none";
    quizModal.style.display   = "flex";
    quizBody.innerHTML = `<div class="quiz-loading"><div class="spinner"></div><p>Generando preguntas con IA…</p></div>`;

    const n = selectedMode === "open" ? 4 : 5;
    const subject  = typeof SUBJECT  !== "undefined" ? SUBJECT  : "";
    const filename = typeof FILENAME !== "undefined" ? FILENAME : "";

    try {
      const res = await fetch("/api/quiz", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ subject, filename, mode: selectedMode, n }),
      });
      const data = await res.json();
      if (data.error) { showQuizError(data.error); return; }
      questions = data.questions;
      currentQ  = 0;
      score     = 0;
      showQuestion();
    } catch (err) {
      showQuizError("Error de red: " + err.message);
    }
  });

  function showQuestion() {
    const q   = questions[currentQ];
    const pct = Math.round((currentQ / questions.length) * 100);
    document.getElementById("quizProgressBar").style.width = pct + "%";
    document.getElementById("quizCounter").textContent = `${currentQ + 1} / ${questions.length}`;

    const modeLabel = {
      multiple_choice: "Multiple Choice",
      true_false:      "Verdadero / Falso",
      open:            "Preguntas abiertas",
    }[selectedMode] || "Quiz";
    document.getElementById("quizTitle").textContent = modeLabel;

    if (selectedMode === "open") {
      quizBody.innerHTML = `
        <p class="quiz-question">${esc(q.question)}</p>
        <div class="quiz-explanation">${esc(q.explanation)}</div>
        <div style="text-align:right;margin-top:12px">
          <button class="quiz-next-btn" id="quizNext">
            ${currentQ < questions.length - 1 ? "Siguiente →" : "Ver resultado"}
          </button>
        </div>
      `;
    } else {
      const optsHtml = q.options.map((opt, i) =>
        `<button class="quiz-opt-btn" data-idx="${i}">${esc(opt)}</button>`
      ).join("");

      quizBody.innerHTML = `
        <p class="quiz-question">${esc(q.question)}</p>
        <div class="quiz-options">${optsHtml}</div>
        <div id="quizFeedback"></div>
      `;

      quizBody.querySelectorAll(".quiz-opt-btn").forEach(btn => {
        btn.addEventListener("click", () => handleAnswer(btn, q));
      });
    }

    document.getElementById("quizNext")?.addEventListener("click", nextQuestion);
  }

  function handleAnswer(btn, q) {
    quizBody.querySelectorAll(".quiz-opt-btn").forEach(b => b.disabled = true);

    const chosen  = parseInt(btn.dataset.idx);
    const correct = q.correct;

    quizBody.querySelectorAll(".quiz-opt-btn").forEach((b, i) => {
      if (i === correct) b.classList.add("correct");
      else if (i === chosen && chosen !== correct) b.classList.add("wrong");
    });

    if (chosen === correct) score++;

    const feedback = document.getElementById("quizFeedback");
    feedback.innerHTML = `
      <div class="quiz-explanation">${esc(q.explanation)}</div>
      <div style="text-align:right;margin-top:10px">
        <button class="quiz-next-btn" id="quizNext">
          ${currentQ < questions.length - 1 ? "Siguiente →" : "Ver resultado"}
        </button>
      </div>
    `;
    document.getElementById("quizNext").addEventListener("click", nextQuestion);
  }

  function nextQuestion() {
    currentQ++;
    if (currentQ >= questions.length) showScore();
    else showQuestion();
  }

  function showScore() {
    document.getElementById("quizProgressBar").style.width = "100%";
    const pct   = Math.round((score / questions.length) * 100);
    const emoji = pct >= 80 ? "🏆" : pct >= 60 ? "👍" : "📚";
    const msg   = pct >= 80
      ? "¡Excelente dominio del tema!"
      : pct >= 60
        ? "Buen trabajo, seguí practicando."
        : "Recomendamos repasar el material.";

    quizBody.innerHTML = `
      <div class="quiz-score">
        <div class="quiz-score-emoji">${emoji}</div>
        <h3>Quiz completado</h3>
        <p>${msg}</p>
        <div class="quiz-score-pill">${score} / ${questions.length} correctas (${pct}%)</div><br>
        <button class="quiz-restart-btn" id="quizRestart">🔄 Volver a intentar</button>
      </div>
    `;
    document.getElementById("quizRestart").addEventListener("click", () => {
      quizModal.style.display   = "none";
      repasoModal.style.display = "flex";
    });
  }

  function showQuizError(msg) {
    quizBody.innerHTML = `<div class="quiz-score"><p style="color:#ef4444;font-size:.9rem">❌ ${esc(msg)}</p><br><button class="quiz-restart-btn" onclick="document.getElementById('quizModal').style.display='none'">Cerrar</button></div>`;
  }

  function esc(str) {
    return String(str || "")
      .replace(/&/g,"&amp;").replace(/</g,"&lt;")
      .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
  }
})();
