"""camera: Klipper printers' webcams (MJPEG over HTTP from Moonraker's webcam list)."""
import threading
import time

import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.responses import StreamingResponse
from starlette.routing import Route

from filament_kit.bridge import camera, registry

from fakes.fake_moonraker import free_port


def jpeg(n: int) -> bytes:
    return b"\xff\xd8" + bytes([n]) * 50 + b"\xff\xd9"


def wait_for(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def stream_server():
    """A multipart MJPEG stream: three good frames, one broken one, then idles."""
    async def gen():
        for i in (1, 2):
            yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: 54\r\n\r\n" + jpeg(i) + b"\r\n"
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + b"not a jpeg" + b"\r\n"
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg(3) + b"\r\n"
        import asyncio
        await asyncio.sleep(30)

    async def stream(request):
        return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(Starlette(routes=[Route("/webcam/", stream)]), host="127.0.0.1", port=port,
                                           log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    assert wait_for(lambda: server.started)
    yield f"http://127.0.0.1:{port}/webcam/?action=stream"
    server.should_exit = True
    t.join(5)


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))


def test_http_mjpeg_latest_frame(stream_server):
    p = registry.Printer("k1", family="klipper", host="127.0.0.1", configured=True)
    src = camera.HttpMjpegSource(p, None, stream_server)
    src.start()
    try:
        assert wait_for(lambda: src.frame()[1] == jpeg(3))
        seq, _ = src.frame()
        assert seq == 3                        # the broken frame was dropped
    finally:
        src.stop()
    assert not src.alive()


def test_klipper_check_needs_host_not_code(tmp_path):
    p = registry.add_klipper("SV08 MAX", "printer.home.arpa")
    hub = camera.Hub(runtime_dir=tmp_path, klipper_url=lambda pid: "http://printer.home.arpa/webcam/?action=stream")
    got, kind = hub.check(p.serial)
    assert (got.serial, kind) == (p.serial, "mjpeg")
    with pytest.raises(camera.NoCamera):
        hub.check(p.serial, "hls")


def test_klipper_without_webcam_has_no_camera(tmp_path):
    p = registry.add_klipper("SV08 MAX", "printer.home.arpa")
    hub = camera.Hub(runtime_dir=tmp_path, klipper_url=lambda pid: None)
    with pytest.raises(camera.NoCamera):
        hub.check(p.serial)
    with pytest.raises(camera.NoCamera):
        camera.Hub(runtime_dir=tmp_path).check(p.serial)      # no Klipper family at all


def test_hub_starts_http_source(tmp_path, stream_server):
    p = registry.add_klipper("SV08 MAX", "127.0.0.1")
    hub = camera.Hub(runtime_dir=tmp_path, klipper_url=lambda pid: stream_server, idle_stop=0.1)
    src = hub.acquire(p.serial, "mjpeg")
    try:
        assert isinstance(src, camera.HttpMjpegSource)
        assert wait_for(lambda: src.frame()[1] is not None)
    finally:
        hub.release(p.serial)
        hub.shutdown()
