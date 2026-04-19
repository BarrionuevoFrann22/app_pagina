# config_manager.py
import json, os
from base64 import b64encode, b64decode

CONFIG_FILE = "config.json"

def _ofuscar(texto: str) -> str:
    return b64encode(texto.encode()).decode()

def _deofuscar(texto: str) -> str:
    try:
        return b64decode(texto.encode()).decode()
    except Exception:
        return texto

def _leer_version() -> str:
    try:
        with open("version.txt") as f:
            return f.read().strip()
    except FileNotFoundError:
        return "1.0.0"

def guardar_config(url_campus: str, usuario: str, password: str, groq_key: str = ""):
    data = {
        "url_campus": url_campus.rstrip("/"),
        "usuario":    usuario,
        "password":   _ofuscar(password),
        "groq_key":   _ofuscar(groq_key) if groq_key else "",
        "version":    _leer_version(),
    }
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

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
    """Devuelve la key del usuario si existe, sino cadena vacía (app.py usa la suya)."""
    c = cargar_config()
    return c.get("groq_key", "") if c else ""