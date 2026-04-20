import os
import json
import uuid
import re
import sys
import webbrowser
import subprocess
import threading
from threading import Timer
from datetime import datetime

from dotenv import load_dotenv

# ─────────────────────────────────────────────────────────────────────
# PATH RESOLVER (compatible .exe de PyInstaller) — debe ir ANTES de load_dotenv
# ─────────────────────────────────────────────────────────────────────
def _app_base_dir() -> str:
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

_APP_DIR = _app_base_dir()

# Cargar .env desde la carpeta del .exe (no desde _MEIPASS)
load_dotenv(os.path.join(_APP_DIR, ".env"))

from flask import Flask, render_template, jsonify, send_from_directory, abort, request, redirect, url_for
from config_manager import cargar_config, guardar_config, config_completa
from updater import chequear_update_background, get_update_info

# ── PDF extraction
try:
    import pdfplumber
    PDF_LIB = "pdfplumber"
except ImportError:
    PDF_LIB = None

# ── Groq AI
GROQ_CANDIDATES = [
    "llama-3.1-8b-instant",
    "llama3-groq-8b-8192-tool-use-preview",
    "gemma2-9b-it",
]

AI_AVAILABLE  = False
AI_CLIENT     = None
AI_MODEL_NAME = ""

try:
    from groq import Groq
    _key = os.environ.get("GROQ_API_KEY", "").strip()

    # Fallback: leer key del config.json si no está en .env
    if not _key:
        try:
            _cfg_tmp = cargar_config()
            if _cfg_tmp and _cfg_tmp.get("groq_key"):
                _key = _cfg_tmp["groq_key"].strip()
                print("✅ Usando Groq key del config.json")
        except Exception:
            pass

    if not _key:
        print("⚠️  GROQ_API_KEY no encontrada — IA desactivada.")
    else:
        _client = Groq(api_key=_key)
        for _model in GROQ_CANDIDATES:
            try:
                _resp = _client.chat.completions.create(
                    model=_model,
                    messages=[{"role": "user", "content": "ok"}],
                    max_tokens=5,
                )
                AI_CLIENT     = _client
                AI_MODEL_NAME = _model
                AI_AVAILABLE  = True
                print(f"✅ Groq listo: {_model}")
                break
            except Exception as _e:
                print(f"   ↳ {_model}: {str(_e)[:80]}")
        if not AI_AVAILABLE:
            print("⚠️  Ningún modelo Groq respondió. Verificá tu GROQ_API_KEY.")
except ImportError:
    print("⚠️  groq no instalado.")
except Exception as e:
    print(f"⚠️  Error inicializando Groq: {e}")

# ── PyInstaller resource resolver (templates/static empaquetados en _MEIPASS)
def resolver_rutas(ruta_relativa):
    try:
        ruta_base = sys._MEIPASS
    except Exception:
        ruta_base = os.path.abspath(".")
    return os.path.join(ruta_base, ruta_relativa)

app = Flask(__name__,
            template_folder=resolver_rutas('templates'),
            static_folder=resolver_rutas('static'))

chequear_update_background()

# ── User Groq key override
from config_manager import get_groq_key as _get_user_groq_key
_user_key = _get_user_groq_key()
if _user_key and not AI_AVAILABLE:
    try:
        _client2 = Groq(api_key=_user_key)
        for _model in GROQ_CANDIDATES:
            try:
                _resp2 = _client2.chat.completions.create(
                    model=_model,
                    messages=[{"role": "user", "content": "ok"}],
                    max_tokens=5,
                )
                AI_CLIENT     = _client2
                AI_MODEL_NAME = _model
                AI_AVAILABLE  = True
                print(f"✅ Groq listo con key del usuario: {_model}")
                break
            except Exception:
                continue
    except Exception as e:
        print(f"⚠️  Key del usuario inválida: {e}")


# ── Helper para recargar Groq dinámicamente (tras onboarding sin reiniciar)
def _reinit_groq() -> tuple[bool, str]:
    global AI_CLIENT, AI_MODEL_NAME, AI_AVAILABLE
    try:
        from groq import Groq
    except ImportError:
        return False, "SDK 'groq' no instalado."

    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        cfg = cargar_config()
        if cfg and cfg.get("groq_key"):
            key = cfg["groq_key"].strip()
    if not key:
        AI_AVAILABLE = False
        return False, "GROQ_API_KEY vacía."

    try:
        client = Groq(api_key=key)
        for model in GROQ_CANDIDATES:
            try:
                client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": "ok"}],
                    max_tokens=5,
                )
                AI_CLIENT     = client
                AI_MODEL_NAME = model
                AI_AVAILABLE  = True
                return True, f"Groq activo: {model}"
            except Exception:
                continue
        AI_AVAILABLE = False
        return False, "Ningún modelo Groq respondió con esa key."
    except Exception as e:
        AI_AVAILABLE = False
        return False, f"Error inicializando Groq: {e}"


# ─────────────────────────────────────────────────────────────────────
# Paths de datos (persisten al lado del .exe, NO en _MEIPASS)
# ─────────────────────────────────────────────────────────────────────
BASE_DIR         = os.path.join(_APP_DIR, "Desarrollo")
ANNOTATIONS_FILE = os.path.join(_APP_DIR, "anotaciones.json")
AGENDA_FILE      = os.path.join(_APP_DIR, "agenda.json")
os.makedirs(BASE_DIR, exist_ok=True)

SUBJECT_COLORS = [
    "#f59e0b", "#3b82f6", "#10b981", "#f97316",
    "#8b5cf6", "#06b6d4", "#84cc16", "#ec4899",
    "#14b8a6", "#ef4444",
]

MONTH_MAP = {
    "enero":1,"febrero":2,"marzo":3,"abril":4,"mayo":5,"junio":6,
    "julio":7,"agosto":8,"septiembre":9,"octubre":10,"noviembre":11,"diciembre":12,
    "jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,
    "jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12,
}

# ─────────────────────────────────────────────────────────────────────
# HELPERS — data access
# ─────────────────────────────────────────────────────────────────────

def scan_subjects():
    subjects = []
    if not os.path.exists(BASE_DIR):
        os.makedirs(BASE_DIR)
        return subjects
    entries = sorted(
        [e for e in os.scandir(BASE_DIR) if e.is_dir()],
        key=lambda e: e.name.lower(),
    )
    for idx, entry in enumerate(entries):
        folder = entry.path
        files  = os.listdir(folder)
        pdfs   = [f for f in files if f.lower().endswith(".pdf")]
        htmls  = [f for f in files if f.lower().endswith((".html", ".htm"))]
        subjects.append({
            "name":      entry.name,
            "color":     SUBJECT_COLORS[idx % len(SUBJECT_COLORS)],
            "textos":    len(pdfs),
            "resumenes": len(htmls),
            "year":      "1er Año",
        })
    return subjects


def load_annotations():
    if not os.path.exists(ANNOTATIONS_FILE):
        return []
    try:
        with open(ANNOTATIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def save_annotations(data):
    with open(ANNOTATIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_agenda():
    if not os.path.exists(AGENDA_FILE):
        return []
    try:
        with open(AGENDA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def save_agenda(data):
    with open(AGENDA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────────────────────────────
# HELPERS — text extraction
# ─────────────────────────────────────────────────────────────────────

def extract_pdf_text(subject_name, filename=None, max_chars=12000):
    folder = os.path.join(BASE_DIR, subject_name)
    if not os.path.isdir(folder) or PDF_LIB is None:
        return ""
    pdfs = [filename] if filename and filename.lower().endswith(".pdf") \
           else sorted(f for f in os.listdir(folder) if f.lower().endswith(".pdf"))
    all_text = []
    for pdf_name in pdfs:
        path = os.path.join(folder, pdf_name)
        try:
            with pdfplumber.open(path) as pdf:
                text = "\n".join(p.extract_text() or "" for p in pdf.pages[:20])
                all_text.append(f"=== {pdf_name} ===\n{text}")
        except Exception as e:
            all_text.append(f"[Error leyendo {pdf_name}: {e}]")
    return "\n\n".join(all_text)[:max_chars]


def extract_html_text(subject_name, filename=None, max_chars=12000):
    folder = os.path.join(BASE_DIR, subject_name)
    if not os.path.isdir(folder):
        return ""
    htmls = [filename] if filename else \
            sorted(f for f in os.listdir(folder) if f.lower().endswith((".html", ".htm")))
    all_text = []
    for h in htmls:
        path = os.path.join(folder, h)
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                raw = f.read()
            text = re.sub(r"<[^>]+>", " ", raw)
            text = re.sub(r"\s+", " ", text).strip()
            all_text.append(f"=== {h} ===\n{text}")
        except Exception as e:
            all_text.append(f"[Error: {e}]")
    return "\n\n".join(all_text)[:max_chars]


# ─────────────────────────────────────────────────────────────────────
# HELPERS — AI
# ─────────────────────────────────────────────────────────────────────

def call_ai(prompt: str) -> str:
    if not AI_AVAILABLE or AI_CLIENT is None:
        return "IA no disponible. Verificá que GROQ_API_KEY esté en .env o en la configuración, y que 'groq' esté instalado."
    try:
        resp = AI_CLIENT.chat.completions.create(
            model=AI_MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4096,
            temperature=0.3,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        return f"Error con Groq ({AI_MODEL_NAME}): {e}"

call_gemini = call_ai  # backwards compatibility


def sanitize_json_response(raw: str):
    text = raw.strip()
    text = re.sub(r"```[a-zA-Z]*\n?", "", text)
    text = re.sub(r"```", "", text).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list) and parsed:
            return parsed
        if isinstance(parsed, dict):
            for key in ("questions", "data", "items", "results"):
                if key in parsed and isinstance(parsed[key], list):
                    return parsed[key]
    except json.JSONDecodeError:
        pass
    start = text.find("[")
    if start != -1:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "[": depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    candidate = text[start:i+1]
                    try:
                        parsed = json.loads(candidate)
                        if isinstance(parsed, list) and parsed:
                            return parsed
                    except json.JSONDecodeError:
                        break
    raise ValueError(f"No se pudo extraer JSON válido. Primeros 400 chars:\n{raw[:400]}")


# ─────────────────────────────────────────────────────────────────────
# HELPER — resumen HTML template
# ─────────────────────────────────────────────────────────────────────

RESUMEN_CSS = """
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:'DM Sans',sans-serif;background:#f1f3f6;padding:40px 16px 80px}
.resumen-container{max-width:820px;margin:0 auto;background:#fff;border-radius:12px;padding:40px 48px;box-shadow:0 4px 24px rgba(0,0,0,.08)}
.resumen-header{text-align:center;margin-bottom:32px}
.resumen-badge{display:inline-block;background:#ede9fe;color:#7c3aed;border:1.5px solid #c4b5fd;border-radius:20px;font-size:.72rem;font-weight:700;letter-spacing:.05em;padding:3px 14px;text-transform:uppercase;margin-bottom:12px}
.resumen-titulo{font-size:1.8rem;font-weight:700;margin-bottom:6px}
.resumen-meta{font-size:.82rem;color:#9ca3af}
.resumen-guia{border-left:4px solid #7c3aed;background:#faf5ff;padding:14px 18px;border-radius:0 8px 8px 0;margin-bottom:28px;font-size:.9rem;line-height:1.6}
.resumen-guia strong{color:#7c3aed;display:block;margin-bottom:6px}
.resumen-seccion{margin-bottom:28px}
.resumen-seccion h2{font-size:1.1rem;font-weight:700;border-left:3px solid #10b981;padding-left:12px;margin-bottom:12px}
.resumen-seccion p{line-height:1.7;color:#374151;margin-bottom:10px}
.resumen-seccion ul{padding-left:20px;line-height:1.7;color:#374151}
.resumen-seccion li{margin-bottom:6px}
@media(max-width:600px){.resumen-container{padding:24px 20px}.resumen-titulo{font-size:1.4rem}}
"""

def build_resumen_html(subject, title, date_str, page_label, intro_block, sections):
    html_body = f"""<div class="resumen-container">
  <div class="resumen-header">
    <span class="resumen-badge">{subject}</span>
    <h1 class="resumen-titulo">{title}</h1>
    <p class="resumen-meta">Resumen IA · {date_str} · {page_label}</p>
  </div>
{intro_block}
{"".join(sections)}
</div>"""
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Resumen — {title}</title>
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>{RESUMEN_CSS}</style>
</head>
<body>{html_body}</body>
</html>"""


def clean_ai_html(r: str) -> str:
    """Limpia markdown residual de respuestas de la IA."""
    r = re.sub(r"```[a-zA-Z]*\n?", "", r)
    r = re.sub(r"```", "", r).strip()
    r = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', r)
    r = re.sub(r'\*(.+?)\*',     r'<em>\1</em>',         r)
    r = re.sub(r'__(.+?)__',     r'<strong>\1</strong>',  r)
    return r


PROMPT_RESUMEN = """CRÍTICO: Respondé ÚNICAMENTE en HTML. PROHIBIDO usar markdown, asteriscos (**), guiones bajos (__) o backticks (`). Solo etiquetas HTML.

Sos un profesor universitario experto en síntesis académica para estudiantes de nivel superior.
Tu tarea es crear un resumen de estudio de ALTA CALIDAD sobre '{subject}'{note}.

REGLAS ESTRICTAS:
- Identificá y explicá los 3-5 conceptos clave más importantes
- Usá lenguaje claro pero académicamente preciso
- Incluí ejemplos concretos donde ayuden a entender
- Al final de esta sección agregá 2-3 preguntas de repaso
- Mínimo 600 palabras, máximo 900 palabras

FORMATO HTML OBLIGATORIO (sin DOCTYPE, sin <html>, sin <body>):
- Cada sección en <div class="resumen-seccion">
- Títulos en <h2>
- Conceptos importantes en <strong>
- Listas con <ul><li> o <ol><li>
- Preguntas de repaso en: <div class="resumen-seccion"><h2>🧠 Preguntas de Repaso</h2><ol><li>...</li></ol></div>

TEXTO A RESUMIR:
{text}"""


# ─────────────────────────────────────────────────────────────────────
# CALENDAR INTENT
# ─────────────────────────────────────────────────────────────────────

def parse_calendar_intent(text: str):
    text_lower = text.lower().strip()
    imperative_triggers = [
        "agrega", "añade", "agregá", "anotá", "poneme", "agendá",
        "guarda", "agregar", "agendar", "recordame", "recordá",
    ]
    declarative_triggers = [
        "tengo", "hay", "tenemos", "me toca", "vence", "vencimiento",
        "entrega", "debo entregar", "tengo que entregar",
    ]
    event_keywords = [
        "parcial", "final", "examen", "prueba", "test", "tarea",
        "tp", "trabajo práctico", "entrega", "presentación",
    ]
    is_imperative  = any(t in text_lower for t in imperative_triggers)
    is_declarative = (
        any(t in text_lower for t in declarative_triggers)
        and any(k in text_lower for k in event_keywords)
    )
    if not is_imperative and not is_declarative:
        return None

    date_found = None
    m = re.search(r"\b(\d{1,2})\s+de\s+([a-záéíóúü]+)(?:\s+de\s+(\d{4}))?", text_lower, re.IGNORECASE)
    if m:
        day   = int(m.group(1))
        month = MONTH_MAP.get(m.group(2).strip())
        year  = int(m.group(3)) if m.group(3) else datetime.now().year
        if month and 1 <= day <= 31:
            try:
                date_found = datetime(year, month, day).strftime("%Y-%m-%d")
            except ValueError:
                pass

    if not date_found:
        m2 = re.search(r"\b(\d{1,2})[/\-](\d{1,2})(?:[/\-](\d{2,4}))?\b", text_lower)
        if m2:
            day, month = int(m2.group(1)), int(m2.group(2))
            year_raw   = m2.group(3)
            year       = int(year_raw) if year_raw else datetime.now().year
            if year < 100:
                year += 2000
            if 1 <= month <= 12 and 1 <= day <= 31:
                try:
                    date_found = datetime(year, month, day).strftime("%Y-%m-%d")
                except ValueError:
                    pass

    if not date_found:
        today    = datetime.now()
        weekdays = {"lunes":0,"martes":1,"miércoles":2,"miercoles":2,"jueves":3,"viernes":4,"sábado":5,"sabado":5,"domingo":6}
        for name, wd in weekdays.items():
            if f"el {name}" in text_lower or f"este {name}" in text_lower:
                days_ahead = (wd - today.weekday()) % 7
                if days_ahead == 0:
                    days_ahead = 7
                target = today.replace(hour=0,minute=0,second=0,microsecond=0)
                from datetime import timedelta
                target += timedelta(days=days_ahead)
                date_found = target.strftime("%Y-%m-%d")
                break

    if not date_found:
        return None

    title_raw = re.sub(r'\b(agrega|agregá|anotá|poneme|agendá|guarda|agregar|agendar|recordame|recordá|el|la|un|una|para|del|de|tengo|hay)\b', '', text_lower)
    title_raw = re.sub(r'\b\d{1,2}[/\-]\d{1,2}(?:[/\-]\d{2,4})?\b', '', title_raw)
    title_raw = re.sub(r'\b\d{1,2}\s+de\s+\w+(?:\s+de\s+\d{4})?\b', '', title_raw)
    title_raw = re.sub(r'\b(lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\b', '', title_raw)
    title_raw = re.sub(r'\s+', ' ', title_raw).strip().strip('.,;:')
    title     = title_raw.capitalize() if title_raw else "Evento"
    return {"title": title, "date": date_found}


# ─────────────────────────────────────────────────────────────────────
# ROUTES — index
# ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    if not config_completa():
        return redirect(url_for("configurar"))
    update   = get_update_info()
    subjects = scan_subjects()
    return render_template("index.html", subjects=subjects, update=update)


# ─────────────────────────────────────────────────────────────────────
# ROUTES — files
# ─────────────────────────────────────────────────────────────────────

@app.route("/files/<path:filepath>")
def serve_file(filepath):
    full = os.path.join(BASE_DIR, filepath)
    if not os.path.isfile(full):
        abort(404)
    directory = os.path.dirname(full)
    filename  = os.path.basename(full)
    return send_from_directory(directory, filename)


@app.route("/static/descargas/<path:filepath>")
def serve_descarga(filepath):
    base = os.path.join(_APP_DIR, "static", "descargas")
    full = os.path.join(base, filepath)
    if not os.path.isfile(full):
        abort(404)
    return send_from_directory(os.path.dirname(full), os.path.basename(full))


# ─────────────────────────────────────────────────────────────────────
# ROUTES — pages
# ─────────────────────────────────────────────────────────────────────

@app.route("/bibliografia/<subject>")
def bibliografia(subject):
    folder = os.path.join(BASE_DIR, subject)
    if not os.path.isdir(folder):
        abort(404)
    files = sorted(f for f in os.listdir(folder) if f.lower().endswith(".pdf"))
    idx   = next((i for i, s in enumerate(scan_subjects()) if s["name"] == subject), 0)
    color = SUBJECT_COLORS[idx % len(SUBJECT_COLORS)]
    return render_template("bibliografia.html", subject=subject, files=files, color=color)


@app.route("/resumenes/<subject>")
def resumenes(subject):
    folder = os.path.join(BASE_DIR, subject)
    if not os.path.isdir(folder):
        abort(404)
    files = sorted(f for f in os.listdir(folder) if f.lower().endswith((".html", ".htm")))
    idx   = next((i for i, s in enumerate(scan_subjects()) if s["name"] == subject), 0)
    color = SUBJECT_COLORS[idx % len(SUBJECT_COLORS)]
    return render_template("resumenes.html", subject=subject, files=files, color=color)


@app.route("/lector/<subject>/<filename>")
def lector(subject, filename):
    folder = os.path.join(BASE_DIR, subject)
    if not os.path.isfile(os.path.join(folder, filename)):
        abort(404)
    idx   = next((i for i, s in enumerate(scan_subjects()) if s["name"] == subject), 0)
    color = SUBJECT_COLORS[idx % len(SUBJECT_COLORS)]
    return render_template("lector.html",
                           subject=subject,
                           filename=filename,
                           pdf_url=f"/files/{subject}/{filename}",
                           color=color)


@app.route("/visor-resumen/<subject>/<filename>")
def visor_resumen(subject, filename):
    folder = os.path.join(BASE_DIR, subject)
    if not os.path.isfile(os.path.join(folder, filename)):
        abort(404)
    idx   = next((i for i, s in enumerate(scan_subjects()) if s["name"] == subject), 0)
    color = SUBJECT_COLORS[idx % len(SUBJECT_COLORS)]
    return render_template("visor_resumen.html",
                           subject=subject,
                           filename=filename,
                           resumen_url=f"/files/{subject}/{filename}",
                           color=color)


# ─────────────────────────────────────────────────────────────────────
# ROUTES — annotations
# ─────────────────────────────────────────────────────────────────────

@app.route("/api/annotations", methods=["GET"])
def get_annotations():
    subject  = request.args.get("subject")
    filename = request.args.get("filename")
    data     = load_annotations()
    if subject:
        data = [a for a in data if a.get("subject") == subject]
    if filename:
        data = [a for a in data if a.get("filename") == filename]
    return jsonify(data)


@app.route("/api/annotations", methods=["POST"])
def add_annotation():
    body = request.get_json(force=True) or {}
    annotation = {
        "id":         str(uuid.uuid4()),
        "subject":    body.get("subject", ""),
        "filename":   body.get("filename", ""),
        "type":       body.get("type", "highlight"),
        "text":       body.get("text", ""),
        "comment":    body.get("comment", ""),
        "color":      body.get("color", "#fde68a"),
        "page":       body.get("page", None),
        "created_at": f"{datetime.now().day} de {datetime.now().strftime('%B')}",
    }
    data = load_annotations()
    data.append(annotation)
    save_annotations(data)
    return jsonify(annotation), 201


@app.route("/api/annotations/<ann_id>", methods=["DELETE"])
def delete_annotation(ann_id):
    data     = load_annotations()
    new_data = [a for a in data if a["id"] != ann_id]
    if len(new_data) == len(data):
        return jsonify({"error": "not found"}), 404
    save_annotations(new_data)
    return jsonify({"deleted": ann_id})


@app.route("/api/annotations/clear", methods=["DELETE"])
def clear_annotations():
    subject  = request.args.get("subject")
    filename = request.args.get("filename")
    data     = load_annotations()
    if subject and filename:
        data = [a for a in data if not (a.get("subject") == subject and a.get("filename") == filename)]
    elif subject:
        data = [a for a in data if a.get("subject") != subject]
    else:
        data = []
    save_annotations(data)
    return jsonify({"ok": True})


# ─────────────────────────────────────────────────────────────────────
# ROUTES — agenda
# ─────────────────────────────────────────────────────────────────────

@app.route("/api/agenda", methods=["GET"])
def get_agenda():
    return jsonify(load_agenda())


@app.route("/api/agenda", methods=["POST"])
def add_agenda_event():
    body = request.get_json(force=True) or {}
    if not body.get("title") or not body.get("date"):
        return jsonify({"error": "title and date required"}), 400
    event = {
        "id":      str(uuid.uuid4()),
        "title":   body["title"],
        "date":    body["date"],
        "subject": body.get("subject", ""),
        "type":    body.get("type", "evento"),
        "created": datetime.now().isoformat(),
    }
    data = load_agenda()
    data.append(event)
    save_agenda(data)
    return jsonify(event), 201


@app.route("/api/agenda/<event_id>", methods=["DELETE"])
def delete_agenda_event(event_id):
    data     = load_agenda()
    new_data = [e for e in data if e["id"] != event_id]
    if len(new_data) == len(data):
        return jsonify({"error": "not found"}), 404
    save_agenda(new_data)
    return jsonify({"deleted": event_id})


# ─────────────────────────────────────────────────────────────────────
# ROUTES — AI chat
# ─────────────────────────────────────────────────────────────────────

@app.route("/api/chat", methods=["POST"])
def ai_chat():
    body     = request.get_json(force=True) or {}
    question = body.get("question", "").strip()
    subject  = body.get("subject", "")
    filename = body.get("filename", "")

    if not question:
        return jsonify({"error": "question required"}), 400

    calendar_event = parse_calendar_intent(question)
    if calendar_event:
        if subject:
            calendar_event["subject"] = subject
        q_lower = question.lower()
        if any(w in q_lower for w in ["examen", "parcial", "final", "prueba", "test"]):
            calendar_event["type"] = "examen"
        elif any(w in q_lower for w in ["tarea", "trabajo", "entrega", "tp"]):
            calendar_event["type"] = "tarea"
        else:
            calendar_event["type"] = "evento"

        event_record = {
            "id":      str(uuid.uuid4()),
            "title":   calendar_event["title"],
            "date":    calendar_event["date"],
            "subject": calendar_event.get("subject", ""),
            "type":    calendar_event["type"],
            "created": datetime.now().isoformat(),
        }
        agenda = load_agenda()
        agenda.append(event_record)
        save_agenda(agenda)

        try:
            dt      = datetime.strptime(calendar_event["date"], "%Y-%m-%d")
            date_es = f"{dt.day} de {dt.strftime('%B')} de {dt.year}"
        except Exception:
            date_es = calendar_event["date"]

        icon   = {"examen": "📝", "tarea": "📋", "evento": "📅"}.get(calendar_event["type"], "📅")
        answer = (
            f"{icon} ¡Listo! Agregué **{calendar_event['title']}** al calendario "
            f"para el **{date_es}**."
            + (f" (Materia: {subject})" if subject else "")
        )
        return jsonify({"answer": answer, "calendar_event": event_record})

    context = extract_pdf_text(subject, filename or None, max_chars=8000) if subject else ""
    if context:
        prompt = (
            f"Eres un tutor académico útil y preciso. "
            f"El estudiante estudia la materia '{subject}'.\n\n"
            f"CONTEXTO:\n{context}\n\n"
            f"PREGUNTA: {question}\n\n"
            f"Respondé en español, de forma clara y concisa."
        )
    else:
        prompt = f"Eres un tutor académico. PREGUNTA: {question}\nRespondé en español."

    return jsonify({"answer": call_ai(prompt)})


# ─────────────────────────────────────────────────────────────────────
# ROUTES — quiz
# ─────────────────────────────────────────────────────────────────────

@app.route("/api/quiz", methods=["POST"])
def generate_quiz():
    body     = request.get_json(force=True) or {}
    subject  = body.get("subject", "")
    filename = body.get("filename", "")
    mode     = body.get("mode", "multiple_choice")
    n        = min(int(body.get("n", 5)), 8)

    context = ""
    if filename:
        if filename.lower().endswith((".html", ".htm")):
            context = extract_html_text(subject, filename, max_chars=4000)
        elif filename.lower().endswith(".pdf"):
            context = extract_pdf_text(subject, filename, max_chars=4000)

    if not context.strip():
        context = extract_html_text(subject, None, max_chars=4000)
    if not context.strip():
        context = extract_pdf_text(subject, None, max_chars=4000)
    if not context.strip():
        return jsonify({"error": "No se encontró contenido para generar el quiz."}), 400

    if mode == "multiple_choice":
        schema = (
            'Array de exactamente {n} objetos JSON:\n'
            '[{{"question":"string","options":["A) ...","B) ...","C) ...","D) ..."],'
            '"correct":0,"explanation":"string"}}]\n'
            '"correct" es el índice 0-3 de la opción correcta.'
        ).format(n=n)
    elif mode == "true_false":
        schema = (
            'Array de exactamente {n} objetos JSON:\n'
            '[{{"question":"string","options":["Verdadero","Falso"],'
            '"correct":0,"explanation":"string"}}]\n'
            '"correct": 0 si verdadero, 1 si falso.'
        ).format(n=n)
    else:
        schema = (
            'Array de exactamente {n} objetos JSON:\n'
            '[{{"question":"string","options":[],"correct":-1,"explanation":"string"}}]'
        ).format(n=n)

    prompt = (
        "Eres un profesor generando preguntas de examen.\n"
        "El texto base puede estar en inglés pero generá las preguntas EN ESPAÑOL.\n\n"
        f"TEXTO BASE:\n{context[:3500]}\n\n"
        f"FORMATO REQUERIDO — respondé ÚNICAMENTE con este JSON, sin texto antes ni después:\n"
        f"{schema}\n\n"
        "IMPORTANTE: Tu respuesta debe comenzar con [ y terminar con ]"
    )

    raw = call_ai(prompt)
    try:
        questions = sanitize_json_response(raw)
    except ValueError as e:
        return jsonify({"error": "La IA no devolvió un formato válido. Intentá de nuevo.", "debug": raw[:400]}), 500

    return jsonify({"questions": questions, "mode": mode, "subject": subject})


# ─────────────────────────────────────────────────────────────────────
# ROUTES — generar resumen (individual)
# ─────────────────────────────────────────────────────────────────────

@app.route("/api/generar-resumen", methods=["POST"])
def generar_resumen():
    body      = request.get_json(force=True) or {}
    subject   = body.get("subject", "")
    filename  = body.get("filename", "")
    page_from = int(body.get("page_from", 1)) - 1
    page_to   = body.get("page_to")
    if page_to is not None:
        page_to = int(page_to)

    if not subject:
        return jsonify({"error": "subject requerido"}), 400
    if not filename:
        return jsonify({"error": "filename requerido — elegí un PDF específico"}), 400

    pdf_path = os.path.join(BASE_DIR, subject, filename)
    if not os.path.isfile(pdf_path):
        return jsonify({"error": f"Archivo no encontrado: {filename}"}), 404

    try:
        import pdfplumber as _plumb
        with _plumb.open(pdf_path) as _pdf:
            total_pages = len(_pdf.pages)
    except Exception as e:
        return jsonify({"error": f"No se pudo leer el PDF: {e}"}), 500

    p_start    = max(0, page_from)
    p_end      = min(page_to, total_pages) if page_to else total_pages
    title      = filename.replace(".pdf", "").replace("_", " ").strip()
    CHUNK      = 40
    CMAX       = 4000
    _now       = datetime.now()
    date_str   = f"{_now.day} de {_now.strftime('%B')} de {_now.year}"
    page_label = f"Páginas {p_start+1}–{p_end}" if (p_start > 0 or page_to) else f"{total_pages} páginas"

    def _extract_chunk(ps, pe):
        try:
            import pdfplumber as _p
            with _p.open(pdf_path) as _pdf:
                txt = "\n\n".join(pg.extract_text() or "" for pg in _pdf.pages[ps:pe])
            return txt.strip()[:CMAX]
        except Exception:
            return ""

    def _call_chunk(chunk_num, total_chunks, ps, pe, text):
        note   = f" (Parte {chunk_num}/{total_chunks}, págs {ps+1}-{pe})" if total_chunks > 1 else ""
        prompt = PROMPT_RESUMEN.format(subject=subject, note=note, text=text)
        r      = call_ai(prompt)
        return clean_ai_html(r)

    chunks   = [(i, min(i + CHUNK, p_end)) for i in range(p_start, p_end, CHUNK)]
    sections = []
    for idx_c, (cs, ce) in enumerate(chunks, 1):
        chunk_text = _extract_chunk(cs, ce)
        if chunk_text:
            section = _call_chunk(idx_c, len(chunks), cs, ce, chunk_text)
            if section:
                sections.append(section)

    if not sections:
        return jsonify({"error": "No se pudo extraer texto del PDF."}), 400

    if len(chunks) > 1:
        first_text = _extract_chunk(p_start, min(p_start + CHUNK, p_end))
        intro_txt  = call_ai(
            f"Sos un profesor universitario. Escribí una introducción académica de 4-5 oraciones "
            f"que explique de qué trata este material de '{subject}', qué vas a aprender y por qué es importante. "
            f"Solo texto plano, sin HTML.\n\n{first_text[:3000]}"
        )
        intro_block = f'<div class="resumen-guia"><strong>📌 Mini Guía</strong><p>{intro_txt}</p></div>'
    else:
        intro_block = '<div class="resumen-guia"><strong>📌 Mini Guía</strong><p>Resumen generado automáticamente a partir del texto.</p></div>'

    html_body = build_resumen_html(subject, title, date_str, page_label, intro_block, sections)
    html_body = clean_ai_html(html_body)

    if len(html_body) < 100:
        return jsonify({"error": "La IA no generó contenido válido. Intentá de nuevo."}), 500

    safe_stem    = re.sub(r"[^\w\-]", "_", filename.replace(".pdf", "") if filename else subject)
    out_filename = f"{safe_stem}_resumen.html"
    out_path     = os.path.join(BASE_DIR, subject, out_filename)

    try:
        with open(out_path, "w", encoding="utf-8") as f_out:
            f_out.write(html_body)
    except Exception as e:
        return jsonify({"error": f"No se pudo guardar el archivo: {e}"}), 500

    return jsonify({
        "ok":       True,
        "filename": out_filename,
        "url":      f"/files/{subject}/{out_filename}",
        "message":  f"Resumen guardado: {out_filename}",
    })


# ─────────────────────────────────────────────────────────────────────
# ROUTES — generar resumenes bulk
# ─────────────────────────────────────────────────────────────────────

_bulk_estado = {"corriendo": False, "log": [], "total": 0, "actual": 0}
_bulk_lock   = threading.Lock()


@app.route("/api/generar-resumenes-bulk", methods=["POST"])
def generar_resumenes_bulk():
    with _bulk_lock:
        if _bulk_estado["corriendo"]:
            return jsonify({"ok": False, "msg": "Ya hay resúmenes generándose."}), 409
        _bulk_estado["corriendo"] = True
        _bulk_estado["log"]       = []
        _bulk_estado["actual"]    = 0

    body      = request.get_json(force=True) or {}
    subject   = body.get("subject", "").strip()
    filenames = body.get("filenames", [])

    if not subject or not filenames:
        _bulk_estado["corriendo"] = False
        return jsonify({"ok": False, "msg": "subject y filenames requeridos"}), 400

    _bulk_estado["total"] = len(filenames)

    unir = body.get("unir", False)

    def _procesar():
        import pdfplumber as _plumb
        CHUNK = 40
        CMAX  = 4000
        todas_las_secciones = []

        for i, filename in enumerate(filenames):
            _bulk_estado["actual"] = i + 1
            _bulk_estado["log"].append(f"[{i+1}/{len(filenames)}] Procesando: {filename}...")
            try:
                pdf_path = os.path.join(BASE_DIR, subject, filename)
                if not os.path.isfile(pdf_path):
                    _bulk_estado["log"].append(f"  [!] No encontrado: {filename}")
                    continue

                with _plumb.open(pdf_path) as _pdf:
                    total_pages = len(_pdf.pages)

                _now       = datetime.now()
                date_str   = f"{_now.day} de {_now.strftime('%B')} de {_now.year}"
                title      = filename.replace(".pdf", "").replace("_", " ").strip()

                def _extract(ps, pe, _path=pdf_path):
                    try:
                        with _plumb.open(_path) as _pdf:
                            return "\n\n".join(pg.extract_text() or "" for pg in _pdf.pages[ps:pe]).strip()[:CMAX]
                    except Exception:
                        return ""

                chunks   = [(j, min(j + CHUNK, total_pages)) for j in range(0, total_pages, CHUNK)]
                sections = []
                for idx_c, (cs, ce) in enumerate(chunks, 1):
                    txt = _extract(cs, ce)
                    if txt:
                        note   = f" (Parte {idx_c}/{len(chunks)}, págs {cs+1}-{ce})" if len(chunks) > 1 else ""
                        prompt = PROMPT_RESUMEN.format(subject=subject, note=note, text=txt)
                        r      = clean_ai_html(call_ai(prompt))
                        if r:
                            sections.append(r)

                if not sections:
                    _bulk_estado["log"].append(f"  [!] Sin texto extraíble: {filename}")
                    continue

                if unir:
                    todas_las_secciones.append(
                        f'<div class="resumen-seccion" style="border-top:2px solid #e5e7eb;padding-top:20px;margin-top:20px">'
                        f'<h2 style="color:#7c3aed">📄 {title}</h2></div>'
                    )
                    todas_las_secciones.extend(sections)
                else:
                    intro_block  = '<div class="resumen-guia"><strong>📌 Mini Guía</strong><p>Resumen generado automáticamente.</p></div>'
                    full_html    = build_resumen_html(subject, title, date_str, f"{total_pages} páginas", intro_block, sections)
                    safe_stem    = re.sub(r"[^\w\-]", "_", filename.replace(".pdf", ""))
                    out_filename = f"{safe_stem}_resumen.html"
                    out_path     = os.path.join(BASE_DIR, subject, out_filename)
                    with open(out_path, "w", encoding="utf-8") as f_out:
                        f_out.write(full_html)
                    _bulk_estado["log"].append(f"  [✓] Guardado: {out_filename}")

            except Exception as e:
                _bulk_estado["log"].append(f"  [ERROR] {filename}: {e}")

        if unir and todas_las_secciones:
            _now         = datetime.now()
            date_str     = f"{_now.day} de {_now.strftime('%B')} de {_now.year}"
            titulo_unido = f"Resumen consolidado — {subject}"
            intro_block  = (
                f'<div class="resumen-guia"><strong>📌 Resumen consolidado</strong>'
                f'<p>Este resumen reúne {len(filenames)} documentos de <strong>{subject}</strong>.</p></div>'
            )
            full_html    = build_resumen_html(subject, titulo_unido, date_str, f"{len(filenames)} documentos", intro_block, todas_las_secciones)
            out_filename = f"_consolidado_{re.sub(chr(32), '_', subject)}_resumen.html"
            out_path     = os.path.join(BASE_DIR, subject, out_filename)
            with open(out_path, "w", encoding="utf-8") as f_out:
                f_out.write(full_html)
            _bulk_estado["log"].append(f"\n[✓] Resumen consolidado guardado: {out_filename}")

        _bulk_estado["log"].append(f"\n[FIN] {len(filenames)} PDF(s) procesados.")
        _bulk_estado["corriendo"] = False

    threading.Thread(target=_procesar, daemon=True).start()
    return jsonify({"ok": True, "total": len(filenames)})


@app.route("/api/bulk-status")
def bulk_status():
    return jsonify({
        "corriendo": _bulk_estado["corriendo"],
        "actual":    _bulk_estado["actual"],
        "total":     _bulk_estado["total"],
        "log":       _bulk_estado["log"][-50:],
    })


# ─────────────────────────────────────────────────────────────────────
# ROUTES — pdf info
# ─────────────────────────────────────────────────────────────────────

@app.route("/api/pdf-info", methods=["GET"])
def pdf_info():
    subject  = request.args.get("subject", "")
    filename = request.args.get("filename", "")
    if not subject or not filename:
        return jsonify({"error": "subject and filename required"}), 400
    path = os.path.join(BASE_DIR, subject, filename)
    if not os.path.isfile(path):
        return jsonify({"error": "file not found"}), 404
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            pages = len(pdf.pages)
        return jsonify({"pages": pages, "filename": filename, "subject": subject})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────────────────────────────
# ROUTES — configuración y onboarding
# ─────────────────────────────────────────────────────────────────────

@app.route("/configurar", methods=["GET", "POST"])
def configurar():
    if request.method == "POST":
        body = request.get_json(force=True) or {}
        url  = body.get("url_campus", "").strip()
        user = body.get("usuario", "").strip()
        pw   = body.get("password", "").strip()
        if not url or not user or not pw:
            return jsonify({"ok": False, "msg": "Todos los campos son obligatorios"}), 400
        try:
            guardar_config(url, user, pw)
        except (ValueError, RuntimeError) as e:
            return jsonify({"ok": False, "msg": str(e)}), 500
        return jsonify({"ok": True})
    return render_template("onboarding.html", update=get_update_info())


@app.route("/api/config-status")
def config_status():
    return jsonify({"configurada": config_completa(), "update": get_update_info()})


@app.route("/api/guardar-config", methods=["POST"])
def guardar_config_api():
    body     = request.get_json(force=True) or {}
    url      = body.get("url_campus", "").strip()
    user     = body.get("usuario", "").strip()
    pw       = body.get("password", "").strip()
    groq_key = body.get("groq_key", "").strip()
    if not url or not user or not pw:
        return jsonify({"ok": False, "msg": "URL, usuario y contraseña son obligatorios"}), 400
    try:
        guardar_config(url, user, pw, groq_key)
    except (ValueError, RuntimeError) as e:
        return jsonify({"ok": False, "msg": str(e)}), 500

    ok_ia, msg_ia = _reinit_groq()
    return jsonify({"ok": True, "ia_activa": ok_ia, "ia_msg": msg_ia})


@app.route("/api/reload-ia", methods=["POST"])
def api_reload_ia():
    ok, msg = _reinit_groq()
    return jsonify({"ok": ok, "msg": msg, "modelo": AI_MODEL_NAME if ok else ""})


# ─────────────────────────────────────────────────────────────────────
# ROUTES — descargas y bot
# ─────────────────────────────────────────────────────────────────────

@app.route("/descargas")
def ver_descargas():
    ruta_json = os.path.join(_APP_DIR, "registro_descargas.json")
    try:
        with open(ruta_json, "r", encoding="utf-8") as f:
            archivos = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        archivos = []

    archivos.sort(key=lambda x: x.get("fecha_descarga", ""), reverse=True)
    agrupados = {}
    color_map = {}
    for a in archivos:
        materia = a.get("materia", "Sin materia")
        agrupados.setdefault(materia, []).append(a)
    for i, materia in enumerate(agrupados):
        color_map[materia] = SUBJECT_COLORS[i % len(SUBJECT_COLORS)]

    return render_template("descargas.html", agrupados=agrupados, color_map=color_map)


_bot_estado = {"corriendo": False, "log": []}
_bot_lock   = threading.Lock()


@app.route("/api/actualizar-material", methods=["POST"])
def actualizar_material():
    with _bot_lock:
        if _bot_estado["corriendo"]:
            return jsonify({"ok": False, "msg": "El bot ya está corriendo."}), 409
        if not config_completa():
            return jsonify({"ok": False, "msg": "No hay configuración. Andá a /configurar"}), 400
        _bot_estado["corriendo"] = True
        _bot_estado["log"]       = []

    def _correr_bot():
        import builtins
        _print_orig = builtins.print

        def _log_print(*args, **kwargs):
            msg = " ".join(str(a) for a in args)
            _bot_estado["log"].append(msg)
            _print_orig(msg)

        builtins.print = _log_print
        try:
            from bot_campus import login, obtener_materias, descargar_archivos
            from config_manager import cargar_config

            cfg = cargar_config()
            if not cfg:
                _bot_estado["log"].append("[ERROR] No hay configuración guardada.")
                return

            sess     = login(cfg["usuario"], cfg["password"])
            materias = obtener_materias(sess)
            if not materias:
                _bot_estado["log"].append("[!] Sin materias encontradas.")
            else:
                descargar_archivos(sess, materias)

        except Exception as e:
            _bot_estado["log"].append(f"[ERROR CRÍTICO] {e}")
        finally:
            builtins.print = _print_orig
            _bot_estado["corriendo"] = False

    threading.Thread(target=_correr_bot, daemon=True).start()
    return jsonify({"ok": True, "msg": "Bot iniciado."})


@app.route("/api/bot-status")
def bot_status():
    return jsonify({
        "corriendo": _bot_estado["corriendo"],
        "log":       _bot_estado["log"][-80:],
    })


# ─────────────────────────────────────────────────────────────────────
# SISTEMA DE APAGADO Y AUTO-INICIO
# ─────────────────────────────────────────────────────────────────────

@app.route('/apagar')
def apagar_servidor():
    print("Apagando servidor...")
    os._exit(0)
    return "Apagado"


def abrir_navegador():
    webbrowser.open_new("http://127.0.0.1:5000")


@app.route("/api/borrar-resumen", methods=["DELETE"])
def borrar_resumen():
    body     = request.get_json(force=True) or {}
    subject  = body.get("subject", "").strip()
    filename = body.get("filename", "").strip()
    todos    = body.get("todos", False)

    if not subject:
        return jsonify({"ok": False, "msg": "subject requerido"}), 400

    folder = os.path.join(BASE_DIR, subject)
    if not os.path.isdir(folder):
        return jsonify({"ok": False, "msg": "Materia no encontrada"}), 404

    borrados = 0
    try:
        if todos:
            archivos = [f for f in os.listdir(folder) if f.lower().endswith((".html", ".htm"))]
            for f in archivos:
                os.remove(os.path.join(folder, f))
                borrados += 1
        else:
            if not filename:
                return jsonify({"ok": False, "msg": "filename requerido"}), 400
            ruta = os.path.join(folder, filename)
            if not os.path.isfile(ruta):
                return jsonify({"ok": False, "msg": "Archivo no encontrado"}), 404
            os.remove(ruta)
            borrados = 1
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500

    return jsonify({"ok": True, "borrados": borrados})


@app.route("/api/borrar-descarga", methods=["DELETE"])
def borrar_descarga():
    body          = request.get_json(force=True) or {}
    ruta_relativa = body.get("ruta_relativa", "").strip()
    materia       = body.get("materia", "").strip()
    todos         = body.get("todos", False)

    ruta_json = os.path.join(_APP_DIR, "registro_descargas.json")

    def _cargar():
        try:
            with open(ruta_json, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _guardar(data):
        tmp = ruta_json + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, ruta_json)

    registro  = _cargar()
    borrados  = 0

    try:
        if todos:
            if not materia:
                return jsonify({"ok": False, "msg": "materia requerida para borrar todos"}), 400
            entradas = [e for e in registro if e.get("materia") == materia]
            for e in entradas:
                ruta_fisica = os.path.join(_APP_DIR, e["ruta_relativa"].replace("/", os.sep))
                if os.path.isfile(ruta_fisica):
                    os.remove(ruta_fisica)
                borrados += 1
            if entradas:
                carpeta = os.path.dirname(os.path.join(_APP_DIR, entradas[0]["ruta_relativa"].replace("/", os.sep)))
                if os.path.isdir(carpeta) and not os.listdir(carpeta):
                    os.rmdir(carpeta)
            registro = [e for e in registro if e.get("materia") != materia]
        else:
            if not ruta_relativa:
                return jsonify({"ok": False, "msg": "ruta_relativa requerida"}), 400
            ruta_fisica = os.path.join(_APP_DIR, ruta_relativa.replace("/", os.sep))
            if os.path.isfile(ruta_fisica):
                os.remove(ruta_fisica)
            registro = [e for e in registro if e.get("ruta_relativa") != ruta_relativa]
            borrados = 1

        _guardar(registro)
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500

    return jsonify({"ok": True, "borrados": borrados})


if __name__ == "__main__":
    Timer(1.5, abrir_navegador).start()
    app.run(debug=False, port=5000)