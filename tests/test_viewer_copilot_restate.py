import json
from pathlib import Path
import pytest
import viewer_fixture
from test_api import call, cookie
from gct.api import server

def get(srv, path, **headers):
    status, _, body = call(srv.port, path, **cookie(srv), **headers)
    return status, json.loads(body)

@pytest.fixture
def vws(tmp_path):
    return viewer_fixture.build(tmp_path / "vws")

@pytest.fixture
def srv(vws):
    s = server.serve(vws, port=0)
    yield s
    s.stop()

def test_api_copilot_candidates_endpoint(srv):
    status, body = get(srv, "/api/copilot/candidates")
    assert status == 200
    assert body["status"] == "ok"
    assert "candidates" in body
    assert isinstance(body["candidates"], list)
    assert "count" in body

def test_api_restate_pairs_endpoint(srv):
    status, body = get(srv, "/api/restate/pairs")
    assert status == 200
    assert body["status"] == "ok"
    assert "pairs" in body
    assert isinstance(body["pairs"], list)
    assert "count" in body
