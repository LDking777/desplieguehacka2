import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_CONNECTION_STRING = os.getenv("SUPABASE_CONNECTION_STRING")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


def test_supabase():
    import psycopg2

    conn = psycopg2.connect(SUPABASE_CONNECTION_STRING)
    with conn.cursor() as cur:
        cur.execute("SELECT 1;")
        cur.fetchone()
    conn.close()
    print("[OK] Conexion a Supabase Exitosa!")


def test_gemini():
    from google import genai

    client = genai.Client(api_key=GEMINI_API_KEY)
    resp = client.models.embed_content(model="gemini-embedding-001", contents="test")
    _ = resp.embeddings[0].values
    print("[OK] Conexion a la API de Gemini Exitosa!")


if __name__ == "__main__":
    test_supabase()
    test_gemini()
