-- Migración: Reto Cavaltec — Autodiagnóstico Ley 1581
-- Pegar directamente en el SQL Editor de Supabase

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================
-- 1. CATÁLOGO MULTIEMPRESA
-- ============================================================
CREATE TABLE IF NOT EXISTS empresas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre TEXT NOT NULL,
    nit TEXT NOT NULL UNIQUE,
    sector TEXT,
    tamano TEXT CHECK (tamano IN ('pequena', 'mediana', 'grande')),
    oauth_provider TEXT,
    oauth_provider_id TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    activa BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- 2. USUARIOS CON ROLES
-- ============================================================
CREATE TABLE IF NOT EXISTS usuarios (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    empresa_id UUID NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT,
    rol TEXT NOT NULL CHECK (rol IN ('administrador', 'evaluador', 'auditor')),
    oauth_provider TEXT,
    oauth_provider_id TEXT,
    activo BOOLEAN NOT NULL DEFAULT true,
    ultimo_acceso TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- 3. BLOQUE DE EVALUACIÓN — PREGUNTAS LEY 1581
-- ============================================================
CREATE TABLE IF NOT EXISTS preguntas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    categoria TEXT NOT NULL CHECK (categoria IN ('politica_datos', 'privacidad_diseno', 'gobernanza')),
    pregunta TEXT NOT NULL,
    descripcion TEXT,
    peso NUMERIC(4,2) NOT NULL CHECK (peso >= 0 AND peso <= 100),
    orden INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Las 11 preguntas oficiales del diagnóstico Reto Cavaltec
INSERT INTO preguntas (categoria, pregunta, descripcion, peso, orden) VALUES
-- Política de datos (máx 40%): Q1 hereda peso de Q2-Q5
('politica_datos',
 '¿La empresa tiene una política de tratamiento de datos personales publicada y accesible?',
 'Pregunta maestra — su peso efectivo depende de las respuestas de Q2 a Q5.',
 0.00, 1),

('politica_datos',
 '¿La política de datos está actualizada conforme a la Ley 1581 y sus decretos reglamentarios?',
 'Verifica que la política refleje los cambios normativos más recientes.',
 10.00, 2),

('politica_datos',
 '¿Existe un procedimiento formal para atender consultas, reclamos y solicitudes de los titulares?',
 'Evalúa los mecanismos de atención al titular (PQRs, derecho de hábeas data).',
 10.00, 3),

('politica_datos',
 '¿La empresa ha designado un oficial de protección de datos o responsable del tratamiento?',
 'Verifica la existencia del responsable ante la SIC.',
 10.00, 4),

('politica_datos',
 '¿Se aplican principios de privacidad desde el diseño en todos los nuevos proyectos o sistemas?',
 'Evalúa si la privacidad se incorpora en la fase de diseño y no como añadido posterior.',
 10.00, 5),

-- Privacidad desde el diseño (máx 36%)
('privacidad_diseno',
 '¿Se realizan evaluaciones de impacto a la protección de datos (EIPD) antes de implementar nuevos tratamientos?',
 'Mide el uso de EIPD para identificar y mitigar riesgos de privacidad.',
 12.00, 6),

('privacidad_diseno',
 '¿Los sistemas y procesos minimizan la recolección de datos personales al mínimo necesario?',
 'Evalúa la aplicación del principio de minimización y proporcionalidad.',
 12.00, 7),

('privacidad_diseno',
 '¿Existe un comité o equipo de gobierno de datos que supervise el cumplimiento normativo?',
 'Verifica la existencia de una estructura de gobernanza de datos.',
 12.00, 8),

-- Gobernanza (máx 24%)
('gobernanza',
 '¿Se realizan auditorías internas o externas periódicas sobre protección de datos personales?',
 'Evalúa la frecuencia y rigurosidad de las auditorías de cumplimiento.',
 16.00, 9),

('gobernanza',
 '¿La empresa capacita a sus colaboradores en protección de datos personales de forma continua?',
 'Mide los programas de formación y sensibilización del personal.',
 8.00, 10),

('gobernanza',
 '¿Existe un procedimiento documentado para la gestión y notificación de brechas de seguridad?',
 'Complementaria — no suma al puntaje final. Evalúa preparación ante incidentes.',
 0.00, 11);

-- ============================================================
-- 4. HISTORIAL DE EVALUACIONES
-- ============================================================
CREATE TABLE IF NOT EXISTS evaluaciones (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    empresa_id UUID NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    usuario_id UUID REFERENCES usuarios(id) ON DELETE SET NULL,
    fecha TIMESTAMPTZ NOT NULL DEFAULT now(),
    puntaje_final NUMERIC(5,2) NOT NULL CHECK (puntaje_final >= 0 AND puntaje_final <= 100),
    respuestas JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- 5. TABLAS RAG (compatibles con pgvector)
-- ============================================================
CREATE TABLE IF NOT EXISTS collections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    collection_id UUID NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    content JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding vector(3072),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- 6. ÍNDICES
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_empresas_nit ON empresas(nit);
CREATE INDEX IF NOT EXISTS idx_empresas_oauth ON empresas(oauth_provider, oauth_provider_id);
CREATE INDEX IF NOT EXISTS idx_usuarios_email ON usuarios(email);
CREATE INDEX IF NOT EXISTS idx_usuarios_empresa ON usuarios(empresa_id);
CREATE INDEX IF NOT EXISTS idx_usuarios_oauth ON usuarios(oauth_provider, oauth_provider_id);
CREATE INDEX IF NOT EXISTS idx_preguntas_orden ON preguntas(orden);
CREATE INDEX IF NOT EXISTS idx_preguntas_categoria ON preguntas(categoria);
CREATE INDEX IF NOT EXISTS idx_evaluaciones_empresa ON evaluaciones(empresa_id);
CREATE INDEX IF NOT EXISTS idx_evaluaciones_fecha ON evaluaciones(empresa_id, fecha DESC);
CREATE INDEX IF NOT EXISTS idx_documents_collection_id ON documents(collection_id);
CREATE INDEX IF NOT EXISTS idx_collections_name ON collections(name);

-- Nota: pgvector en Supabase limita los índices a 2000 dims.
-- Cuando actualicen a pgvector >= 0.7.0, ejecutar:
-- CREATE INDEX ON documents USING hnsw (embedding vector_cosine_ops);
