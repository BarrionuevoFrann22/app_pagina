# bot_campus.py
import requests
from bs4 import BeautifulSoup
import os, re, sys, time, random, json
from datetime import datetime
from urllib.parse import urlparse

# ─── PATH RESOLVER (compatible .exe de PyInstaller) ────────────────────────────

def _base_dir() -> str:
    """Carpeta del .exe o del .py — nunca _MEIPASS."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR_APP = _base_dir()

# ─── PATHS ABSOLUTOS ───────────────────────────────────────────────────────────

CARPETA_STATIC = os.path.join(BASE_DIR_APP, "Desarrollo")
REGISTRO_JSON  = os.path.join(BASE_DIR_APP, "registro_descargas.json")

PATRONES_RECURSO = [
    "/mod/resource/view.php",
    "/mod/folder/view.php",
    "/mod/assign/view.php",
    "/pluginfile.php",
]

# ─── VARIABLES GLOBALES (se llenan con _init_campus) ───────────────────────────

_BASE_URL = LOGIN_URL = DASHBOARD_URL = ""
CAMPUS_USER = CAMPUS_PASS = DOMINIO_FACULTAD = ""
HEADERS_BASE: dict = {}

# ─── CONFIG GLOBAL ─────────────────────────────────────────────────────────────

def _cargar_config_campus() -> dict:
    """Lee config.json generado por el onboarding."""
    ruta = os.path.join(BASE_DIR_APP, "config.json")
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            data = json.load(f)
        from base64 import b64decode
        data["password"] = b64decode(data["password"].encode()).decode()
        return data
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        raise RuntimeError(
            f"config.json no encontrado o corrupto en: {ruta}. "
            f"Abrí la app y completá el onboarding primero. ({e})"
        )

def _derivar_urls(url_campus: str) -> tuple[str, str, str]:
    parsed    = urlparse(url_campus)
    base_path = re.sub(r'/login(/index\.php)?/?$', '', parsed.path).rstrip('/')
    base_url      = f"{parsed.scheme}://{parsed.netloc}{base_path}"
    login_url     = f"{base_url}/login/index.php"
    dashboard_url = f"{base_url}/my/"
    return base_url, login_url, dashboard_url

def _init_campus():
    """Carga config y arma URLs. Llamar antes de cualquier operación."""
    global _BASE_URL, LOGIN_URL, DASHBOARD_URL
    global CAMPUS_USER, CAMPUS_PASS, DOMINIO_FACULTAD, HEADERS_BASE

    cfg = _cargar_config_campus()
    _BASE_URL, LOGIN_URL, DASHBOARD_URL = _derivar_urls(cfg["url_campus"])
    CAMPUS_USER      = cfg["usuario"]
    CAMPUS_PASS      = cfg["password"]
    DOMINIO_FACULTAD = urlparse(_BASE_URL).netloc.replace(":", "_")
    HEADERS_BASE = {
        "Origin":     f"{urlparse(_BASE_URL).scheme}://{urlparse(_BASE_URL).netloc}",
        "Referer":    LOGIN_URL,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

# ─── HELPERS ───────────────────────────────────────────────────────────────────

def _sleep(min_s, max_s):
    t = random.uniform(min_s, max_s)
    print(f"  [SLEEP] {t:.1f}s...")
    time.sleep(t)

def _sanitizar(nombre: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", nombre).strip()

def _fix_encoding(nombre: str) -> str:
    try:
        return nombre.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return nombre

def _nombre_desde_respuesta(resp: requests.Response, url: str) -> str:
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r'filename\*?=["\']?(?:UTF-8\'\')?([^"\';\n]+)', cd, re.IGNORECASE)
    if m:
        nombre = m.group(1).strip().strip('"')
        return _fix_encoding(nombre)
    return url.split("/")[-1].split("?")[0] or "archivo_sin_nombre"

def _es_archivo(resp: requests.Response) -> bool:
    return "text/html" not in resp.headers.get("Content-Type", "")

def _headers_get(referer: str) -> dict:
    return {**HEADERS_BASE, "Referer": referer}

# ─── MANIFIESTO JSON ───────────────────────────────────────────────────────────

def _cargar_registro() -> list:
    if not os.path.exists(REGISTRO_JSON):
        return []
    try:
        with open(REGISTRO_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []

def _guardar_registro(registro: list):
    tmp = REGISTRO_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(registro, f, ensure_ascii=False, indent=2)
    os.replace(tmp, REGISTRO_JSON)

def _registrar_archivo(nombre: str, materia: str, ruta_relativa: str, url_original: str):
    registro  = _cargar_registro()
    ruta_url  = ruta_relativa.replace(os.sep, "/")
    existente = next((e for e in registro if e.get("ruta_relativa") == ruta_url), None)
    ahora     = datetime.now().isoformat(timespec="seconds")

    if existente:
        existente["fecha_descarga"] = ahora
    else:
        registro.append({
            "nombre_archivo": nombre,
            "materia":        materia,
            "facultad":       DOMINIO_FACULTAD,
            "ruta_relativa":  ruta_url,
            "fecha_descarga": ahora,
            "url_original":   url_original,
        })
    _guardar_registro(registro)

# ─── LOGIN ─────────────────────────────────────────────────────────────────────

def get_login_token(session: requests.Session) -> str:
    resp = session.get(LOGIN_URL, headers=HEADERS_BASE, timeout=15)
    resp.raise_for_status()
    soup  = BeautifulSoup(resp.text, "html.parser")
    token = soup.find("input", {"name": "logintoken"})
    if not token:
        raise ValueError("logintoken no encontrado")
    return token["value"]

def login(username: str, password: str) -> requests.Session:
    if not LOGIN_URL:
        _init_campus()
    session = requests.Session()
    token   = get_login_token(session)
    resp    = session.post(
        LOGIN_URL,
        data={"anchor": "", "username": username, "password": password, "logintoken": token},
        headers={**HEADERS_BASE, "Content-Type": "application/x-www-form-urlencoded"},
        allow_redirects=True, timeout=15,
    )
    resp.raise_for_status()
    if "/login/index.php" in resp.url:
        raise PermissionError("Login fallido. Verificá usuario y contraseña.")
    print(f"[OK] Login exitoso → {resp.url}\n")
    return session

# ─── AUTO-DESCUBRIMIENTO ───────────────────────────────────────────────────────

def obtener_materias(session: requests.Session) -> dict:
    print(f"[>>] Dashboard: {DASHBOARD_URL}")
    resp = session.get(DASHBOARD_URL, headers=_headers_get(LOGIN_URL), timeout=20)
    resp.raise_for_status()
    if "/login/index.php" in resp.url:
        raise PermissionError("Sesión expiró")

    soup    = BeautifulSoup(resp.text, "html.parser")
    materias, seen = {}, set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "course/view.php?id=" not in href or href in seen:
            continue
        nombre = _sanitizar(a.get_text(strip=True))
        if nombre:
            seen.add(href)
            materias[nombre] = href

    print(f"[OK] {len(materias)} materia(s):")
    for n, u in materias.items():
        print(f"     · {n} → {u}")
    print()
    return materias

# ─── DESCARGA ──────────────────────────────────────────────────────────────────

def _descargar_archivo(session, url, referer, carpeta_materia, nombre_materia, url_original):
    try:
        resp = session.get(url, headers=_headers_get(referer),
                           allow_redirects=True, timeout=30, stream=True)
        resp.raise_for_status()

        if not _es_archivo(resp):
            sub_soup  = BeautifulSoup(resp.text, "html.parser")
            sub_links = [
                a["href"] for a in sub_soup.find_all("a", href=True)
                if "/pluginfile.php" in a["href"] or "forcedownload=1" in a["href"]
            ]
            if not sub_links:
                print("  [!] Viewer sin descargable. Omitiendo.")
                return False
            resp = session.get(sub_links[0], headers=_headers_get(url),
                               allow_redirects=True, timeout=30, stream=True)
            resp.raise_for_status()

        nombre   = _nombre_desde_respuesta(resp, resp.url)
        ruta     = os.path.join(carpeta_materia, nombre)
        ruta_rel = os.path.join("Desarrollo", nombre_materia, nombre)

        if os.path.exists(ruta):
            print(f"  [=] Ya existe: {nombre}")
            _registrar_archivo(nombre, nombre_materia, ruta_rel, url_original)
            return False

        print(f"  [↓] Descargando: {nombre}")
        with open(ruta, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        _registrar_archivo(nombre, nombre_materia, ruta_rel, url_original)
        print(f"  [✓] Guardado: {ruta}")
        return True

    except requests.RequestException as e:
        print(f"  [ERROR] {e}")
        return False

def descargar_archivos(session: requests.Session, materias: dict):
    total_desc = total_omit = 0
    os.makedirs(CARPETA_STATIC, exist_ok=True)

    for nombre_materia, url_materia in materias.items():
        print(f"\n{'='*60}\n[MATERIA] {nombre_materia}\n{'='*60}")
        _sleep(1.2, 2.5)

        carpeta = os.path.join(CARPETA_STATIC, nombre_materia)
        os.makedirs(carpeta, exist_ok=True)

        try:
            resp = session.get(url_materia, headers=_headers_get(DASHBOARD_URL),
                               allow_redirects=True, timeout=20)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  [ERROR] {e}")
            continue

        soup    = BeautifulSoup(resp.text, "html.parser")
        enlaces = list(dict.fromkeys(
            a["href"] for a in soup.find_all("a", href=True)
            if any(p in a["href"] for p in PATRONES_RECURSO)
        ))

        if not enlaces:
            print("  [!] Sin recursos descargables.")
            continue

        print(f"  [OK] {len(enlaces)} recurso(s).")
        for i, enlace in enumerate(enlaces, 1):
            print(f"\n  [{i}/{len(enlaces)}] {enlace}")
            _sleep(1.5, 3.2)
            ok = _descargar_archivo(session, enlace, url_materia,
                                    carpeta, nombre_materia, enlace)
            total_desc += ok
            total_omit += not ok

    print(f"\n{'='*60}")
    print(f"[FIN] Descargados: {total_desc} | Omitidos: {total_omit}")
    print(f"[DIR] {os.path.abspath(CARPETA_STATIC)}")

# ─── ENTRY POINT ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        _init_campus()
        sess     = login(CAMPUS_USER, CAMPUS_PASS)
        materias = obtener_materias(sess)
        if not materias:
            print("[!] Sin materias. Verificá la URL del campus en la configuración.")
        else:
            descargar_archivos(sess, materias)
    except RuntimeError as e:
        print(f"[CONFIG ERROR] {e}")
    except (ValueError, PermissionError, requests.RequestException) as e:
        print(f"[ERROR CRÍTICO] {e}")