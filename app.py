import html
import json
import os
import logging
from contextlib import asynccontextmanager
from typing import Optional

from psycopg2.pool import ThreadedConnectionPool
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, Field, field_validator

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SUPABASE_CONNECTION_STRING = os.getenv("SUPABASE_CONNECTION_STRING")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)
EMBEDDING_MODEL = "text-embedding-3-large"
CHAT_MODEL = "gpt-4o-mini"

try:
    db_pool = ThreadedConnectionPool(1, 10, SUPABASE_CONNECTION_STRING, cursor_factory=RealDictCursor)
except Exception as e:
    print(f"ERROR al conectar a la base de datos: {e}")
    db_pool = None


def get_db():
    if db_pool is None:
        raise HTTPException(status_code=503, detail="Database connection is unavailable")
    return db_pool.getconn()


def put_db(conn):
    if db_pool is not None:
        db_pool.putconn(conn)


_query_count = 0

_embedding_cache = {}
_EMBEDDING_CACHE_MAX = 100


def generar_embedding(texto: str) -> list[float]:
    cached = _embedding_cache.get(texto)
    if cached is not None:
        return cached
    resp = client.embeddings.create(model=EMBEDDING_MODEL, input=texto)
    emb = resp.data[0].embedding
    if len(_embedding_cache) >= _EMBEDDING_CACHE_MAX:
        _embedding_cache.pop(next(iter(_embedding_cache)))
    _embedding_cache[texto] = emb
    return emb


def buscar_contexto(query: str, top_k: int = 2) -> list[dict]:
    embedding = generar_embedding(query)
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, content, collection_id,
                           ROUND((1 - (embedding <=> %s::vector))::numeric, 4) AS score
                   FROM documents
                   WHERE embedding IS NOT NULL
                   ORDER BY embedding <=> %s::vector
                   LIMIT %s""",
                (embedding, embedding, top_k),
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        put_db(conn)


# ─────────────────────────────────────────────────────────────
#  MODELOS DE SOLICITUD Y RESPUESTA
# ─────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)

    @field_validator("message")
    @classmethod
    def sanitizar(cls, v: str) -> str:
        return html.escape(v.strip())


class RespuestaPregunta(BaseModel):
    pregunta_id: int = Field(..., ge=1, le=11)
    respuesta: bool


class CalcularEvaluacionRequest(BaseModel):
    empresa_id: str = Field(..., min_length=1, max_length=64)
    respuestas: list[RespuestaPregunta] = Field(..., min_length=1, max_length=11)


class InfoBrecha(BaseModel):
    pregunta_id: int
    categoria: str
    pregunta: str
    peso: float


class InfoCategoria(BaseModel):
    obtenido: float
    posible: float
    porcentaje: float


class DetalleEvaluacion(BaseModel):
    puntaje_final: float
    total_posible: float
    puntaje_obtenido: float
    categorias: dict[str, InfoCategoria]
    respuestas: list[dict]


class CalcularEvaluacionResponse(BaseModel):
    puntaje_final: float
    nivel_cumplimiento: str
    brechas: list[InfoBrecha]
    detalle: DetalleEvaluacion


class ConsultorRequest(BaseModel):
    mensaje: str = Field(..., min_length=1, max_length=3000)
    brechas: Optional[list[InfoBrecha]] = None
    pregunta_id: Optional[int] = Field(default=None, ge=1, le=11)

    @field_validator("mensaje")
    @classmethod
    def sanitizar(cls, v: str) -> str:
        return html.escape(v.strip())


class ConsultorResponse(BaseModel):
    respuesta: str
    fuentes: int
    modo: str


# ─────────────────────────────────────────────────────────────
#  APLICACIÓN FASTAPI
# ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Backend iniciado en http://localhost:8000")
    yield
    if db_pool is not None:
        db_pool.closeall()


app = FastAPI(title="Cavaltec - Autodiagnóstico Ley 1581", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def index():
    return RedirectResponse(url="/static/index.html")


@app.get("/metrics")
def metrics():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total FROM documents")
            total_docs = cur.fetchone()["total"]

            cur.execute("SELECT COUNT(*) AS total FROM collections")
            total_cols = cur.fetchone()["total"]

            cur.execute("SELECT COUNT(*) AS total FROM documents WHERE embedding IS NOT NULL")
            total_embedded = cur.fetchone()["total"]

        return {
            "documentos": total_docs,
            "colecciones": total_cols,
            "embeddings": total_embedded,
            "consultas": _query_count,
        }
    except Exception as e:
        logger.error("Error en /metrics: %s", str(e))
        return {"documentos": 0, "colecciones": 0, "embeddings": 0}
    finally:
        put_db(conn)


# ─────────────────────────────────────────────────────────────
#  ENDPOINT DE CÁLCULO DE EVALUACIÓN
# ─────────────────────────────────────────────────────────────

@app.post("/api/evaluacion/calcular", response_model=CalcularEvaluacionResponse)
def calcular_evaluacion(req: CalcularEvaluacionRequest):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, orden, categoria, pregunta, peso FROM preguntas ORDER BY orden"
            )
            preguntas = cur.fetchall()

            # Auto‑registrar empresa demo si no existe
            cur.execute("SELECT id FROM empresas WHERE id = %s", (req.empresa_id,))
            if not cur.fetchone():
                nit = "DEMO-" + req.empresa_id[:8].upper()
                cur.execute(
                    """INSERT INTO empresas (id, nombre, nit, sector, tamano)
                       VALUES (%s, 'Empresa Demo', %s, 'Tecnología', 'mediana')
                       ON CONFLICT (id) DO NOTHING""",
                    (req.empresa_id, nit),
                )

            pesos_map = {p["orden"]: float(p["peso"]) for p in preguntas}
            cats_map = {p["orden"]: p["categoria"] for p in preguntas}
            texts_map = {p["orden"]: p["pregunta"] for p in preguntas}

            respuestas_dict = {r.pregunta_id: r.respuesta for r in req.respuestas}

            q1_ok = respuestas_dict.get(1, False)

            total_q2_q5 = sum(pesos_map[q] for q in [2, 3, 4, 5])
            true_q2_q5 = sum(
                pesos_map[q] for q in [2, 3, 4, 5] if respuestas_dict.get(q, False)
            )

            puntaje_obtenido = 0.0
            total_posible = 0.0
            brechas: list[InfoBrecha] = []
            categorias: dict[str, dict] = {}
            detalle_respuestas: list[dict] = []

            for p in preguntas:
                orden = p["orden"]
                peso = pesos_map[orden]
                cat = cats_map[orden]
                texto = texts_map[orden]

                if orden == 11:
                    continue

                if orden == 1:
                    resp = q1_ok
                    peso_efectivo = true_q2_q5 if resp else 0.0
                    puntaje_obtenido += peso_efectivo
                    total_posible += total_q2_q5
                    if peso_efectivo < total_q2_q5:
                        brechas.append(InfoBrecha(
                            pregunta_id=orden, categoria=cat,
                            pregunta=texto, peso=round(total_q2_q5 - peso_efectivo, 2),
                        ))
                else:
                    resp = respuestas_dict.get(orden, False)
                    peso_efectivo = peso if resp else 0.0
                    if not q1_ok and cat == "politica_datos":
                        peso_efectivo = 0.0
                    puntaje_obtenido += peso_efectivo
                    total_posible += peso
                    if not resp or (not q1_ok and cat == "politica_datos"):
                        brechas.append(InfoBrecha(
                            pregunta_id=orden, categoria=cat,
                            pregunta=texto, peso=peso,
                        ))

                if cat not in categorias:
                    categorias[cat] = {"obtenido": 0.0, "posible": 0.0}

                categorias[cat]["obtenido"] += peso_efectivo
                categorias[cat]["posible"] += (
                    total_q2_q5 if orden == 1 else peso
                )

                detalle_respuestas.append({
                    "pregunta_id": orden,
                    "pregunta": texto,
                    "categoria": cat,
                    "peso": peso,
                    "peso_efectivo": round(peso_efectivo, 2),
                    "respuesta": resp,
                })

            puntaje_final = round((puntaje_obtenido / total_posible) * 100, 2)

            if puntaje_final >= 80:
                nivel = "Avanzado"
            elif puntaje_final >= 50:
                nivel = "Intermedio"
            else:
                nivel = "Inicial"

            detalle_categorias = {}
            for cat, vals in categorias.items():
                pct = round((vals["obtenido"] / vals["posible"]) * 100, 2) if vals["posible"] > 0 else 0.0
                detalle_categorias[cat] = InfoCategoria(
                    obtenido=round(vals["obtenido"], 2),
                    posible=round(vals["posible"], 2),
                    porcentaje=pct,
                )

            cur.execute(
                "INSERT INTO evaluaciones (empresa_id, puntaje_final, respuestas) VALUES (%s, %s, %s::jsonb)",
                (req.empresa_id, puntaje_final, json.dumps(respuestas_dict, ensure_ascii=False)),
            )
        conn.commit()

        return CalcularEvaluacionResponse(
            puntaje_final=puntaje_final,
            nivel_cumplimiento=nivel,
            brechas=brechas,
            detalle=DetalleEvaluacion(
                puntaje_final=puntaje_final,
                total_posible=round(total_posible, 2),
                puntaje_obtenido=round(puntaje_obtenido, 2),
                categorias=detalle_categorias,
                respuestas=detalle_respuestas,
            ),
        )
    except Exception as e:
        conn.rollback()
        logger.error("Error en /api/evaluacion/calcular: %s", str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error interno: {e}")
    finally:
        put_db(conn)


# ─────────────────────────────────────────────────────────────
#  ENDPOINT DE CONSULTOR IA (RAG + Ley 1581)
# ─────────────────────────────────────────────────────────────

_LEY1581_PROMPT = (
    "Eres un consultor experto en protección de datos personales y cumplimiento normativo "
    "especializado en la Ley 1581 de 2012 de Colombia y sus decretos reglamentarios (1377 de 2013, "
    "090 de 2022, 1081 de 2015). Tu misión es asesorar a empresas colombianas en su proceso de "
    "autodiagnóstico y adecuación normativa.\n\n"

    "REGLAS GENERALES:\n"
    "1. Responde SIEMPRE en español claro y accesible. Traduce términos jurídicos a lenguaje sencillo.\n"
    "2. Basa tus respuestas en el contexto normativo que se te proporciona. Si no tienes contexto "
    "suficiente, indica honestamente los límites de tu conocimiento.\n"
    "3. Sé práctico y accionable. Cada recomendación debe poder ejecutarse en el contexto de una "
    "PYME colombiana.\n"
    "4. No inventes artículos o plazos legales. Si no los tienes en el contexto, omítelos.\n\n"

    "MODO 1 — AYUDA POR PREGUNTA:\n"
    "Cuando el usuario mencione una pregunta específica del diagnóstico o su número (Q1-Q11):\n"
    "- Explica QUÉ significa legal y prácticamente esa pregunta.\n"
    "- Traduce los términos técnicos (ej: \"hábeas data\", \"EIPD\", \"minimización\") a lenguaje cotidiano.\n"
    "- Da ejemplos concretos de cómo se vería el cumplimiento en una empresa real.\n"
    "- Ayuda al usuario a interpretar si su empresa cumple o no, sin decidir por él.\n"
    "- Relaciona la pregunta con el bloque al que pertenece (Política de datos, Privacidad desde el "
    "diseño o Gobernanza).\n\n"

    "MODO 2 — PLAN DE ACCIÓN:\n"
    "Cuando recibas una lista de brechas (preguntas marcadas como False), estructura tu respuesta así:\n"
    "- ENCABEZADO: Resumen ejecutivo del nivel de cumplimiento y urgencia.\n"
    "- PRIORIZACIÓN: Ordena las brechas de mayor a menor peso, explicando por qué cada una es crítica.\n"
    "- RECOMENDACIONES: Para cada brecha, entrega 2-3 acciones concretas y medibles. Indica "
    "responsable sugerido, esfuerzo estimado (bajo/medio/alto) y plazo sugerido.\n"
    "- HOJA DE RUTA: Agrupa las acciones en fases (corto, mediano, largo plazo) mostrando dependencias "
    "entre tareas.\n"
    "- CIERRE: Recomendación general y próxima revisión sugerida.\n\n"

    "TONO: Profesional pero cercano, como un consultor senior que habla con el responsable de "
    "cumplimiento de una empresa. Usa viñetas, negritas y separaciones claras para facilitar la lectura."
)


@app.post("/api/ia/consultor", response_model=ConsultorResponse)
def consultor_ia(req: ConsultorRequest):
    global _query_count
    _query_count += 1

    modo = "plan_accion" if req.brechas else "ayuda"
    top_k = 4 if modo == "plan_accion" else 3

    try:
        docs = buscar_contexto(req.mensaje, top_k=top_k)
        contexto = "\n\n".join(
            f"[Fuente {i+1} (score={d['score']})]\n"
            + json.dumps(d["content"], ensure_ascii=False)
            for i, d in enumerate(docs)
        )

        user_parts = [f"Contexto normativo:\n{contexto}"]

        if modo == "ayuda":
            if req.pregunta_id:
                conn = get_db()
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT orden, pregunta, descripcion, peso, categoria "
                            "FROM preguntas WHERE orden = %s",
                            (req.pregunta_id,),
                        )
                        row = cur.fetchone()
                finally:
                    put_db(conn)

                if row:
                    cat_labels = {
                        "politica_datos": "Política de datos",
                        "privacidad_diseno": "Privacidad desde el diseño",
                        "gobernanza": "Gobernanza",
                    }
                    user_parts.append(
                        f"Datos de la pregunta:\n"
                        f"- Número: Q{row['orden']}\n"
                        f"- Bloque: {cat_labels.get(row['categoria'], row['categoria'])}\n"
                        f"- Enunciado: {row['pregunta']}\n"
                        f"- Peso: {float(row['peso'])}%\n"
                        f"- Descripción: {row['descripcion'] or 'N/A'}"
                    )

            user_parts.append(f"Consulta del usuario:\n{req.mensaje}")

        else:
            brechas_texto = "\n".join(
                f"- Q{b.pregunta_id} [{b.categoria}] ({b.peso}%): {b.pregunta}"
                for b in req.brechas
            )
            user_parts.append(
                f"Resultado del autodiagnóstico — BREACHAS DETECTADAS:\n{brechas_texto}\n\n"
                f"Consulta del usuario:\n{req.mensaje}\n\n"
                "Genera el Plan de Acción detallado según las instrucciones del prompt del sistema."
            )

        messages = [
            {"role": "system", "content": _LEY1581_PROMPT},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ]

        resp = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=messages,
            temperature=0.3 if modo == "plan_accion" else 0.5,
            max_tokens=2048 if modo == "plan_accion" else 1024,
        )

        return ConsultorResponse(
            respuesta=resp.choices[0].message.content,
            fuentes=len(docs),
            modo=modo,
        )
    except Exception as e:
        logger.error("Error en /api/ia/consultor: %s", str(e), exc_info=True)
        return ConsultorResponse(
            respuesta=f"Error interno: {type(e).__name__}: {e}",
            fuentes=0,
            modo=modo,
        )


# ─────────────────────────────────────────────────────────────
#  ENDPOINT LEGACY CHAT (RAG genérico)
# ─────────────────────────────────────────────────────────────

@app.post("/chat")
def chat(req: ChatRequest):
    global _query_count
    _query_count += 1
    try:
        docs = buscar_contexto(req.message)
        contexto = "\n\n".join(
            json.dumps(d["content"], ensure_ascii=False) for d in docs
        )

        messages = [
            {"role": "system", "content": "Eres un asistente que responde preguntas sobre datos almacenados en Supabase. Usa el contexto proporcionado para responder. Si no hay contexto útil, responde con lo que sepas."},
            {"role": "user", "content": f"Contexto:\n{contexto}\n\nPregunta: {req.message}"},
        ]

        resp = client.chat.completions.create(model=CHAT_MODEL, messages=messages)
        return {"respuesta": resp.choices[0].message.content, "fuentes": len(docs)}
    except Exception as e:
        logger.error("Error en /chat: %s", str(e), exc_info=True)
        return {"respuesta": f"Error interno: {type(e).__name__}: {e}", "fuentes": 0}
