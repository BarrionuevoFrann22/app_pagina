"""
auto_procesar.py — Fase 4: Auto-Resumen en segundo plano
=========================================================
Corre independientemente de Flask.
Dos veces por semana escanea Desarrollo/ buscando PDFs sin resumen .html.
Si encuentra alguno, llama a Groq y guarda el resumen automáticamente.

Uso:
    python auto_procesar.py              # corre ahora y queda en loop
    python auto_procesar.py --once       # corre una vez y sale (para testear)

En background:
    nohup python auto_procesar.py &      # Mac/Linux
"""

import os, re, sys, time, logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────────────────
# PATH RESOLVER (compatible .exe de PyInstaller)
# ─────────────────────────────────────────────────────────────────────
def _base_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent

# ─────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────
BASE_DIR  = _base_dir() / "Desarrollo"
LOG_FILE  = _base_dir() / "auto_procesar.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# DEPENDENCIES CHECK
# ─────────────────────────────────────────────────────────────────────
try:
    import pdfplumber
except ImportError:
    log.error("Falta pdfplumber. Ejecutá: pip install pdfplumber")
    sys.exit(1)

try:
    import schedule
except ImportError:
    log.error("Falta schedule. Ejecutá: pip install schedule")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────
# GROQ SETUP — fast, free, no daily limits
# ─────────────────────────────────────────────────────────────────────
AI_CLIENT = None
AI_NAME   = ""

GROQ_CANDIDATES = [
    "llama3-8b-8192",
    "llama3-70b-8192",
    "mixtral-8x7b-32768",
    "gemma2-9b-it",
    "llama-3.1-8b-instant",
]

def init_ai():
    global AI_CLIENT, AI_NAME
    _key = os.environ.get("GROQ_API_KEY", "").strip()

    # Fallback: leer del config.json si no está en .env
    if not _key:
        try:
            sys.path.insert(0, str(_base_dir()))
            from config_manager import get_groq_key
            _key = get_groq_key().strip()
            if _key:
                log.info("✅ Usando GROQ_API_KEY desde config.json")
        except Exception as e:
            log.warning(f"  No se pudo leer config.json: {e}")

    if not _key:
        log.error("GROQ_API_KEY no encontrada (ni en .env ni en config.json)")
        log.error("  Obtené tu clave gratis en: https://console.groq.com/keys")
        return False

    try:
        from groq import Groq
    except ImportError:
        log.error("Falta el SDK de Groq. Ejecutá: pip install groq")
        return False

    client = Groq(api_key=_key)

    for model in GROQ_CANDIDATES:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "ok"}],
                max_tokens=5,
            )
            AI_CLIENT = client
            AI_NAME   = model
            log.info(f"✅ Groq listo: {model}")
            return True
        except Exception as e:
            log.warning(f"  ↳ {model}: {str(e)[:100]}")

    log.error("❌ Ningún modelo Groq respondió. Verificá tu GROQ_API_KEY.")
    return False

# ─────────────────────────────────────────────────────────────────────
# PDF HELPERS
# ─────────────────────────────────────────────────────────────────────

# PDFs with more than this many pages are skipped in auto mode
MAX_AUTO_PAGES = 100
# Pages per chunk for multi-chunk summarization
CHUNK_SIZE     = 20
# Max chars sent to AI per chunk
CHUNK_MAX_CHARS = 5000

def get_stem(filename: str) -> str:
    return Path(filename).stem.lower()

def pdf_has_summary(folder: Path, pdf_name: str) -> bool:
    stem = get_stem(pdf_name)
    for f in folder.iterdir():
        if f.suffix.lower() in (".html", ".htm") and get_stem(f.name) == stem:
            return True
        if f.suffix.lower() in (".html", ".htm") and get_stem(f.name) == stem + "_resumen":
            return True
    return False

def count_pdf_pages(pdf_path: Path) -> int:
    """Return number of pages in a PDF, or 0 on error."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            return len(pdf.pages)
    except Exception:
        return 0

def extract_chunk(pdf_path: Path, start: int, end: int) -> str:
    """Extract text from pages [start, end) (0-indexed). Returns up to CHUNK_MAX_CHARS."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            pages = pdf.pages[start:end]
            text  = "\n\n".join(p.extract_text() or "" for p in pages)
        return text.strip()[:CHUNK_MAX_CHARS]
    except Exception as e:
        log.error(f"  Error extrayendo chunk {start}-{end} de {pdf_path.name}: {e}")
        return ""

def extract_text(pdf_path: Path, page_from: int = 0, page_to: int = None) -> str:
    """Extract text from a range of pages (0-indexed, end exclusive)."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            total = len(pdf.pages)
            end   = min(page_to, total) if page_to else total
            pages = pdf.pages[page_from:end]
            text  = "\n\n".join(p.extract_text() or "" for p in pages)
        return text.strip()[:CHUNK_MAX_CHARS * 2]
    except Exception as e:
        log.error(f"  Error extrayendo texto de {pdf_path.name}: {e}")
        return ""

# ─────────────────────────────────────────────────────────────────────
# AI SUMMARY GENERATION
# ─────────────────────────────────────────────────────────────────────
def call_groq(prompt: str, max_tokens: int = 2048) -> str:
    """Call Groq. Returns text or empty string on failure."""
    if not AI_CLIENT:
        return ""
    try:
        resp = AI_CLIENT.chat.completions.create(
            model=AI_NAME,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.3,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        log.error(f"  Error llamando a Groq ({AI_NAME}): {e}")
        return ""


def summarize_chunk(subject: str, chunk_num: int, total_chunks: int,
                    page_from: int, page_to: int, text: str) -> str:
    """Ask Groq to summarize one chunk of pages. Returns plain text/HTML section."""
    if not text.strip():
        return ""
    multi_note = (f" (Parte {chunk_num} de {total_chunks}, páginas {page_from+1}-{page_to})"
                  if total_chunks > 1 else "")
    prompt = (
        f"Eres un profesor. Resumí el siguiente texto académico de la materia '{subject}'{multi_note}.\n"
        f"Identificá los conceptos clave y las ideas principales.\n"
        f"Respondé en HTML usando solo <div class=\"resumen-seccion\"> con <h2> y <p>/<ul>.\n"
        f"Máximo 400 palabras. Sin DOCTYPE ni <html>.\n\n"
        f"TEXTO:\n{text}"
    )
    raw = call_groq(prompt, max_tokens=1200)
    raw = re.sub(r"```[a-zA-Z]*\n?", "", raw)
    raw = re.sub(r"```", "", raw).strip()
    return raw


def generate_summary_html(subject: str, pdf_name: str, pdf_path: Path,
                          page_from: int = 0, page_to: int = None) -> str:
    """
    Generate a full HTML summary body.
    For PDFs > CHUNK_SIZE pages, processes in chunks and stitches results.
    page_from/page_to are 0-indexed; page_to=None means end of document.
    """
    if not AI_CLIENT:
        return ""

    _now     = datetime.now()
    date_str = f"{_now.day} de {_now.strftime('%B')} de {_now.year}"

    # Determine actual page range
    total_pages = count_pdf_pages(pdf_path)
    p_start = max(0, page_from)
    p_end   = min(page_to, total_pages) if page_to else total_pages
    n_pages = p_end - p_start

    log.info(f"    Páginas {p_start+1}-{p_end} de {total_pages} ({n_pages} pgs)")

    # Build chunks
    chunks = []
    for chunk_start in range(p_start, p_end, CHUNK_SIZE):
        chunk_end = min(chunk_start + CHUNK_SIZE, p_end)
        chunks.append((chunk_start, chunk_end))

    total_chunks = len(chunks)
    log.info(f"    {total_chunks} chunk(s) de hasta {CHUNK_SIZE} páginas cada uno")

    # Generate section HTML per chunk
    sections_html = []
    for i, (cs, ce) in enumerate(chunks, 1):
        log.info(f"    Chunk {i}/{total_chunks}: páginas {cs+1}-{ce}…")
        text = extract_chunk(pdf_path, cs, ce)
        if not text:
            log.warning(f"    Chunk {i}: sin texto extraíble")
            continue
        section = summarize_chunk(subject, i, total_chunks, cs, ce, text)
        if section:
            sections_html.append(section)
            time.sleep(2)   # rate-limit between chunk calls

    if not sections_html:
        return ""

    # For multi-chunk docs, generate a brief intro summary from the first chunk text
    intro_html = ""
    if total_chunks > 1:
        first_text = extract_chunk(pdf_path, p_start, min(p_start + CHUNK_SIZE, p_end))
        intro_prompt = (
            f"Basándote en este comienzo del texto de '{subject}', escribí 2-3 oraciones "
            f"describiendo de qué trata el documento en total. Solo el texto, sin HTML.\n\n{first_text[:2000]}"
        )
        intro_text = call_groq(intro_prompt, max_tokens=200)
        intro_html = f'''
  <div class="resumen-guia">
    <strong>📌 Mini Guía del Documento</strong>
    <p>{intro_text}</p>
  </div>'''
    else:
        intro_html = '''
  <div class="resumen-guia">
    <strong>📌 Mini Guía de la Unidad</strong>
    <p>Resumen generado automáticamente por IA.</p>
  </div>'''

    page_range_label = (f"Páginas {p_start+1}-{p_end}" if (p_start > 0 or page_to)
                        else f"{total_pages} páginas")

    body = f'''<div class="resumen-container">
  <div class="resumen-header">
    <span class="resumen-badge">{subject}</span>
    <h1 class="resumen-titulo">{pdf_name.replace(".pdf","").replace("_"," ")}</h1>
    <p class="resumen-meta">Resumen generado por IA el {date_str} · {page_range_label}</p>
  </div>
{intro_html}
{"".join(sections_html)}
</div>'''
    return body


def build_full_html(subject: str, title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Resumen — {title}</title>
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:'DM Sans',sans-serif;background:#f1f3f6;padding:40px 16px 80px}}
    .resumen-container{{max-width:820px;margin:0 auto;background:#fff;border-radius:12px;padding:40px 48px;box-shadow:0 4px 24px rgba(0,0,0,.08)}}
    .resumen-header{{text-align:center;margin-bottom:32px}}
    .resumen-badge{{display:inline-block;background:#ede9fe;color:#7c3aed;border:1.5px solid #c4b5fd;border-radius:20px;font-size:.72rem;font-weight:700;letter-spacing:.05em;padding:3px 14px;text-transform:uppercase;margin-bottom:12px}}
    .resumen-titulo{{font-size:1.8rem;font-weight:700;margin-bottom:6px}}
    .resumen-meta{{font-size:.82rem;color:#9ca3af}}
    .resumen-guia{{border-left:4px solid #7c3aed;background:#faf5ff;padding:14px 18px;border-radius:0 8px 8px 0;margin-bottom:28px;font-size:.9rem;line-height:1.6}}
    .resumen-guia strong{{color:#7c3aed;display:block;margin-bottom:6px}}
    .resumen-seccion{{margin-bottom:28px}}
    .resumen-seccion h2{{font-size:1.1rem;font-weight:700;border-left:3px solid #10b981;padding-left:12px;margin-bottom:12px}}
    .resumen-seccion p{{line-height:1.7;color:#374151;margin-bottom:10px}}
    .resumen-seccion ul{{padding-left:20px;line-height:1.7;color:#374151}}
    .resumen-seccion li{{margin-bottom:6px}}
    @media(max-width:600px){{.resumen-container{{padding:24px 20px}}.resumen-titulo{{font-size:1.4rem}}}}
  </style>
</head>
<body>{body}</body>
</html>"""

# ─────────────────────────────────────────────────────────────────────
# MAIN SCAN JOB
# ─────────────────────────────────────────────────────────────────────
def scan_and_summarize():
    if not AI_CLIENT:
        log.error("IA no inicializada — saltando escaneo.")
        return

    log.info("=" * 60)
    log.info(f"🔍 Iniciando escaneo con Groq ({AI_NAME})…")

    if not BASE_DIR.exists():
        log.warning(f"Carpeta no encontrada: {BASE_DIR}")
        return

    ok = errors = 0

    for subject_folder in sorted(BASE_DIR.iterdir()):
        if not subject_folder.is_dir():
            continue
        subject = subject_folder.name
        pdfs    = sorted(f for f in subject_folder.iterdir() if f.suffix.lower() == ".pdf")

        if not pdfs:
            continue

        log.info(f"📂 {subject} ({len(pdfs)} PDFs)")

        for pdf_path in pdfs:
            if pdf_has_summary(subject_folder, pdf_path.name):
                log.info(f"  ✅ Ya tiene resumen: {pdf_path.name}")
                continue

            log.info(f"  📄 Procesando: {pdf_path.name}")

            # Count pages first
            n_pages = count_pdf_pages(pdf_path)
            log.info(f"    Páginas totales: {n_pages}")

            if n_pages > MAX_AUTO_PAGES:
                log.warning(
                    f"  ⏭️  Saltando — {n_pages} páginas > límite auto ({MAX_AUTO_PAGES}). "
                    f"Usá el botón 'Resumir páginas X a Y' en el lector para hacerlo manualmente."
                )
                continue

            log.info(f"  🤖 Generando resumen con Groq/{AI_NAME}…")
            body = generate_summary_html(subject, pdf_path.name, pdf_path)

            if not body:
                log.warning(f"  ⚠️  Sin contenido generado para: {pdf_path.name}")
                errors += 1
                continue

            # Save next to PDF, same stem + _resumen
            stem     = re.sub(r"[^\w\-]", "_", Path(pdf_path.stem).name)
            out_name = f"{stem}_resumen.html"
            out_path = subject_folder / out_name

            try:
                title    = pdf_path.stem.replace("_", " ")
                full_html = build_full_html(subject, title, body)
                out_path.write_text(full_html, encoding="utf-8")
                log.info(f"  💾 Guardado: {out_name}")
                ok += 1
                time.sleep(4)  # rate-limit: be gentle with Groq
            except Exception as e:
                log.error(f"  ❌ Error guardando: {e}")
                errors += 1

    log.info(f"✅ Fin — {ok} generados, {errors} errores.")
    log.info("=" * 60)

# ─────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    run_once = "--once" in sys.argv

    log.info("🚀 Auto-procesador iniciado.")
    if not init_ai():
        log.error("No se pudo inicializar Groq. Verificá tu GROQ_API_KEY en .env o en config.json")
        log.error("Obtené tu clave gratis en: https://console.groq.com/keys")
        sys.exit(1)

    log.info("⚡ Escaneo inicial…")
    scan_and_summarize()

    if run_once:
        log.info("Modo --once: terminando.")
        sys.exit(0)

    # Schedule: lunes y jueves a las 08:00
    schedule.every().monday.at("08:00").do(scan_and_summarize)
    schedule.every().thursday.at("08:00").do(scan_and_summarize)
    log.info("⏰ Scheduler activo (lunes y jueves 08:00). Ctrl+C para detener.")

    try:
        while True:
            schedule.run_pending()
            time.sleep(60)
    except KeyboardInterrupt:
        log.info("🛑 Detenido manualmente.")