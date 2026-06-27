import csv
import json
import os
import logging
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from openai import OpenAI
from psycopg2.extras import RealDictCursor

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SUPABASE_CONNECTION_STRING = os.getenv("SUPABASE_CONNECTION_STRING")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not SUPABASE_CONNECTION_STRING:
    raise ValueError("SUPABASE_CONNECTION_STRING is required")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY is required")

client = OpenAI(api_key=OPENAI_API_KEY)
EMBEDDING_MODEL = "text-embedding-3-large"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 200


def _get_connection():
    return psycopg2.connect(SUPABASE_CONNECTION_STRING, cursor_factory=RealDictCursor)


def _find_or_create_collection(name: str, description: str = "") -> str:
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM collections WHERE name = %s", (name,))
            row = cur.fetchone()
            if row:
                return str(row["id"])

            cur.execute(
                "INSERT INTO collections (name, description) VALUES (%s, %s) RETURNING id",
                (name, description),
            )
            new_row = cur.fetchone()
        conn.commit()
    return str(new_row["id"])


def _generate_embedding(text: str) -> list[float]:
    resp = client.embeddings.create(model=EMBEDDING_MODEL, input=text)
    return resp.data[0].embedding


def _chunk_text(text: str) -> list[str]:
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + CHUNK_SIZE, len(words))
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        if end == len(words):
            break
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks


def cargar_csv_en_coleccion(file_path: str, collection_name: str) -> int:
    collection_id = _find_or_create_collection(collection_name, f"Importado desde {file_path}")
    path = Path(file_path)

    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        logger.warning("CSV vacío: %s", file_path)
        return 0

    with _get_connection() as conn:
        with conn.cursor() as cur:
            for row in rows:
                cur.execute(
                    """INSERT INTO documents (collection_id, content)
                       VALUES (%s, %s)""",
                    (collection_id, json.dumps(row)),
                )
        conn.commit()

    logger.info("Insertadas %d filas del CSV '%s' en colección '%s'", len(rows), file_path, collection_name)
    return len(rows)


def cargar_texto_para_rag(file_path: str, collection_name: str) -> int:
    collection_id = _find_or_create_collection(collection_name, f"RAG importado desde {file_path}")
    path = Path(file_path)
    text = path.read_text(encoding="utf-8")

    chunks = _chunk_text(text)
    if not chunks:
        logger.warning("Archivo vacío: %s", file_path)
        return 0

    with _get_connection() as conn:
        with conn.cursor() as cur:
            for chunk in chunks:
                embedding = _generate_embedding(chunk)
                content = {"texto": chunk, "fuente": file_path}
                cur.execute(
                    """INSERT INTO documents (collection_id, content, embedding)
                       VALUES (%s, %s, %s::vector)""",
                    (collection_id, json.dumps(content), embedding),
                )
        conn.commit()

    logger.info("Insertados %d chunks del texto '%s' en colección '%s'", len(chunks), file_path, collection_name)
    return len(chunks)


def reembed_existing_docs():
    """Re-embeddea todos los documentos que tienen embedding (del modelo anterior)."""
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, content FROM documents WHERE embedding IS NOT NULL")
            docs = cur.fetchall()
    finally:
        conn.close()

    if not docs:
        logger.info("No hay documentos para re-embedder.")
        return 0

    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            for i, doc in enumerate(docs):
                content = doc["content"]
                texto = content.get("texto") or json.dumps(content)
                embedding = _generate_embedding(texto)
                cur.execute(
                    "UPDATE documents SET embedding = %s::vector WHERE id = %s",
                    (embedding, doc["id"]),
                )
                if (i + 1) % 10 == 0:
                    conn.commit()
                    logger.info("Re-embedded %d/%d documentos...", i + 1, len(docs))
        conn.commit()
    finally:
        conn.close()

    logger.info("Re-embedding completado: %d documentos actualizados.", len(docs))
    return len(docs)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Ingesta de datos a Supabase (JSONB + pgvector)")
    parser.add_argument("modo", choices=["csv", "texto", "reembed"], help="Tipo de ingesta")
    parser.add_argument("file_path", nargs="?", help="Ruta del archivo CSV o TXT")
    parser.add_argument("collection_name", nargs="?", help="Nombre de la colección destino")
    args = parser.parse_args()

    if args.modo == "reembed":
        total = reembed_existing_docs()
    elif args.modo == "csv":
        total = cargar_csv_en_coleccion(args.file_path, args.collection_name)
    else:
        total = cargar_texto_para_rag(args.file_path, args.collection_name)

    logger.info("Ingesta completada: %d registros insertados.", total)
