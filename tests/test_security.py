from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_api_docs_are_not_exposed():
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_security_headers_on_pages_and_api():
    for path in ("/", "/staff/login", "/api/staff/me", "/nope"):
        h = client.get(path).headers
        assert h["x-content-type-options"] == "nosniff"
        assert h["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in h["content-security-policy"]
        assert "script-src" not in h["content-security-policy"] or "'unsafe-inline'" not in h["content-security-policy"].split("script-src")[1].split(";")[0]


def test_pages_have_no_inline_scripts():
    import re
    for path in ("/", "/login", "/tests", "/tests/x", "/thank", "/staff/login", "/staff"):
        body = client.get(path).text
        for m in re.finditer(r"<script([^>]*)>", body):
            assert "src=" in m.group(1), f"inline <script> on {path} would be blocked by CSP"
