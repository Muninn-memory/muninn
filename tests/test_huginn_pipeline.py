from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from huginn_pipeline import run_huginn_query


class HuginnPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_after_search_runs_after_arun(self) -> None:
        events: list[str] = []

        async def fake_arun(*_args, **_kwargs) -> str:
            events.append("arun")
            return "ok"

        async def after_search() -> None:
            events.append("after")

        with patch("huginn_pipeline.arun", side_effect=fake_arun), patch(
            "huginn_pipeline.muninn_save_to_memory", new=AsyncMock()
        ):
            answer = await run_huginn_query(
                "test query",
                save_to_memory=False,
                after_search=after_search,
            )

        self.assertEqual(answer, "ok")
        self.assertEqual(events, ["arun", "after"])


if __name__ == "__main__":
    unittest.main()
