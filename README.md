# Cavaltec - Autodiagnóstico Ley 1581

Backend API para el autodiagnóstico de cumplimiento de la **Ley 1581 de 2012** (Protección de Datos Personales en Colombia), con consultoría basada en **RAG (Retrieval-Augmented Generation)** usando OpenAI y pgvector.

## Stack tecnológico

- **Runtime:** Python 3.12+
- **Framework:** FastAPI
- **Base de datos:** PostgreSQL + pgvector (Supabase)
- **Embeddings:** OpenAI `text-embedding-3-large` (3072 dims)
- **Chat:** OpenAI `gpt-4o-mini`
- **Autenticación:** JWT (Supabase)

## Estructura del proyecto

```
├── app.py              # API principal (FastAPI)
├── auth.py             # Autenticación y roles
├── ingest_data.py      # Ingesta de datos CSV/texto a Supabase
├── list_data.py        # Listado de datos
├── migracion.sql       # Esquema de base de datos
├── seed_preguntas.py   # Seed de preguntas del diagnóstico
├── test_connections.py # Prueba de conexiones
├── requirements.txt    # Dependencias
├── .env                # Variables de entorno
├── .gitignore
├── static/
│   └── index.html      # Frontend estático
└── venv/               # Entorno virtual
```

## Requisitos

- Python 3.12+
- PostgreSQL con extensión `pgvector`
- Cuenta de OpenAI con API key
- (Opcional) Cuenta Supabase

## Instalación

```bash
# Clonar el repositorio
git clone <repo>
cd <repo>

# Crear entorno virtual
python -m venv venv

# Activar (Windows)
venv\Scripts\activate

# Activar (Linux/macOS)
source venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt
```

## Configuración

Crear archivo `.env`:

```env
SUPABASE_CONNECTION_STRING=postgresql://user:pass@host:5432/postgres
OPENAI_API_KEY=sk-...
```

## Base de datos

Ejecutar `migracion.sql` en el SQL Editor de Supabase o directamente en PostgreSQL:

```bash
psql <connection_string> -f migracion.sql
```

Poblar las preguntas del diagnóstico:

```bash
python seed_preguntas.py
```

## Ingesta de datos (RAG)

Cargar documentos normativos para el consultor IA:

```bash
# Desde archivo de texto
python ingest_data.py texto ley_1581.txt "Ley 1581"

# Desde CSV
python ingest_data.py csv datos.csv "Mi Colección"

# Re-embedding de documentos existentes
python ingest_data.py reembed
```

## Ejecución

```bash
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

La API estará disponible en `http://localhost:8000`.

## Endpoints

### Salud y métricas

| Método | Ruta           | Descripción                    |
|--------|----------------|--------------------------------|
| GET    | `/health`      | Health check                   |
| GET    | `/metrics`     | Estadísticas de documentos     |
| GET    | `/`            | Redirige a static/index.html   |

### Evaluación

| Método | Ruta                       | Descripción                          |
|--------|----------------------------|--------------------------------------|
| POST   | `/api/evaluacion/calcular` | Calcula puntaje de autodiagnóstico   |

**Body:**
```json
{
  "empresa_id": "uuid-demo-123",
  "respuestas": [
    { "pregunta_id": 1, "respuesta": true },
    { "pregunta_id": 2, "respuesta": false }
  ]
}
```

### Consultor IA

| Método | Ruta              | Descripción                              |
|--------|-------------------|------------------------------------------|
| POST   | `/api/ia/consultor` | Consultor especializado en Ley 1581 (RAG) |

**Body (modo ayuda):**
```json
{
  "mensaje": "¿Qué implica la pregunta Q3?",
  "pregunta_id": 3
}
```

**Body (modo plan de acción):**
```json
{
  "mensaje": "Genera un plan de acción",
  "brechas": [
    { "pregunta_id": 2, "categoria": "politica_datos", "pregunta": "...", "peso": 10.0 }
  ]
}
```

### Chat genérico

| Método | Ruta    | Descripción                       |
|--------|---------|-----------------------------------|
| POST   | `/chat` | Chat RAG genérico sobre documentos |

## Modelo de datos

### Preguntas (11 preguntas)

- **Política de datos** (Q1-Q5, peso máximo 40%)
  - Q1: Pregunta maestra — su peso depende de Q2-Q5
  - Q2-Q5: 10% cada una
- **Privacidad desde el diseño** (Q6-Q8, peso máximo 36%)
  - Q6-Q8: 12% cada una
- **Gobernanza** (Q9-Q11, peso máximo 24%)
  - Q9: 16%, Q10: 8%, Q11: 0% (complementaria)

### Niveles de cumplimiento

| Puntaje       | Nivel       |
|---------------|-------------|
| >= 80%        | Avanzado    |
| >= 50% y < 80%| Intermedio  |
| < 50%         | Inicial     |

## Autenticación

Usa JWT de Supabase. Incluir en el header:

```
Authorization: Bearer <token>
```

Roles disponibles: `administrador`, `evaluador`, `auditor`.
