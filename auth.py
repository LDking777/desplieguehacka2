import os
import logging
from typing import Optional

import jwt as pyjwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)

SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")
JWT_ALGORITHM = "HS256"

security_scheme = HTTPBearer(auto_error=False)


def verify_jwt(token: str) -> dict:
    if not SUPABASE_JWT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="SUPABASE_JWT_SECRET no configurado en el servidor",
        )
    try:
        payload = pyjwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["exp", "sub"]},
        )
        return payload
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except pyjwt.InvalidAudienceError:
        raise HTTPException(status_code=401, detail="Audiencia del token inválida")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido o malformado")


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
) -> Optional[dict]:
    if credentials is None:
        return None
    payload = verify_jwt(credentials.credentials)
    return {
        "sub": payload.get("sub"),
        "email": payload.get("email", ""),
        "provider": (payload.get("app_metadata") or {}).get("provider", "unknown"),
        "jwt_payload": payload,
    }


async def get_current_user(
    user: Optional[dict] = Depends(get_optional_user),
) -> dict:
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Autenticación requerida — envía un token Bearer válido",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_rol(roles: list[str]):
    async def _checker(
        token_user: dict = Depends(get_current_user),
    ) -> dict:
        sub = token_user.get("sub")
        if not sub:
            raise HTTPException(status_code=401, detail="Token sin subject")

        from app import get_db, put_db

        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, nombre, email, rol FROM usuarios "
                    "WHERE oauth_provider_id = %s AND activo = true",
                    (sub,),
                )
                row = cur.fetchone()
        finally:
            put_db(conn)

        if not row:
            raise HTTPException(
                status_code=403,
                detail="Usuario no registrado en la plataforma. Contacta a un administrador.",
            )

        user = dict(row)
        if user["rol"] not in roles:
            raise HTTPException(
                status_code=403,
                detail=f"Acceso denegado — se requiere rol {roles}, tienes '{user['rol']}'",
            )
        return user

    return _checker
