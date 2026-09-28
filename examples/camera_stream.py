"""Live camera view served by the running voice service, stdlib only.

stream.py needs the service stopped because vilib and the service both want
the camera. This shares the service's own Picamera2 instead, so you can watch
while he talks, finds things or roams.

    GET /              a page with the stream on it
    GET /mjpg          MJPEG stream (browser, VLC, ffplay)
    GET /snapshot.jpg  one frame

No auth and no TLS: it binds to 127.0.0.1 by default, and the way in from
outside is ``tailscale serve`` (docs/camera.md), which adds both and only
answers devices on your tailnet. Frames are grabbed only while someone is
watching, and one grab is shared by every viewer.
"""
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAGE = b"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Petronilo</title><style>body{margin:0;background:#111;display:flex;
justify-content:center;align-items:center;min-height:100vh}img{max-width:100%}</style>
</head><body><img src="/mjpg" alt="camera"></body></html>"""
BOUNDARY = "frame"


class FrameSource:
    """Wraps ``grab() -> JPEG bytes or None`` so that viewers polling at the
    same time share one grab per 1/fps seconds instead of each taking their own."""

    def __init__(self, grab, fps=5):
        self.grab = grab
        self.interval = 1.0 / fps
        self._lock = threading.Lock()
        self._frame = None
        self._at = 0.0

    def latest(self):
        with self._lock:
            if self._frame is None or time.monotonic() - self._at >= self.interval:
                try:
                    self._frame = self.grab()
                except Exception as e:
                    print(f"(cámara en vivo: {e})")
                    self._frame = None
                self._at = time.monotonic()
            return self._frame


class CameraServer:
    def __init__(self, grab, host="127.0.0.1", port=9000, fps=5):
        self.source = FrameSource(grab, fps)
        self.address = (host, port)
        self._httpd = None

    def start(self):
        source = self.source

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                path = self.path.split("?", 1)[0]
                if path == "/":
                    self._send(200, "text/html; charset=utf-8", PAGE)
                elif path == "/snapshot.jpg":
                    frame = source.latest()
                    if frame is None:
                        self._send(503, "text/plain", b"camera off\n")
                    else:
                        self._send(200, "image/jpeg", frame)
                elif path == "/mjpg":
                    self._stream()
                else:
                    self._send(404, "text/plain", b"not found\n")

            def _send(self, code, content_type, body):
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _stream(self):
                self.send_response(200)
                self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    while True:
                        frame = source.latest()
                        if frame is not None:
                            self.wfile.write(
                                f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\n"
                                f"Content-Length: {len(frame)}\r\n\r\n".encode() + frame + b"\r\n")
                        time.sleep(source.interval)
                except (BrokenPipeError, ConnectionResetError):
                    pass   # the viewer closed the tab

            def log_message(self, fmt, *args):
                pass   # one line per frame request would flood the journal

        self._httpd = ThreadingHTTPServer(self.address, Handler)
        self._httpd.daemon_threads = True
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        print(f"(cámara en vivo: http://{self.address[0]}:{self._httpd.server_port}/)")

    @property
    def port(self):
        return self._httpd.server_port if self._httpd else self.address[1]

    def stop(self):
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
