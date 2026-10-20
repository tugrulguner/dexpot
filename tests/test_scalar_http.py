"""Exercise scalar selection and checked failures through the real server."""

import http.client
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_scalar_strategy_is_active_and_preserves_http_recovery(tmp_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    script = tmp_path / "scalar_app.py"
    script.write_text(
        """import os, sys, dexpot, msgspec
from dexpot import Dex
class Item(msgspec.Struct):
    id: int
    name: str
    price: float
app = Dex()
@app.post('/typed', body=Item, response=Item)
def typed(body): return body
@app.get('/bad', response=Item)
def bad(): return Item(True, 'x', 9.99)
@app.get('/nonfinite', response=Item)
def nonfinite(): return Item(7, 'x', float('inf'))
@app.get('/mode')
def mode():
    return {'compiled': bool(getattr(app._endpoints[0].resp_prepare, '__compiled_scalar__', False)),
            'gil_enabled': getattr(sys, '_is_gil_enabled', lambda: True)(),
            'module': dexpot.__file__, 'pid': os.getpid()}
app.serve(port=PORT)
""".replace("PORT", str(port))
    )
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), DEXPOT_WORKERS="1", DEXPOT_POOL="2")
    env.pop("PYTHON_GIL", None)
    process = subprocess.Popen(
        [sys.executable, str(script)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    conn = None
    try:
        deadline = time.monotonic() + 8
        while True:
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
                conn.request("GET", "/mode")
                response = conn.getresponse()
                mode = json.loads(response.read())
                assert response.status == 200
                break
            except OSError:
                if conn is not None:
                    conn.close()
                assert process.poll() is None and time.monotonic() < deadline
                time.sleep(0.02)
        assert str(ROOT / "src") in mode["module"]
        assert mode["compiled"] is (not mode["gil_enabled"])
        expected = {"id": 7, "name": "item-7", "price": 9.99}
        for path, status in (("/typed", 200), ("/bad", 500), ("/nonfinite", 500), ("/typed", 200)):
            conn.request(
                "POST" if path == "/typed" else "GET",
                path,
                body=json.dumps(expected) if path == "/typed" else None,
                headers={"Content-Type": "application/json"},
            )
            response = conn.getresponse()
            body = json.loads(response.read())
            assert response.status == status
            if status == 200:
                assert body == expected
    finally:
        if conn is not None:
            conn.close()
        process.terminate()
        stdout, stderr = process.communicate(timeout=8)
        assert process.returncode == 0, (stdout, stderr)
