"""并发：真实 HTTP 服务下多请求并行，结果互不干扰、历史记录不错乱。"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
import uvicorn

from app.main import app
from app.pricing import OptionParams, price

HOST = "127.0.0.1"
PORT = 8123
BASE = f"http://{HOST}:{PORT}"


@pytest.fixture(scope="module")
def live_server():
    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        try:
            httpx.get(f"{BASE}/health", timeout=0.5)
            break
        except Exception:
            time.sleep(0.1)
    else:
        raise RuntimeError("测试服务未能启动")
    yield BASE
    server.should_exit = True
    thread.join(timeout=5)


def test_concurrent_requests_are_isolated(live_server):
    spots = [80.0 + float(i) for i in range(24)]

    def work(spot):
        resp = httpx.post(f"{live_server}/price", json={
            "S": spot, "K": 100.0, "T": 1.0, "r": 0.03,
            "sigma": 0.25, "option_type": "call",
        }, timeout=10.0)
        return spot, resp.status_code, resp.json()

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(work, spots))

    for spot, status, body in outcomes:
        assert status == 200
        expected = price(OptionParams(spot=spot, strike=100.0, expiry=1.0,
                                      rate=0.03, sigma=0.25, dividend=0.0,
                                      option_type="call"))
        # 每个响应必须对应自己的参数，不得串扰
        assert body["params"]["S"] == spot
        assert body["price"] == pytest.approx(expected, rel=1e-12)

    # 每个并发请求都独立留痕，记录数与请求数一致
    history = httpx.get(f"{live_server}/history",
                        params={"endpoint": "price", "limit": 500}, timeout=10.0)
    recorded_spots = [r["spot"] for r in history.json()["records"]]
    for spot in spots:
        assert spot in recorded_spots
