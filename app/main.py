from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.auth import router as auth_router
from app.config import Settings
from app.database import REQUIRED_TABLES, SCHEMA_REVISION, build_engine


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configuration = settings or Settings()
        engine = build_engine(configuration)
        app.state.settings = configuration
        app.state.engine = engine
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(title="EventFlow API", version="0.1.0", lifespan=lifespan)
    app.include_router(auth_router)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Pydantic errors contain rejected inputs, potentially including passwords.
        errors = [
            {key: error[key] for key in ("loc", "msg", "type")}
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.get("/health/live", tags=["health"])
    def live():
        return {"status": "ok"}

    @app.get(
        "/health/ready", tags=["health"], responses={503: {"description": "Not ready"}}
    )
    def ready():
        try:
            with app.state.engine.connect() as connection:
                revisions = set(
                    connection.execute(
                        text("SELECT version_num FROM public.alembic_version")
                    ).scalars()
                )
                tables = set(
                    connection.execute(
                        text(
                            "SELECT tablename FROM pg_catalog.pg_tables "
                            "WHERE schemaname = 'public'"
                        )
                    ).scalars()
                )
                if revisions != {SCHEMA_REVISION} or not REQUIRED_TABLES <= tables:
                    return JSONResponse(
                        status_code=503, content={"status": "not_ready"}
                    )
        except SQLAlchemyError:
            # Never return connection strings, credentials, or driver errors.
            return JSONResponse(status_code=503, content={"status": "not_ready"})
        return {"status": "ready"}

    return app


app = create_app()
