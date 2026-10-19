"""Synthetic Open-Meteo responses served only on loopback."""
import datetime as dt
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


class WeatherServer:
    def __init__(self):
        self.code, self.requests = 0, []
        source = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                path = urlsplit(self.path).path
                code = source.code
                source.requests.append({"path": self.path, "code": code})
                if path == "/open-meteo/v1/search":
                    data = {"results": [{"name": "Synthetic airport", "latitude": 51.47, "longitude": -0.45}]}
                elif path == "/open-meteo/v1/forecast":
                    now = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
                    stamps = [(now + dt.timedelta(hours=i)).timestamp() for i in range(-6, 73)]
                    data = {"hourly": {"time": stamps, **{key: [value] * len(stamps) for key, value in
                            {"weather_code": code, "precipitation": 0, "precipitation_probability": 0,
                             "wind_gusts_10m": 0, "snowfall": 1 if code == 71 else 0}.items()}}}
                else:
                    self.send_error(404)
                    return
                body = json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_port)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
