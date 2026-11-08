import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

SUPABASE_CONNECTION_STRING = os.getenv("SUPABASE_CONNECTION_STRING")

if not SUPABASE_CONNECTION_STRING:
    print("Error: SUPABASE_CONNECTION_STRING no está configurado en el archivo .env")
    exit(1)

def get_connection():
    return psycopg2.connect(SUPABASE_CONNECTION_STRING, cursor_factory=RealDictCursor)

def list_collections_and_documents():
    try:
        conn = get_connection()
    except Exception as e:
        print(f"Error al conectar a Supabase: {e}")
        return

    try:
        with conn.cursor() as cur:
            # Obtener todas las colecciones
            cur.execute("SELECT id, name, description, metadata, created_at FROM collections ORDER BY name;")
            collections = cur.fetchall()

            if not collections:
                print("No se encontraron colecciones en la base de datos.")
                return

            print(f"=== Se encontraron {len(collections)} colección(es) ===\n")

            for col in collections:
                col_id = col["id"]
                name = col["name"]
                desc = col.get("description") or "Sin descripción"
                metadata = col.get("metadata") or {}
                created_at = col["created_at"]

                print(f"📌 Colección: {name}")
                print(f"   ID: {col_id}")
                print(f"   Descripción: {desc}")
                print(f"   Metadata: {json.dumps(metadata, ensure_ascii=False)}")
                print(f"   Creado el: {created_at}")

                # Obtener documentos de esta colección
                cur.execute(
                    "SELECT id, content, (embedding IS NOT NULL) as has_embedding, created_at FROM documents WHERE collection_id = %s ORDER BY created_at;",
                    (col_id,)
                )
                documents = cur.fetchall()

                print(f"   📄 Documentos vinculados: {len(documents)}")
                if not documents:
                    print("      No hay documentos en esta colección.")
                else:
                    for i, doc in enumerate(documents, 1):
                        doc_id = doc["id"]
                        content = doc["content"]
                        has_embedding = "Sí" if doc["has_embedding"] else "No"
                        created = doc["created_at"]

                        print(f"\n      [{i}] Documento ID: {doc_id}")
                        print(f"          Tiene Embedding: {has_embedding}")
                        print(f"          Creado el: {created}")
                        print("          Contenido:")
                        # Pretty print the content JSON indented
                        content_str = json.dumps(content, indent=14, ensure_ascii=False).strip()
                        print(f"              {content_str}")
                print("\n" + "="*50 + "\n")

    except Exception as e:
        print(f"Error al consultar la base de datos: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    list_collections_and_documents()
