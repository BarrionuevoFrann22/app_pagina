# updater.py
import requests, threading
from config_manager import _leer_version

# Reemplazá con tu usuario y nombre de repo de GitHub
GITHUB_USER  = "BarrionuevoFrann22"
GITHUB_REPO  = "app_pagina"
RELEASES_URL = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/releases/latest"

_update_info = {"disponible": False, "version": "", "url_descarga": ""}

def chequear_update_background():
    """Corre en thread daemon — no bloquea el arranque de Flask."""
    threading.Thread(target=_chequear, daemon=True).start()

def _chequear():
    try:
        resp = requests.get(RELEASES_URL, timeout=8)
        if resp.status_code != 200:
            return
        data            = resp.json()
        version_remota  = data.get("tag_name", "").lstrip("v")
        version_local   = _leer_version()

        if _es_mayor(version_remota, version_local):
            # Buscar el .exe entre los assets
            assets    = data.get("assets", [])
            exe_asset = next((a for a in assets if a["name"].endswith(".exe")), None)
            _update_info["disponible"]   = True
            _update_info["version"]      = version_remota
            _update_info["url_descarga"] = exe_asset["browser_download_url"] if exe_asset else data.get("html_url", "")
    except Exception:
        pass   # sin internet o repo privado — silencioso

def _es_mayor(remota: str, local: str) -> bool:
    """Compara versiones semver simples: '1.2.0' > '1.1.0'"""
    try:
        r = tuple(int(x) for x in remota.split("."))
        l = tuple(int(x) for x in local.split("."))
        return r > l
    except ValueError:
        return False

def get_update_info() -> dict:
    return _update_info.copy()