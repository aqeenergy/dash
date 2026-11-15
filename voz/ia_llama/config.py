"""Configuración central. Todo se puede cambiar con variables de entorno o en el archivo .env."""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent  # carpeta voz/
REPO = RAIZ.parent  # raíz del repositorio

try:  # python-dotenv es opcional
    from dotenv import load_dotenv

    load_dotenv(RAIZ / ".env")
    load_dotenv(REPO / ".env")
except ImportError:
    pass

# --- Clave de API (Google AI Studio). El SDK también lee GOOGLE_API_KEY. ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

# --- Modelos ---
# Lista separada por comas: el primero es el principal y los demás, reservas. Si uno no existe
# (404, Google cambia los nombres a menudo), está saturado o agota su cuota, se pasa al siguiente.
MODELOS_LIVE = [m.strip() for m in os.getenv(
    "MODELO_LIVE", "gemini-3.1-flash-live-preview,gemini-2.5-flash-native-audio-preview-12-2025"
).split(",") if m.strip()]
MODELO_LIVE = MODELOS_LIVE[0]
VERSION_API_LIVE = os.getenv("VERSION_API_LIVE", "v1beta")  # la API Live no existe en v1
MINUTOS_VOLVER_AL_PRINCIPAL = int(os.getenv("MINUTOS_VOLVER_AL_PRINCIPAL", "10"))
MODELO_EMBEDDINGS = os.getenv("MODELO_EMBEDDINGS", "gemini-embedding-001")
DIMENSION_EMBEDDINGS = int(os.getenv("DIMENSION_EMBEDDINGS", "768"))

# --- Voz ---
VOZ = os.getenv("VOZ", "Kore")  # otras: Puck, Charon, Fenrir, Aoede...
NOMBRE_ASISTENTE = os.getenv("NOMBRE_ASISTENTE", "Llama")

# --- Rutas de datos ---
# Por defecto se usan los datos del NASA PSI que ya están en el repositorio (datos_psi/).
_PSI = REPO / "datos_psi" / "datos" / "psi_datos"
DIR_DOCUMENTOS = Path(os.getenv("DIR_DOCUMENTOS", RAIZ / "documentos"))  # PDF/MD/TXT + fichas PSI
DIR_TABLAS = Path(os.getenv("DIR_TABLAS", _PSI / "tablas"))
DIR_METADATOS = Path(os.getenv("DIR_METADATOS", _PSI / "metadatos"))
DIR_INDICE = Path(os.getenv("DIR_INDICE", RAIZ / "indice"))

# --- Troceado de documentos para el RAG ---
TAM_FRAGMENTO = int(os.getenv("TAM_FRAGMENTO", "1200"))  # caracteres
SOLAPE_FRAGMENTO = int(os.getenv("SOLAPE_FRAGMENTO", "200"))

# --- Límites de las respuestas de las herramientas (para no saturar la voz) ---
MAX_FILAS = int(os.getenv("MAX_FILAS", "20"))
MAX_FRAGMENTOS = int(os.getenv("MAX_FRAGMENTOS", "5"))

# --- Catálogo de tablas dentro de las instrucciones (ahorra 1-2 consultas por pregunta) ---
CATALOGO_EN_PROMPT = os.getenv("CATALOGO_EN_PROMPT", "si").lower() in ("si", "sí", "1", "true", "yes")

# --- Respuestas atascadas: si Gemini deja de enviar a mitad de respuesta, se le da un toque ---
SEGUNDOS_ATASCO = float(os.getenv("SEGUNDOS_ATASCO", "10"))
TEXTO_TOQUE = os.getenv("TEXTO_TOQUE", "(Sigue, por favor: termina la respuesta que estabas dando.)")

# --- Protección de la cuota (que nadie agote el límite de todos) ---
MAX_SESIONES_SIMULTANEAS = int(os.getenv("MAX_SESIONES_SIMULTANEAS", "3"))
MAX_SESIONES_IP_HORA = int(os.getenv("MAX_SESIONES_IP_HORA", "300"))  # en una sede todos comparten IP
MAX_MINUTOS_SESION = int(os.getenv("MAX_MINUTOS_SESION", "15"))

# --- Audio (lo fija la API Live; no cambiar) ---
FRECUENCIA_ENTRADA = 16000  # PCM 16 bits mono little-endian
FRECUENCIA_SALIDA = 24000  # PCM 16 bits mono little-endian
