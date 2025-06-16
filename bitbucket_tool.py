#!/usr/bin/env uv run
# /// script
# dependencies = ["llm", "llm-ollama", "llm-anthropic", "atlassian-python-api", "diskcache"]
# ///

import cmd
import json
import argparse
import logging
import os
from typing import List, Tuple

import llm
from atlassian.bitbucket.cloud import Cloud
from diskcache import Cache


logger = logging.getLogger(__name__)

SYNTAX_RULES = """Following are the syntax rules for searching files in Bitbucket:
A query in Bitbucket has to contain one search term.
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
Bitbucket can group repositories by projects. To specify a project use  project: operator followed by the project name (e.g. `project:my_project`), so if the query is "my_function project:my_project", it will search for the term "def my_function" in files of the specified project.
"""

APP_USERNAME = os.environ.get("APP_USERNAME", "")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")

MAX_PAGE = 100  # Maximum number of pages to fetch for search results
EXPIRATION_TIME = 3600  # Cache expiration time in seconds


def get_system_prompt() -> str:
    """
    Get the system prompt for the conversation.

    Returns:
        str: The system prompt for the conversation
    """
    return f"Act as an Senior Software engineer. Use the BitbucketCodeSearch tool to search for code. {SYNTAX_RULES} Be sure to use the correct syntax for Bitbucket code search."


class BitbucketCodeSearch:
    def __init__(
        self,
        workspace_name: str,
        url: str = "https://api.bitbucket.org/",
        app_username: str = APP_USERNAME,
        app_password: str = APP_PASSWORD,
    ):
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

    def _get_all_search_results(self, search_query: str, max_page: int = MAX_PAGE) -> List[dict]:
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

            with Cache(directory="cache") as cache:
                # Use cache to avoid hitting API limits
                response = cache.get(f"search_code_page_{page}_{search_query}")
                if response is None:
                    logger.info("Fetching page %s", page)
                    response = self.workspace.get("/search/code", params=params)
                    cache.set(
                        f"search_code_page_{page}_{search_query}",
                        response,
                        expire=EXPIRATION_TIME,
                    )
                else:
                    logger.info("Using cached response for page %s", page)

            if "values" in response:
                all_results.extend(response["values"])

            if response.get("next") is None:
                break

            page += 1
            if page > max_page:
                logger.warning("Reached maximum page limit of %s", max_page)
                break

        return all_results

    def get_file_names_with_matches(self, search_query: str, max_page: int = MAX_PAGE) -> str:
        """
        Get file names that contain matches for the search query.

        Args:
            search_query: The search query string

        Returns:
           String representation of file names with matches, separated by newlines.
        """
        results = self._get_all_search_results(search_query, max_page)
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

        return "\n".join(file_names)

    def get_matches(self, search_query: str, max_page: int = MAX_PAGE, highlight: bool = False) -> List[Tuple[str, str]]:
        """
        Get matches for the search query.

        Args:
            search_query: The search query string

        Returns:
            List of tuples (file_name, formatted_matches)
        """
        results = self._get_all_search_results(search_query, max_page)
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
                formatted_match = self._format_content_matches(result.get("content_matches", []), highlight=highlight)

                if formatted_match:
                    formatted_results.append((file_name, formatted_match))

        return formatted_results

    def get_raw_matches(self, search_query: str, max_page: int = MAX_PAGE) -> str:
        """
        Get matches for the search query.

        Args:
            search_query: The search query string

        Returns:
            string representation of the search results in JSON format.
        Example output:
            [
                {
                  "type": "code_search_result",
                  "content_match_count": 2,
                  "content_matches": [
                    {
                      "lines": [
                        {
                          "line": 2,
                          "segments": []
                        },
                        {
                          "line": 3,
                          "segments": [
                            {
                              "text": "def "
                            },
                            {
                              "text": "foo",
                              "match": true
                            },
                            {
                              "text": "():"
                            }
                          ]
                        },
                        {
                          "line": 4,
                          "segments": [
                            {
                              "text": "    print(\"snek\")"
                            }
                          ]
                        },
                        {
                          "line": 5,
                          "segments": []
                        }
                      ]
                    }
                  ],
                  "path_matches": [
                    {
                      "text": "src/"
                    },
                    {
                      "text": "foo",
                      "match": true
                    },
                    {
                      "text": ".py"
                    }
                  ],
                  "file": {
                    "path": "src/foo.py",
                    "type": "commit_file",
                    "links": {
                      "self": {
                        "href": "https://api.bitbucket.org/2.0/repositories/my-workspace/demo/src/ad6964b5fe2880dbd9ddcad1c89000f1dbcbc24b/src/foo.py"
                      }
                    }
                  }
                }
              ]

        """
        results = self._get_all_search_results(search_query, max_page)
        return json.dumps(results)

    def _format_content_matches(self, content_matches: List[dict], highlight: bool = False) -> str:
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


class ConversationHandler:
    def __init__(self, model, tools=None, system_prompt=None, options=None):
        self.model = model
        self.tools = tools or []
        logger.debug("tools: %s", self.tools)
        self.system_prompt = system_prompt or "You are a helpful assistant."
        self.options = options or {}
        self.conversation = model.conversation()

    def get_response(self, prompt: str) -> str:
        """
        Get response from the model based on the prompt.

        Args:
            prompt: The input prompt for the model
            options: Additional options for the model

        Returns:
            The response from the model
        """
        if self.conversation.responses:
            response = self.conversation.chain(prompt, tools=self.tools)
        else:
            response = self.conversation.chain(prompt, system=self.system_prompt, tools=self.tools, options=self.options)

        return response.text()

    def new_conversation(self) -> "ConversationHandler":
        """
        Start a new conversation with the model.

        Args:
            tools: Optional tools to use in the conversation
            system_prompt: Optional system prompt for the conversation

        Returns:
            A new ConversationHandler instance
        """
        return ConversationHandler(model=self.model, tools=self.tools, system_prompt=self.system_prompt, options=self.options)

    def get_usage_info(self) -> str:
        """
        Get usage information for the conversation.

        Returns:
            A string containing the usage information
        """
        if self.conversation.responses:
            return self.conversation.responses[-1].usage()
        return "No usage information available yet."


class InteractiveLLMShell(cmd.Cmd):
    def __init__(self, conversion_hanlder, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.conversation_handler = conversion_hanlder
        self.prompt = "LLM> "
        self.intro = "Welcome to the LLM interactive shell. Type 'help' for commands."

    def default(self, line: str):
        """
        Default command handler for unrecognized commands.
        """
        if not line:
            print("No command entered.")
            return
        response = self.conversation_handler.get_response(line)
        print(response)

    def do_chat(self, line: str):
        """
        Start new chat.
        """
        if not line:
            print("Prompt cannot be empty.")
            return

        self.conversation_handler = self.conversation_handler.new_conversation()
        response = self.conversation_handler.get_response(line)
        print(response)

    def do_usage(self, line: str):
        """
        Get usage information for the conversation.
        """
        usage_info = self.conversation_handler.get_usage_info()
        print(usage_info)

    def do_exit(self, line):
        """
        Exit the interactive shell.
        """
        print("Exiting the interactive shell.")
        return True


def main(args):
    bitbucket_tool = BitbucketCodeSearch(workspace_name=args.workspace)
    model = llm.get_model(args.model)
    options = {
        "temperature": args.temperature,
        "num_ctx": args.n_ctx,
    }

    if args.debug_json:
        results = bitbucket_tool.get_raw_matches(args.prompt)
        print(results)
        exit(0)

    if args.debug:
        results = bitbucket_tool.get_matches(args.prompt, highlight=True)
        for file_name, matches in results:
            print(f"File: {file_name}")
            print(matches)
            print("-" * 40)  # Separator for readability
        exit(0)

    if args.interactive:
        conversation_handler = ConversationHandler(
            model=model,
            tools=[
                bitbucket_tool.get_raw_matches,
                bitbucket_tool.get_file_names_with_matches,
            ],
            system_prompt=get_system_prompt(),
            options=options,
        )
        shell = InteractiveLLMShell(conversation_handler)
        shell.do_chat(args.prompt)  # Initial prompt
        shell.cmdloop()
        return

    chain_response = model.chain(
        args.prompt,
        tools=[
            bitbucket_tool.get_raw_matches,
            bitbucket_tool.get_file_names_with_matches,
        ],
        system=get_system_prompt(),
        after_call=print,
        options=options,
    )

    for chunk in chain_response:
        print(chunk, end="", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bitbucket Code Search Tool")
    parser.add_argument(
        "--log_level",
        type=str,
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )
    parser.add_argument("--workspace", type=str, help="Bitbucket workspace name")
    parser.add_argument("--model", type=str, default="llama3.3", help="LLM model to use")
    parser.add_argument("--prompt", type=str, help="Prompt template to use")
    parser.add_argument("--temperature", type=float, default=0.2, help="Temperature for LLM generation")
    parser.add_argument("--n_ctx", type=int, default=8192, help="Number of context tokens for LLM")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument(
        "--debug_json",
        action="store_true",
        help="Output raw JSON results for debugging",
    )
    parser.add_argument("--interactive", action="store_true", help="Run in interactive mode")

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    if not args.prompt:
        raise ValueError("Prompt must be provided")

    main(args)
