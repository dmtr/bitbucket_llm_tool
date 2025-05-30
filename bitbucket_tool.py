#!/usr/bin/env uv run
# /// script
# dependencies = ["llm", "llm-ollama", "llm-anthropic", "atlassian-python-api"]
# ///

import argparse
import logging
import os
from typing import List, Tuple
import llm
from atlassian.bitbucket.cloud import Cloud

logger = logging.getLogger(__name__)

SYNTAX_RULES = """Following are the syntax rules for searching files in Bitbucket:
A query in Bitbucket has to contain at least one search term, which can either be a single word or a phrase surrounded by quotes.
Search operators are words that can be added to searches to help narrow down the results. Operators must be in ALL CAPS. These are the search operators that can be used to search for files:
AND
OR
NOT
-
(  )
Multiple terms can be used, and they form a boolean query that implicitly uses the AND operator. So a query for "bitbucket server" is equivalent to "bitbucket AND server".
Wildcard searches (e.g. qu?ck buil*) and regular expressions in queries are not supported.
Single characters within search terms are ignored as they’re not indexed by Bitbucket for performance reasons (e.g. searching for “foo a bar” is the same as searching for just “foo bar” as the character “a” in the search is ignored).
Case is not preserved, however search operators must be in ALL CAPS.
Queries cannot have more than 9 expressions (e.g. combinations of terms and operators).
To specify a programming language, use the `lang:` operator followed by the language name (e.g. `lang:python`), so if the query is "my_function lang:python", it will search for the term "def my_function" in Python files.
"""

APP_USERNAME = os.environ.get("APP_USERNAME")
APP_PASSWORD = os.environ.get("APP_PASSWORD")


class BitbucketCodeSearch():
    def __init__(self,workspace_name: str, url: str = "https://api.bitbucket.org/", app_username: str = APP_USERNAME, app_password: str = APP_PASSWORD):
        """
        Initialize BitbucketCodeSearch client.

        Args:
            workspace_name: Name of the Bitbucket workspace
            url: Bitbucket API URL
            app_username: username
            app_password: password
        """

        self.workspace_name = workspace_name
        self.client = Cloud(
            url=url,
            username=app_username,
            password=app_password,
            backoff_and_retry=True,
        )
        self.workspace = self.client.workspaces.get(workspace_name)

    def _get_all_search_results(self, search_query: str) -> List[dict]:
        """
        Fetch all search results across multiple pages.

        Args:
            search_query: The search query string

        Returns:
            List of all search result values
        """
        all_results = []
        page = 1

        while True:
            params = {"search_query": search_query}
            if page > 1:
                params["page"] = page

            logger.info("Fetching page %s", page)
            response = self.workspace.get("/search/code", params=params)

            if "values" in response:
                all_results.extend(response["values"])

            if response.get("next") is None:
                break

            page += 1

        return all_results

    def get_file_names_with_matches(self, search_query: str) -> List[str]:
        """
        Get file names that contain matches for the search query.

        Args:
            search_query: The search query string

        Returns:
            List of file names with repository name as prefix
        """
        results = self._get_all_search_results(search_query)
        file_names = []

        for result in results:
            if result.get("type") == "code_search_result":
                file_info = result.get("file", {})
                file_path = file_info.get("path", "")

                if file_path:
                    # Extract repository name from the file links
                    links = file_info.get("links", {})
                    self_link = links.get("self", {}).get("href", "")

                    # Parse repository name from the URL
                    # URL format: https://api.bitbucket.org/2.0/repositories/{workspace}/{repo_name}/src/...
                    repo_name = ""
                    if "/repositories/" in self_link:
                        parts = self_link.split("/repositories/")[1].split("/")
                        if len(parts) >= 2:
                            repo_name = parts[1]

                    if repo_name:
                        file_names.append(f"{repo_name}/{file_path}")
                    else:
                        file_names.append(file_path)

        return file_names

    def get_matches(self, search_query: str) -> List[Tuple[str, str]]:
        """
        Get matches for the search query.

        Args:
            search_query: The search query string

        Returns:
            List of tuples (file_name, formatted_matches)
        """
        results = self._get_all_search_results(search_query)
        formatted_results = []

        for result in results:
            if result.get("type") == "code_search_result":
                file_info = result.get("file", {})
                file_path = file_info.get("path", "")

                # Extract repository name
                links = file_info.get("links", {})
                self_link = links.get("self", {}).get("href", "")
                repo_name = ""
                if "/repositories/" in self_link:
                    parts = self_link.split("/repositories/")[1].split("/")
                    if len(parts) >= 2:
                        repo_name = parts[1]

                file_name = f"{repo_name}/{file_path}" if repo_name else file_path

                # Format content matches
                formatted_match = self._format_content_matches(result.get("content_matches", []))

                if formatted_match:
                    formatted_results.append((file_name, formatted_match))

        return formatted_results

    def _format_content_matches(self, content_matches: List[dict], highlight: bool=False) -> str:
        """
        Format content matches into a readable string.

        Args:
            content_matches: List of content match objects

        Returns:
            Formatted string representation of matches
        """
        formatted_lines = []

        for match in content_matches:
            lines = match.get("lines", [])

            for line_info in lines:
                line_number = line_info.get("line")
                segments = line_info.get("segments", [])

                if segments:  # Only include lines with content
                    line_text = ""
                    for segment in segments:
                        text = segment.get("text", "")
                        is_match = segment.get("match", False)

                        if highlight and is_match:
                            line_text += f"**{text}**"  # Highlight matches
                        else:
                            line_text += text

                    if line_text.strip():  # Only add non-empty lines
                        formatted_lines.append(f"Line {line_number}: {line_text}")

        return "\n".join(formatted_lines)


def main(args):
    bitbucket_tool = BitbucketCodeSearch(workspace_name=args.workspace)
    model = llm.get_model(args.model)
    options = {
        "temperature": args.temperature,
        "top_p": args.top_p,
    }

    chain_response = model.chain(
        args.prompt,
        tools=[bitbucket_tool.get_matches],
        system=f"Use the BitbucketCodeSearch tool to search for code. Follow the instructions: {SYNTAX_RULES}",
        after_call=print,
        options= options,
    )

    for chunk in chain_response:
        print(chunk, end="", flush=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    parser = argparse.ArgumentParser(description="Bitbucket Code Search Tool")
    parser.add_argument("--workspace", type=str, help="Bitbucket workspace name")
    parser.add_argument("--model", type=str, default="llama3.3", help="LLM model to use")
    parser.add_argument("--prompt", type=str, help="Prompt template to use")
    parser.add_argument("--temperature", type=float, default=0.2, help="Temperature for LLM generation")
    parser.add_argument("--top_p", type=float, default=1, help="Top P for LLM generation")

    args = parser.parse_args()
    if not args.prompt:
        raise ValueError("Prompt must be provided")

    main(args)
