"""FastAPI app: start runs, stream their trace over SSE, serve reports and the static UI.

    uvicorn app.web:app --port 8000

Keys stay in server memory: nothing from Settings is put in a response, and the browser only
talks to /api/*. Uploads are read from the request body into memory (never to disk).
"""

import asyncio
import json
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.agent import MAX_QLOO_CALLS, Agent
from app.cache import Cache
from app.config import REPO, load_settings
from app.ingest import IngestError, parse_csv
from app.llm import LLM
from app.qloo_client import QlooClient
from app.runs import RateLimiter, Run, RunStore

MAX_UPLOAD_BYTES = 200_000
MAX_ROWS = 300
MAX_CONCURRENT_RUNS = 3
REPLAY_STEP_S = 0.05  # a replay streams its saved trace quickly; it is labelled as a replay
HEARTBEAT_S = 15

DEMOS = {
    "nyc": {"file": REPO / "data" / "sample_transactions.csv", "label": "NYC demo"},
    "blr": {"file": REPO / "data" / "sample_bengaluru.csv", "label": "Bengaluru demo"},
}
SNAPSHOT_DIR = REPO / "data" / "demo_snapshots"

settings = load_settings()
qloo_cache, llm_cache = Cache(), Cache()
runs = RunStore()
limiter = RateLimiter(max_hits=5, window_s=600)
slots = threading.BoundedSemaphore(MAX_CONCURRENT_RUNS)
snapshots: dict[str, dict] = {}  # demo id -> {"report", "events", "ran_at"}


def error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")  # set by Render's proxy
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def execute(run: Run, txns, live: bool) -> None:
    """Runs the agent in a worker thread; every trace entry is pushed to the run as it happens."""
    try:
        agent = Agent(
            settings,
            llm=LLM(settings, cache=llm_cache, read_cache=not live),
            client=QlooClient(settings, max_calls=MAX_QLOO_CALLS, cache=qloo_cache, read_cache=not live),
            on_event=run.push,
        )
        report = agent.run(txns)
        report.update({"source": run.source, "live": live, "replayed_at": None, "run_id": run.id,
                       "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        run.finish(report)
    except Exception as exc:  # report a clear message to the UI instead of a silent hang
        run.fail(f"The run failed: {type(exc).__name__}: {str(exc)[:200]}")
    finally:
        slots.release()


def start(source: str, txns, live: bool) -> Run | JSONResponse:
    if not slots.acquire(blocking=False):
        return error(503, "Pareil is busy with other runs. Try again in a minute.")
    run = runs.create(source, live=live)
    threading.Thread(target=execute, args=(run, txns, live), daemon=True).start()
    return run


def replay(demo: str) -> Run:
    snap = snapshots[demo]
    run = runs.create(snap["report"]["source"], live=False, replayed_at=snap["ran_at"])
    report = {**snap["report"], "replayed_at": snap["ran_at"], "live": False, "run_id": run.id}

    def feed() -> None:
        for event in snap["events"]:
            run.push(event)
            threading.Event().wait(REPLAY_STEP_S)
        run.finish(report)

    threading.Thread(target=feed, daemon=True).start()
    return run


def demo_txns(demo: str):
    return parse_csv(DEMOS[demo]["file"].read_text(encoding="utf-8"))


def prewarm() -> None:
    """Runs both demos once at startup so visitors get an instant (labelled) replay."""
    for demo, spec in DEMOS.items():
        if demo in snapshots:
            continue
        txns = demo_txns(demo)
        slots.acquire()
        run = runs.create(f"{spec['label']} · {len(txns)} transactions", live=True)
        execute(run, txns, live=True)
        if run.report:
            snapshots[demo] = {"report": run.report, "events": run.events, "ran_at": run.report["ran_at"]}


def load_snapshot_files() -> None:
    for demo in DEMOS:
        path = SNAPSHOT_DIR / f"{demo}.json"
        if path.exists():
            snap = json.loads(path.read_text(encoding="utf-8"))
            snapshots[demo] = snap


@asynccontextmanager
async def lifespan(_: FastAPI):
    load_snapshot_files()
    threading.Thread(target=prewarm, daemon=True).start()
    yield


app = FastAPI(title="Pareil", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
        "img-src 'self' data: https://images.qloo.com; connect-src 'self'; frame-ancestors 'none'"
    )
    return response


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/api/demos")
def demos():
    return [{"id": d, "label": spec["label"], "ready": d in snapshots,
             "ran_at": snapshots[d]["ran_at"] if d in snapshots else None} for d, spec in DEMOS.items()]


@app.post("/api/runs")
async def create_run(request: Request):
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()

    if content_type == "application/json":
        try:
            body = await request.json()
        except ValueError:
            return error(400, "Body must be JSON like {\"demo\": \"nyc\"}.")
        demo, live = body.get("demo"), bool(body.get("live"))
        if demo not in DEMOS:
            return error(400, f"Unknown demo. Use one of: {', '.join(DEMOS)}.")
        if not live and demo in snapshots:
            return {"run_id": replay(demo).id, "replay": True}
        wait = limiter.check(client_ip(request))
        if wait:
            return error(429, f"Too many live runs from your network. Try again in {int(wait // 60) + 1} min.")
        txns = demo_txns(demo)
        run = start(f"{DEMOS[demo]['label']} · {len(txns)} transactions", txns, live=True)

    elif content_type in ("text/csv", "text/plain", "application/vnd.ms-excel"):
        data = bytearray()
        async for chunk in request.stream():
            data += chunk
            if len(data) > MAX_UPLOAD_BYTES:
                return error(413, f"File too large: the limit is {MAX_UPLOAD_BYTES // 1000} KB.")
        try:
            text = bytes(data).decode("utf-8-sig")
        except UnicodeDecodeError:
            return error(400, "The file must be UTF-8 text (a CSV saved from Excel or Google Sheets works).")
        try:
            txns = parse_csv(text, max_rows=MAX_ROWS)
        except IngestError as exc:
            return error(400, str(exc))
        wait = limiter.check(client_ip(request))
        if wait:
            return error(429, f"Too many live runs from your network. Try again in {int(wait // 60) + 1} min.")
        run = start(f"Your upload · {len(txns)} transactions", txns, live=True)

    else:
        return error(415, "Send JSON ({\"demo\": \"nyc\"}) or a CSV file with Content-Type text/csv.")

    if isinstance(run, JSONResponse):
        return run
    return {"run_id": run.id, "replay": False}


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str):
    run = runs.get(run_id)
    if not run:
        return error(404, "Unknown or expired run.")

    async def stream():
        sent, idle = 0, 0.0
        meta = {"source": run.source, "live": run.live, "replayed_at": run.replayed_at}
        yield f"event: start\ndata: {json.dumps(meta)}\n\n"
        while True:
            events, done = run.since(sent)
            for event in events:
                yield f"event: step\ndata: {json.dumps(event)}\n\n"
            sent += len(events)
            if done and not run.since(sent)[0]:
                payload = {"error": run.error} if run.error else {"run_id": run.id}
                yield f"event: {'error' if run.error else 'done'}\ndata: {json.dumps(payload)}\n\n"
                return
            idle = 0.0 if events else idle + 0.2
            if idle >= HEARTBEAT_S:
                idle = 0.0
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.2)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/runs/{run_id}/report")
def run_report(run_id: str):
    run = runs.get(run_id)
    if not run:
        return error(404, "Unknown or expired run.")
    if run.error:
        return error(502, run.error)
    if not run.done:
        return JSONResponse({"status": "running"}, status_code=202)
    return run.report


app.mount("/", StaticFiles(directory=REPO / "static", html=True), name="static")
