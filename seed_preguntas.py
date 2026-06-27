import os
import logging

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SUPABASE_CONNECTION_STRING = os.getenv("SUPABASE_CONNECTION_STRING")

if not SUPABASE_CONNECTION_STRING:
    raise ValueError("SUPABASE_CONNECTION_STRING is required")

PREGUNTAS = [
    # === Bloque Política de datos (máx 40%) ===
    {
        "orden": 1,
        "categoria": "politica_datos",
        "pregunta": "¿La empresa tiene una política de tratamiento de datos personales publicada y accesible?",
        "descripcion": "Pregunta maestra — su peso efectivo depende de las respuestas de Q2 a Q5.",
        "peso": 0.00,
    },
    {
        "orden": 2,
        "categoria": "politica_datos",
        "pregunta": "¿La política de datos está actualizada conforme a la Ley 1581 y sus decretos reglamentarios?",
        "descripcion": "Verifica que la política refleje los cambios normativos más recientes.",
        "peso": 10.00,
    },
    {
        "orden": 3,
        "categoria": "politica_datos",
        "pregunta": "¿Existe un procedimiento formal para atender consultas, reclamos y solicitudes de los titulares?",
        "descripcion": "Evalúa los mecanismos de atención al titular (PQRs, derecho de hábeas data).",
        "peso": 10.00,
    },
    {
        "orden": 4,
        "categoria": "politica_datos",
        "pregunta": "¿La empresa ha designado un oficial de protección de datos o responsable del tratamiento?",
        "descripcion": "Verifica la existencia del responsable ante la SIC.",
        "peso": 10.00,
    },
    {
        "orden": 5,
        "categoria": "politica_datos",
        "pregunta": "¿Se aplican principios de privacidad desde el diseño en todos los nuevos proyectos o sistemas?",
        "descripcion": "Evalúa si la privacidad se incorpora en la fase de diseño y no como añadido posterior.",
        "peso": 10.00,
    },
    # === Bloque Privacidad desde el diseño (máx 36%) ===
    {
        "orden": 6,
        "categoria": "privacidad_diseno",
        "pregunta": "¿Se realizan evaluaciones de impacto a la protección de datos (EIPD) antes de implementar nuevos tratamientos?",
        "descripcion": "Mide el uso de EIPD para identificar y mitigar riesgos de privacidad.",
        "peso": 12.00,
    },
    {
        "orden": 7,
        "categoria": "privacidad_diseno",
        "pregunta": "¿Los sistemas y procesos minimizan la recolección de datos personales al mínimo necesario?",
        "descripcion": "Evalúa la aplicación del principio de minimización y proporcionalidad.",
        "peso": 12.00,
    },
    {
        "orden": 8,
        "categoria": "privacidad_diseno",
        "pregunta": "¿Existe un comité o equipo de gobierno de datos que supervise el cumplimiento normativo?",
        "descripcion": "Verifica la existencia de una estructura de gobernanza de datos.",
        "peso": 12.00,
    },
    # === Bloque Gobernanza (máx 24%) ===
    {
        "orden": 9,
        "categoria": "gobernanza",
        "pregunta": "¿Se realizan auditorías internas o externas periódicas sobre protección de datos personales?",
        "descripcion": "Evalúa la frecuencia y rigurosidad de las auditorías de cumplimiento.",
        "peso": 16.00,
    },
    {
        "orden": 10,
        "categoria": "gobernanza",
        "pregunta": "¿La empresa capacita a sus colaboradores en protección de datos personales de forma continua?",
        "descripcion": "Mide los programas de formación y sensibilización del personal.",
        "peso": 8.00,
    },
    {
        "orden": 11,
        "categoria": "gobernanza",
        "pregunta": "¿Existe un procedimiento documentado para la gestión y notificación de brechas de seguridad?",
        "descripcion": "Complementaria — no suma al puntaje final. Evalúa preparación ante incidentes.",
        "peso": 0.00,
    },
]

CATEGORIA_LABELS = {
    "politica_datos": "Política de datos",
    "privacidad_diseno": "Privacidad desde el diseño",
    "gobernanza": "Gobernanza",
}


def seed_preguntas():
    conn = psycopg2.connect(
        SUPABASE_CONNECTION_STRING, cursor_factory=RealDictCursor
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT orden FROM preguntas ORDER BY orden")
            existentes = {r["orden"] for r in cur.fetchall()}

            insertados = 0
            omitidos = 0

            for p in PREGUNTAS:
                if p["orden"] in existentes:
                    cur.execute(
                        """UPDATE preguntas
                           SET categoria = %s, pregunta = %s, descripcion = %s, peso = %s
                           WHERE orden = %s""",
                        (p["categoria"], p["pregunta"],
                         p["descripcion"], p["peso"], p["orden"]),
                    )
                    omitidos += 1
                    logger.info("Actualizada Q%d: %s", p["orden"], p["pregunta"][:60])
                else:
                    cur.execute(
                        """INSERT INTO preguntas (categoria, pregunta, descripcion, peso, orden)
                           VALUES (%s, %s, %s, %s, %s)""",
                        (p["categoria"], p["pregunta"],
                         p["descripcion"], p["peso"], p["orden"]),
                    )
                    insertados += 1
                    logger.info("Insertada Q%d: %s", p["orden"], p["pregunta"][:60])

        conn.commit()

        total = len(PREGUNTAS)
        logger.info("Seed completado — %d insertadas, %d actualizadas de %d preguntas",
                     insertados, omitidos, total)
        return insertados, omitidos
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def listar_preguntas():
    conn = psycopg2.connect(
        SUPABASE_CONNECTION_STRING, cursor_factory=RealDictCursor
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT orden, categoria, pregunta, peso FROM preguntas ORDER BY orden"
            )
            preguntas = cur.fetchall()

        if not preguntas:
            logger.warning("No hay preguntas en la base de datos.")
            return

        print()
        print("=" * 72)
        print("  PREGUNTAS DE AUTODIAGNÓSTICO — LEY 1581")
        print("=" * 72)

        bloque_actual = None
        for p in preguntas:
            label = CATEGORIA_LABELS.get(p["categoria"], p["categoria"])
            if label != bloque_actual:
                bloque_actual = label
                print(f"\n  ▸ {bloque_actual}")

            herencia = "  (hereda peso de Q2-Q5)" if p["orden"] == 1 else ""
            complementaria = "  (complementaria)" if p["orden"] == 11 else ""
            print(f"    Q{p['orden']:2d}  [{p['peso']:5.1f}%]{herencia}{complementaria}")
            print(f"         {p['pregunta']}")

        print()
        print(f"  Total preguntas: {len(preguntas)}")
        print("=" * 72)
        print()
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Seed de preguntas del autodiagnóstico Ley 1581"
    )
    parser.add_argument(
        "accion", nargs="?", default="seed",
        choices=["seed", "listar"],
        help="'seed' para insertar/actualizar (default), 'listar' para consultar",
    )
    args = parser.parse_args()

    if args.accion == "listar":
        listar_preguntas()
    else:
        insertados, omitidos = seed_preguntas()
        logger.info("Hecho: %d insertadas, %d actualizadas.", insertados, omitidos)
