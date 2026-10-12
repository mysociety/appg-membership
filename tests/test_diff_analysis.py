from __future__ import annotations

from pathlib import Path

from data_common.dataset.site import create_app
from data_common.dataset.site.freezer import check_site
from data_common.dataset.site.schemas import AnalysisBundleManifest
from pytest import MonkeyPatch

from appg_membership.diff import APPGDiff, DiffResult, LineDiff, MiniAppg


def test_register_report_bundle_links_and_tables(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """
    Register reports must remain navigable Flask pages with escaped table cells.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\n[tool.dataset.site]\nbase_url = "/reports"\n'
    )
    (tmp_path / "site").mkdir()
    (tmp_path / "site/diffs.css").write_text("table { width: 100%; }")
    report = DiffResult(
        current_index="250102",
        previous_index="241120",
        added_appgs=[],
        removed_appgs=[],
        updated_appgs=[MiniAppg(slug="example", title="Example")],
        differences=[
            APPGDiff(
                slug="example",
                name="Example",
                differences=[LineDiff(key="title", old_value="A|B", new_value="C")],
            )
        ],
    )
    report.generate_analysis_pages()
    bundle = tmp_path / "_render/site/analysis/register-changes-250102"
    manifest = AnalysisBundleManifest.model_validate_json(
        (bundle / "page.json").read_text()
    )
    assert manifest.slug == "register-changes-250102"
    body = (bundle / "body.html").read_text()
    assert '<h2 id="table-of-contents">' in body
    assert '<h3 id="changes-to-example">' in body
    assert "<td>A|B</td>" in body
    assert (bundle / "notebook_resources/diffs.css").is_file()
    app = create_app(repo_root=tmp_path)
    response = app.test_client().get("/reports/analysis/register-changes-250102/")
    assert response.status_code == 200
    assert b"APPG Register Changes" in response.data
    assert check_site(app).page_count == 3
    report.generate_analysis_pages()
    assert (bundle / "body.html").read_text() == body
