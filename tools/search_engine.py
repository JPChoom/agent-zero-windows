import asyncio

from helpers import duckduckgo_search
from helpers.errors import handle_error
from helpers.print_style import PrintStyle
from helpers.searxng import search as searxng
from helpers.tool import Response, Tool

SEARCH_ENGINE_RESULTS = 10


class SearchEngine(Tool):
    async def execute(self, query="", **kwargs):
        search_result = await self.searxng_search(query)

        await self.agent.handle_intervention(search_result)

        return Response(message=search_result, break_loop=False)

    async def searxng_search(self, question):
        try:
            results = await searxng(question)
            return self.format_result_searxng(results, "Search Engine")
        except Exception as searxng_error:
            PrintStyle.warning(
                "SearXNG unavailable, falling back to DuckDuckGo: "
                f"{searxng_error}"
            )

            try:
                results = await asyncio.to_thread(
                    duckduckgo_search.search,
                    question,
                    SEARCH_ENGINE_RESULTS,
                )
                return "\n\n".join(results)
            except Exception as ddg_error:
                return (
                    "Search failed.\n"
                    f"SearXNG: {searxng_error}\n"
                    f"DuckDuckGo: {ddg_error}"
                )

    def format_result_searxng(self, result, source):
        if isinstance(result, Exception):
            handle_error(result)
            return f"{source} search failed: {result}"

        outputs = []
        for item in (result or {}).get("results", []):
            outputs.append(
                f"{item['title']}\n{item['url']}\n{item['content']}"
            )

        return "\n\n".join(outputs[:SEARCH_ENGINE_RESULTS]).strip()
