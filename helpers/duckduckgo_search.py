# from langchain_community.utilities import DuckDuckGoSearchAPIWrapper

# def search(query: str, results = 5, region = "wt-wt", time="y") -> str:
#     # Create an instance with custom parameters
#     api = DuckDuckGoSearchAPIWrapper(
#         region=region,  # Set the region for search results
#         safesearch="off",  # Set safesearch level (options: strict, moderate, off)
#         time=time,  # Set time range (options: d, w, m, y)
#         max_results=results  # Set maximum number of results to return
#     )
#     # Perform a search
#     result = api.run(query)
#     return result

import asyncio

# duckduckgo_search's __init__ globally switches Windows to the
# SelectorEventLoopPolicy, which cannot spawn subprocesses and breaks
# Playwright (browser tool) with NotImplementedError. Restore the policy
# that was active before the import.
_policy_before_import = asyncio.get_event_loop_policy()
from duckduckgo_search import DDGS
asyncio.set_event_loop_policy(_policy_before_import)

def search(query: str, results = 5, region = "wt-wt", time="y") -> list[str]:

    ddgs = DDGS()
    src = ddgs.text(
        query,
        region=region,  # Specify region 
        safesearch="off",  # SafeSearch setting
        timelimit=time,  # Time limit (y = past year)
        max_results=results  # Number of results to return
    )
    results = []
    for s in src:
        results.append(str(s))
    return results