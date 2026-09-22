from __future__ import annotations

import asyncio
import secrets
import time
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from .config import Settings
from .runtime import ALPRRuntime

settings = Settings.from_env()
runtime = ALPRRuntime(settings)
security = HTTPBasic(auto_error=False)


def require_access(
    credentials: Annotated[HTTPBasicCredentials | None, Depends(security)],
) -> None:
    if not settings.access_user and not settings.access_password:
        return
    valid = credentials is not None
    if credentials is not None:
        valid = secrets.compare_digest(credentials.username, settings.access_user)
        valid = valid and secrets.compare_digest(credentials.password, settings.access_password)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
            headers={"WWW-Authenticate": 'Basic realm="Sauron ALPR"'},
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    await asyncio.to_thread(runtime.start)
    yield
    await asyncio.to_thread(runtime.stop)


app = FastAPI(title="Sauron FastALPR", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
def healthz():
    return runtime.health()


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_access)])
def dashboard():
    return DASHBOARD_HTML


@app.get("/api/cameras", dependencies=[Depends(require_access)])
def cameras():
    return runtime.cameras()


@app.get("/api/events", dependencies=[Depends(require_access)])
def events():
    return runtime.recent_events()


@app.get("/cameras/{camera_id}/snapshot.jpg", dependencies=[Depends(require_access)])
def snapshot(camera_id: str):
    if camera_id not in runtime.states:
        raise HTTPException(404, "camera not found")
    _, jpeg = runtime.latest_jpeg(camera_id)
    if jpeg is None:
        raise HTTPException(503, "camera frame not ready")
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/cameras/{camera_id}/stream.mjpg", dependencies=[Depends(require_access)])
def stream(camera_id: str):
    if camera_id not in runtime.states:
        raise HTTPException(404, "camera not found")

    def frames():
        last_seq = -1
        while not runtime.stopping:
            frame_seq, jpeg = runtime.latest_jpeg(camera_id)
            if jpeg is not None and frame_seq != last_seq:
                last_seq = frame_seq
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
            time.sleep(0.05)

    return StreamingResponse(
        frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store"},
    )


DASHBOARD_HTML = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Sauron ALPR</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; background: #071019; color: #ecf3f8; }
    header { position: sticky; top: 0; z-index: 2; display: flex; align-items: center;
      justify-content: space-between; padding: 18px 24px; background: #071019ee;
      border-bottom: 1px solid #1c3344; backdrop-filter: blur(12px); }
    h1 { margin: 0; letter-spacing: .14em; font-size: 18px; font-weight: 750; }
    h1 span { color: #27e0aa; }
    #summary { color: #8ca2b2; font: 13px ui-monospace, monospace; }
    main { padding: 22px; }
    #grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 16px; }
    .card { overflow: hidden; background: #0c1823; border: 1px solid #1b3344; border-radius: 8px;
      box-shadow: 0 18px 45px #0005; }
    .card img { display: block; width: 100%; aspect-ratio: 16/9; object-fit: cover; background: #020609; }
    .meta { display: flex; justify-content: space-between; align-items: center; padding: 12px 14px; }
    .name { font-weight: 700; }
    .detail { margin-top: 3px; color: #7890a0; font: 11px ui-monospace, monospace; }
    .badge { padding: 5px 8px; border-radius: 99px; background: #173244; color: #a4b6c2;
      font: 700 10px ui-monospace, monospace; text-transform: uppercase; }
    .badge.live { background: #0c4738; color: #61efc1; }
    .badge.offline, .badge.error { background: #4a2024; color: #ff9b9b; }
    section { margin-top: 28px; }
    h2 { font-size: 13px; color: #90a7b6; letter-spacing: .12em; text-transform: uppercase; }
    #events { display: grid; gap: 8px; }
    .event { display: grid; grid-template-columns: 150px 130px 1fr; gap: 12px; padding: 11px 14px;
      background: #0c1823; border-left: 3px solid #27e0aa; font: 12px ui-monospace, monospace; }
    @media (max-width: 560px) { header { align-items: flex-start; gap: 8px; flex-direction: column; }
      main { padding: 12px; } #grid { grid-template-columns: 1fr; } .event { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <header><h1>SAURON <span>ALPR</span></h1><div id="summary">iniciando...</div></header>
  <main><div id="grid"></div><section><h2>Lecturas recientes</h2><div id="events"></div></section></main>
  <script>
    const cards = new Map();
    function card(camera) {
      const root = document.createElement('article'); root.className = 'card';
      const img = document.createElement('img'); img.src = `/cameras/${encodeURIComponent(camera.camera_id)}/stream.mjpg`;
      const meta = document.createElement('div'); meta.className = 'meta';
      const left = document.createElement('div');
      const name = document.createElement('div'); name.className = 'name'; name.textContent = camera.camera_id;
      const detail = document.createElement('div'); detail.className = 'detail';
      const badge = document.createElement('span'); badge.className = 'badge';
      left.append(name, detail); meta.append(left, badge); root.append(img, meta);
      document.querySelector('#grid').append(root);
      const value = { detail, badge }; cards.set(camera.camera_id, value); return value;
    }
    async function refresh() {
      try {
        const cameras = await (await fetch('/api/cameras')).json();
        let live = 0;
        for (const camera of cameras) {
          const view = cards.get(camera.camera_id) || card(camera);
          if (camera.status === 'live') live++;
          view.badge.className = `badge ${camera.status}`; view.badge.textContent = camera.status;
          const count = camera.detections.length;
          view.detail.textContent = `${camera.inference_ms ?? '-'} ms · ${count} placa${count === 1 ? '' : 's'} · frame ${camera.frame_seq}`;
        }
        document.querySelector('#summary').textContent = `${live}/${cameras.length} cámaras · FastALPR ONNX`;
        const events = await (await fetch('/api/events')).json();
        const list = document.querySelector('#events'); list.replaceChildren();
        for (const event of events.slice(0, 20)) {
          const row = document.createElement('div'); row.className = 'event';
          for (const text of [new Date(event.timestamp * 1000).toLocaleString(), event.camera_id, event.metadata.plate_text]) {
            const cell = document.createElement('span'); cell.textContent = text; row.append(cell);
          }
          list.append(row);
        }
        if (!events.length) list.textContent = 'Sin matrículas legibles todavía.';
      } catch (error) { document.querySelector('#summary').textContent = `sin conexión: ${error}`; }
    }
    refresh(); setInterval(refresh, 2000);
  </script>
</body>
</html>"""
