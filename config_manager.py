# config_manager.py
import json, os, sys
from base64 import b64encode, b64decode

def _get_base_dir() -> str:
    """Carpeta donde vive el .exe o el .py — nunca _MEIPASS."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(_get_base_dir(), "config.json")

def _ofuscar(texto: str) -> str:
    return b64encode(texto.encode()).decode()

def _deofuscar(texto: str) -> str:
    try:
        return b64decode(texto.encode()).decode()
    except Exception:
        return texto

def _leer_version() -> str:
    try:
        v = os.path.join(_get_base_dir(), "version.txt")
        with open(v) as f:
            return f.read().strip()
    except FileNotFoundError:
        return "1.0.0"

def guardar_config(url_campus: str, usuario: str, password: str, groq_key: str = ""):
    if not url_campus or not usuario or not password:
        raise ValueError("URL, usuario y contraseña son obligatorios.")

    data = {
        "url_campus": url_campus.strip().rstrip("/"),
        "usuario":    usuario.strip(),
        "password":   _ofuscar(password),
        "groq_key":   _ofuscar(groq_key.strip()) if groq_key and groq_key.strip() else "",
        "version":    _leer_version(),
    }
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except (IOError, OSError, PermissionError) as e:
        raise RuntimeError(f"No se pudo escribir config.json en {CONFIG_FILE}: {e}")

def cargar_config() -> dict | None:
    if not os.path.exists(CONFIG_FILE):
        return None
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["password"] = _deofuscar(data.get("password", ""))
        data["groq_key"] = _deofuscar(data.get("groq_key", ""))
        return data
    except (json.JSONDecodeError, IOError):
        return None

def config_completa() -> bool:
    c = cargar_config()
    return bool(c and c.get("url_campus") and c.get("usuario") and c.get("password"))

def get_groq_key() -> str:
    c = cargar_config()
    return c.get("groq_key", "") if c else ""