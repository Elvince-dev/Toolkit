from __future__ import annotations

import asyncio
from io import BytesIO

from fastapi import UploadFile

from api import main
from toolkit.adapters.registry import reset, sheet
from toolkit.config import settings
from toolkit.tools.data import _describe_sheet


def test_uploaded_csv_is_available_to_dataset_and_agent_tools(
    tmp_path, monkeypatch
):
    settings.cache_clear()
    monkeypatch.setenv("TOOLKIT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TOOLKIT_CSV_PATH", str(tmp_path / "original-csv"))

    try:
        upload = UploadFile(
            filename="Quarter 1.csv",
            file=BytesIO(b"Month,Sales\nJanuary,120\nFebruary,180\n"),
        )
        result = asyncio.run(main.upload_file(upload))

        assert result["dataset"] == "Quarter 1"
        assert settings().csv_path == tmp_path / "uploads"
        assert sheet().read_tab("Quarter 1").rows == [
            ["January", "120"],
            ["February", "180"],
        ]
        dataset = asyncio.run(main.get_dataset("Quarter 1"))
        assert dataset["name"] == "Quarter 1"
        assert dataset["row_count"] == 2
        assert "Quarter 1" in _describe_sheet({})

        settings().csv_path = tmp_path / "original-csv"
        main.activate_existing_uploads()
        assert "Quarter 1" in sheet().list_tabs()
    finally:
        reset()
        settings.cache_clear()
