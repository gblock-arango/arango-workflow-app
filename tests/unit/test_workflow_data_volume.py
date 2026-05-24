"""UC workflow-data builtin layout (layout_version 2: no corpora/)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

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
    (datasets / "cyber" / "fraud_cyber_dataset.json").write_text("{}", encoding="utf-8")

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
    assert result["layout_version"] == vol.LAYOUT_VERSION
    assert "financial" in result["domains"]
    assert (wf_root / "builtin" / "financial" / "sample.md").is_file()
    assert not (wf_root / "builtin" / "corpora").exists()
    manifest = wf_root / vol.SEED_MANIFEST_REL
    assert manifest.is_file()
    assert (wf_root / "builtin" / "ontologies" / "cyber" / "big.jsonld").is_file()
    assert (wf_root / "builtin" / "instance_data" / "cyber" / "fraud_cyber_dataset.json").is_file()
    assert "cyber" in result.get("instance_data_domains", [])
    assert "cyber" not in result["domains"]


def test_browse_instance_data_under_instance_data_prefix():
    assert vol.is_volume_file_browsable(
        "fraud_cyber_dataset.json",
        rel_path="builtin/instance_data/cyber/fraud_cyber_dataset.json",
        file_kind="instance",
    )
    assert not vol.is_volume_file_browsable(
        "fraud_cyber_dataset.json",
        rel_path="builtin/ontologies/cyber/fraud_cyber_dataset.json",
        file_kind="ontology",
    )


def test_browse_ontology_excludes_manifest_and_plain_json():
    assert not vol.is_volume_file_browsable(
        ".seed_manifest.json",
        rel_path="builtin/.seed_manifest.json",
        file_kind="ontology",
    )
    assert not vol.is_volume_file_browsable(
        "accounts.json",
        rel_path="builtin/cyber/accounts.json",
        file_kind="ontology",
    )
    assert vol.is_volume_file_browsable(
        "fraud_cyber_dataset.jsonld",
        rel_path="builtin/ontologies/cyber/fraud_cyber_dataset.jsonld",
        file_kind="ontology",
    )


def test_use_files_api_on_databricks_deploy_mode(monkeypatch):
    monkeypatch.setenv("TEST_DEPLOYMENT_MODE", "self_managed_platform")
    monkeypatch.setattr(vol, "local_mount_available", lambda: True)
    assert vol.use_files_api_for_io() is True


def test_use_local_mount_when_explicit(monkeypatch):
    monkeypatch.setenv("UC_WORKFLOW_DATA_IO_MODE", "local_mount")
    monkeypatch.setenv("TEST_DEPLOYMENT_MODE", "self_managed_platform")
    monkeypatch.setattr(vol, "local_mount_available", lambda: True)
    assert vol.use_files_api_for_io() is False


def test_write_bytes_uses_files_api_when_configured(monkeypatch):
    monkeypatch.setenv("ARANGO_REGISTRY_TABLE", "workspace.default.arango_connection_registry")
    monkeypatch.setenv("UC_GRAPH_VOLUME_NAME", "arango_workflow_volume")
    monkeypatch.setattr(vol, "use_files_api_for_io", lambda: True)

    with patch.object(vol, "_write_via_files_api", return_value="uploads/x/a.md") as mock_write:
        out = vol.write_bytes(relative_path="uploads/x/a.md", content=b"# hi")

    assert out == "uploads/x/a.md"
    mock_write.assert_called_once()


def test_list_files_falls_back_to_files_api_when_unmounted(monkeypatch):
    monkeypatch.setenv("ARANGO_REGISTRY_TABLE", "workspace.default.arango_connection_registry")
    monkeypatch.setenv("UC_GRAPH_VOLUME_NAME", "arango_workflow_volume")
    monkeypatch.setattr(vol, "local_mount_available", lambda: False)

    entry = MagicMock()
    entry.is_directory = False
    entry.name = "sample.md"
    entry.path = (
        "/Volumes/workspace/default/arango_workflow_volume/workflow-data/builtin/financial/sample.md"
    )
    entry.file_size = 42

    mock_files = MagicMock()
    mock_files.list_directory_contents.return_value = [entry]
    mock_client = MagicMock()
    mock_client.files = mock_files

    with patch(
        "databricks.sdk.WorkspaceClient",
        return_value=mock_client,
    ):
        files = vol.list_files(prefix="builtin", max_entries=10)

    assert len(files) == 1
    assert files[0]["path"] == "builtin/financial/sample.md"
    assert files[0]["name"] == "sample.md"
