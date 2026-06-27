import os
import sys
import signal

# Poner conexion que falle rápido (connection refused)
os.environ["SUPABASE_CONNECTION_STRING"] = "postgresql://invalido:falsa@127.0.0.1:1/nonexistent"
os.environ["OPENAI_API_KEY"] = "sk-test-fake-key-12345"

import app
from fastapi.testclient import TestClient

client = TestClient(app.app)

# 1. Health endpoint (no DB) -> 200
r = client.get("/health")
print(f"/health -> {r.status_code}")
assert r.status_code == 200

# 2. Metrics endpoint (usa DB) -> 503
r = client.get("/metrics")
print(f"/metrics -> {r.status_code} body={r.text[:100]}")
assert r.status_code == 503

# 3. Evaluacion endpoint (usa DB) -> 503
r = client.post("/api/evaluacion/calcular", json={
    "empresa_id": "test-123",
    "respuestas": [{"pregunta_id": 1, "respuesta": True}]
})
print(f"/api/evaluacion/calcular -> {r.status_code}")
assert r.status_code == 503

print("\n✔ Prueba exitosa: servidor arranca sin DB, endpoints devuelven 503")
