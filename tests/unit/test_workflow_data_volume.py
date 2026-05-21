"""UC workflow-data builtin layout (layout_version 2: no corpora/)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.workflow_platform import workflow_data_volume as vol


def test_builtin_uc_path_uses_domain_folders_not_corpora(monkeypatch):
    monkeypatch.setenv("ARANGO_REGISTRY_TABLE", "workspace.default.arango_connection_registry")
    monkeypatch.setenv("UC_GRAPH_VOLUME_NAME", "arango_workflow_volume")

    uc_path = vol.workflow_data_builtin_uc_path()
    assert uc_path.endswith("/workflow-data/builtin")
    assert "corpora" not in uc_path
    assert vol.workflow_data_builtin_root() == vol.workflow_data_root() / "builtin"


def test_seed_builtin_writes_domain_subdirs(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    datasets = repo / "datasets"
    (datasets / "financial").mkdir(parents=True)
    (datasets / "financial" / "sample.md").write_text("# Sample\n", encoding="utf-8")
    (datasets / "cyber").mkdir()
    (datasets / "cyber" / "big.jsonld").write_text("{}", encoding="utf-8")

    wf_root = tmp_path / "wf"
    wf_root.mkdir()
    monkeypatch.setattr(vol, "workflow_data_root", lambda: wf_root)
    monkeypatch.setattr(vol, "repo_datasets_dir", lambda: datasets)
    monkeypatch.setattr(vol, "ensure_workflow_data_dirs", lambda: wf_root / "builtin" or wf_root)

    def _ensure():
        (wf_root / "builtin").mkdir(parents=True, exist_ok=True)
        return wf_root

    monkeypatch.setattr(vol, "ensure_workflow_data_dirs", _ensure)

    result = vol.seed_builtin_datasets_from_bundle(force=True)
    assert result["ok"] is True
    assert result["layout_version"] == 2
    assert "financial" in result["domains"]
    assert (wf_root / "builtin" / "financial" / "sample.md").is_file()
    assert not (wf_root / "builtin" / "corpora").exists()
    manifest = Path(result["destination"]) / ".seed_manifest.json"
    assert manifest.is_file()
    assert "cyber" not in result["domains"]
