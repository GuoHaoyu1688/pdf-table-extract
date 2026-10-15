import asyncio
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from pdf_table_extract.cli import main
from pdf_table_extract.mcp_server import build_server
from pdf_table_extract.web.server import make_server

ROOT = Path(__file__).resolve().parents[1]
PDF = str(ROOT / "examples/ruled.pdf")


def test_cli_workflow_and_uniform_errors(tmp_path, capsys):
    base = ["--data-dir", str(tmp_path / "data"), "--json"]

    def run(*args, expected=0):
        assert main([*args, *base]) == expected
        return json.loads(capsys.readouterr().out)

    assert run("--version")["data"]["version"] == "0.1.0"
    assert run("inspect", PDF)["data"]["page_count"] == 1
    assert run("extract", PDF, "--out", str(tmp_path / "tables"), "--format", "json", "--progress")[
        "data"
    ]["tables"]
    assert run("render", PDF, "--out", str(tmp_path / "page.png"))["ok"]
    assert run("template", "save", "example", "--area", "50,92,480,220")["ok"]
    assert len(run("template", "list")["data"]) == 1
    assert run("template", "show", "example")["data"]["name"] == "example"
    assert run("template", "apply", "example", PDF, "--out", str(tmp_path / "batch"))["ok"]
    assert run("export", "--out", str(tmp_path / "templates.json"))["ok"]
    assert run("import", str(tmp_path / "templates.json"))["data"]["skipped"] == 1
    assert run("backup")["ok"]
    assert run("template", "delete", "example", "--yes")["ok"]
    assert run("inspect", "missing.pdf", expected=3)["error"]["code"] == "not_found"
    assert run("extract", PDF, "--area", "bad", expected=2)["error"]["code"] == "invalid_input"
    assert main(["extract"]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "invalid_arguments"


def test_config_and_template_file(tmp_path, capsys):
    config = tmp_path / "config.toml"
    config.write_text(f'data_dir="{tmp_path / "configured"}"\ntimezone="UTC"\n')
    template = tmp_path / "template.json"
    template.write_text('{"pages":"1","header_rows":1}')
    assert (
        main(["--config", str(config), "template", "save", "example", "--from-file", str(template)])
        == 0
    )
    assert json.loads(capsys.readouterr().out)["ok"]
    assert (tmp_path / "configured/cache.sqlite").exists()


def test_mcp_tools_via_official_sdk(tmp_path):
    server = build_server()

    async def call(name, args):
        result = await server.call_tool(name, args)
        return (
            result[1]
            if isinstance(result, tuple)
            else result
            if isinstance(result, dict)
            else json.loads(result[0].text)
        )

    async def run():
        assert {t.name for t in await server.list_tools()} == {"inspect_pdf", "extract_tables"}
        assert (await call("inspect_pdf", {"path": PDF}))["data"]["page_count"] == 1
        assert (await call("extract_tables", {"path": PDF, "out": str(tmp_path), "format": "csv"}))[
            "data"
        ]["tables"]
        assert not (await call("inspect_pdf", {"path": "missing.pdf"}))["ok"]
        assert not (await call("extract_tables", {"path": "missing.pdf"}))["ok"]

    asyncio.run(run())


def test_http_review_and_column_correction(tmp_path):
    server = make_server(port=0, pdf=PDF, quiet=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"

    def request(route, payload=None, token=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-PTE-CSRF"] = token
        req = urllib.request.Request(
            url + route, data=json.dumps(payload).encode() if payload else None, headers=headers
        )
        with urllib.request.urlopen(req) as response:
            return json.load(response)

    try:
        token = request("/api/config")["data"]["csrf"]
        with pytest.raises(urllib.error.HTTPError):
            request("/api/extract", {"path": PDF})
        assert request("/api/inspect", {"path": PDF}, token)["data"]["page_count"] == 1
        result = request("/api/extract", {"path": PDF, "columns": [50, 230, 330, 480]}, token)[
            "data"
        ]
        assert result["tables"][0]["rows"][0] == ["Sample A", "10", "1200.50"]
        assert result["tables"][0]["page_regions"][0]["cells"]
        with urllib.request.urlopen(
            url + "/api/render?path=" + urllib.parse.quote(PDF)
        ) as response:
            assert response.read().startswith(b"\x89PNG")
        with urllib.request.urlopen(url + "/") as response:
            assert b"Source geometry" in response.read()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
