"""FastAPI application factory + CORS middleware + lifespan (migrations)."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import internal_router, kb_router, router, run_migrations


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Startup: run DB migrations, eagerly init Agent Runtime (worker + recovery)."""
    await run_migrations()
    # Eager init agent runtime — starts Stream worker + recovery loop
    from app.api.routes import get_contract_dispatcher
    get_contract_dispatcher()  # contract mode (default)
    yield
    # Shutdown: stop the Stream worker gracefully
    try:
        from app.api.routes import _agent_worker
        if _agent_worker is not None:
            await _agent_worker.stop()
    except Exception:
        pass


app = FastAPI(
    title="AtlasMind AI Service API",
    version="1.0.0",
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/chat")
app.include_router(kb_router, prefix="/api/kb")
app.include_router(internal_router, prefix="/internal")
