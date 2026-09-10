from __future__ import annotations

from contextlib import asynccontextmanager
import hmac
import math
import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator
from acoustic_sync.timeline.rates import parse_rate

from .jobs import ARTIFACTS, JobManager
from .filesystem import browse

STATIC = Path(__file__).parent / "static"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class BrowseRequest(BaseModel):
    path: str | None = Field(default=None, max_length=4096)
    initial: bool = False
    show_xml: bool = False
    offset: int = Field(default=0, ge=0)


class JobRequest(BaseModel):
    input_dir: str = Field(min_length=1, max_length=4096)
    output_xml: str = Field(min_length=1, max_length=4096)
    fps: str = "25"
    confidence_threshold: float = Field(default=70, ge=0, le=100)
    workers: int = Field(default=2, ge=1, le=64)

    @field_validator("fps", mode="before")
    @classmethod
    def frame_rate(cls, value):
        if isinstance(value, bool):
            raise ValueError("Frame rate must be a number or rational")
        text = str(value).strip()
        if not 0 < parse_rate(text) <= 240:
            raise ValueError("Frame rate must be between 0 and 240")
        return text


def authority(value):
    try:
        parsed = urlsplit(value)
        if parsed.scheme != "http" or parsed.username or parsed.password or parsed.hostname not in LOCAL_HOSTS:
            return None
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            return None
        return parsed.hostname, parsed.port or 80
    except ValueError:
        return None


def create_app(state_dir: Path | None = None):
    root = state_dir if state_dir is not None else Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "state"))) / "AcousticSync" / "web"
    manager = JobManager(Path(root))
    sessions = {}

    @asynccontextmanager
    async def lifespan(app):
        manager.start()
        try:
            yield
        finally:
            manager.stop()
            sessions.clear()

    app = FastAPI(title="Acoustic Sync", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.manager = manager

    @app.middleware("http")
    async def local_security(request: Request, call_next):
        host = authority("http://" + request.headers.get("host", ""))
        server = request.scope.get("server")
        if not host or (server and server[1] and host[1] != server[1]):
            return JSONResponse({"detail": "Localhost Host with the server port required"}, status_code=403)
        origin = request.headers.get("origin")
        if origin is not None and authority(origin) != host:
            return JSONResponse({"detail": "Same-origin localhost request required"}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "Cross-site requests are forbidden"}, status_code=403)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            token = sessions.get(request.cookies.get("acoustic_session", ""))
            supplied = request.headers.get("x-session-token", "")
            if not token or not hmac.compare_digest(token, supplied):
                return JSONResponse({"detail": "Valid session token required; reload the page"}, status_code=403)
        response = await call_next(request)
        response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                 "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
                                 "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        return response

    @app.get("/api/session")
    def session(request: Request):
        identifier = request.cookies.get("acoustic_session", "")
        if identifier not in sessions:
            identifier = secrets.token_urlsafe(32)
            if len(sessions) >= 256:
                sessions.pop(next(iter(sessions)))
            sessions[identifier] = secrets.token_urlsafe(32)
        response = JSONResponse({"token": sessions[identifier]})
        response.set_cookie("acoustic_session", identifier, httponly=True, samesite="strict", path="/")
        return response

    @app.post("/api/filesystem/browse")
    def browse_folder(values: BrowseRequest):
        try:
            return browse(values.path, initial=values.initial, show_xml=values.show_xml, offset=values.offset)
        except PermissionError as exc:
            raise HTTPException(403, "This folder is not accessible") from exc
        except FileNotFoundError as exc:
            raise HTTPException(404, "This folder no longer exists") from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/jobs", status_code=201)
    def submit(values: JobRequest):
        if not math.isfinite(values.confidence_threshold):
            raise HTTPException(422, "Numeric values must be finite")
        try:
            source = Path(values.input_dir).expanduser()
            output = Path(values.output_xml).expanduser()
            if not source.is_absolute() or not output.is_absolute():
                raise ValueError("Use absolute local paths")
            source = source.resolve()
            output = output.resolve()
            if not source.is_dir():
                raise ValueError("Input directory does not exist")
            if output.suffix.lower() != ".xml" or output.is_dir():
                raise ValueError("Output must be an XML file path")
            if output.is_relative_to(manager.root) or manager.root.is_relative_to(output.parent):
                raise ValueError("Choose an output folder separate from the web state directory")
            data = values.model_dump()
            data.update(input_dir=str(source), output_xml=str(output))
            return manager.submit(data)
        except FileExistsError as exc:
            raise HTTPException(409, str(exc)) from exc
        except OverflowError as exc:
            raise HTTPException(429, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/jobs")
    def jobs():
        return manager.listing()

    @app.get("/api/jobs/{identifier}")
    def job(identifier: str):
        try:
            return manager.snapshot(identifier)
        except KeyError:
            raise HTTPException(404, "Job not found")

    @app.post("/api/jobs/{identifier}/cancel")
    def cancel(identifier: str):
        try:
            return manager.cancel(identifier)
        except KeyError:
            raise HTTPException(404, "Job not found")

    @app.get("/api/jobs/{identifier}/artifacts/{name}")
    def artifact(identifier: str, name: str):
        data = job(identifier)
        if name not in ARTIFACTS or name not in data["artifacts"]:
            raise HTTPException(404, "Artifact not available")
        directory = manager.root / identifier / "artifacts"
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.resolve().parent != directory.resolve():
            raise HTTPException(404, "Artifact not available")
        return FileResponse(path, filename=Path(data["output_xml"]).name if name == "timeline.xml" else name,
                            media_type="application/octet-stream")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/static/{name}")
    def static(name: str):
        if name not in {"app.js", "style.css"}:
            raise HTTPException(404)
        return FileResponse(STATIC / name)

    return app
