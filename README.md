# 📚 Mi Plataforma IES — Fase 1

Plataforma de estudio personal local construida con Flask.

## Estructura del Proyecto

```
plataforma_estudio/
├── app.py                  # Backend Flask
├── requirements.txt
├── README.md
├── Desarrollo/             # ← TUS MATERIAS VAN AQUÍ
│   ├── Matematica/
│   │   ├── apunte1.pdf
│   │   └── resumen1.html
│   ├── Fisica/
│   └── ...
├── templates/
│   ├── index.html          # Dashboard principal
│   ├── bibliografia.html   # Vista de PDFs por materia
│   └── resumenes.html      # Vista de resúmenes HTML
└── static/
    ├── styles.css
    └── calendar.js
```

## Instalación y Uso

### 1. Crear entorno virtual (recomendado)
```bash
python -m venv venv
source venv/bin/activate        # Linux/Mac
venv\Scripts\activate           # Windows
```

### 2. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 3. Crear carpeta de materias
```bash
mkdir -p Desarrollo/Matematica Desarrollo/Fisica Desarrollo/Historia
# Copia tus PDFs y HTMLs dentro de cada subcarpeta
```

### 4. Ejecutar
```bash
python app.py
```

Abrir en el navegador: **http://localhost:5000**

---

## Cómo funciona

- Flask escanea automáticamente `Desarrollo/` al cargar la página.
- Cada subcarpeta = una materia con su propia tarjeta.
- Cuenta `.pdf` → Textos | `.html` / `.htm` → Resúmenes.
- Los colores de las tarjetas se asignan automáticamente en ciclo.

## API

| Endpoint | Descripción |
|---|---|
| `GET /` | Dashboard principal |
| `GET /api/subjects` | JSON con todas las materias y conteos |
| `GET /bibliografia/<materia>` | Lista los PDFs de esa materia |
| `GET /resumenes/<materia>` | Lista los HTMLs de esa materia |
| `GET /files/<materia>/<archivo>` | Sirve el archivo directamente |

---
*Fase 2: Lector de PDF embebido + editor de resúmenes*
*Fase 3: Sistema de notas y tareas*  
*Fase 4: Chat con IA integrado*
