from dataclasses import replace

from fastapi.testclient import TestClient

from app.main import create_app


def test_serves_built_frontend_when_configured(settings, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("nope")

    app = create_app(replace(settings, frontend_dist=dist), run_background_jobs=False)
    with TestClient(app) as client:
        assert client.get("/").text == "<html>app</html>"
        assert client.get("/assets/app.js").text == "console.log(1)"
        assert client.get("/privacy").text == "<html>app</html>"  # client-side route
        assert client.get("/%2e%2e/secret.txt").text == "<html>app</html>"  # no path traversal
        assert client.get("/api/nope").status_code == 404
        assert client.get("/healthz").json() == {"ok": True}


def test_api_only_when_no_frontend(client):
    assert client.get("/").status_code == 404
