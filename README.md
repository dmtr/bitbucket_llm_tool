# Bitbucket Code Search Tool

This tool allows you to search for code in your Bitbucket workspace using a natural language prompt. It utilizes the Bitbucket API and a large language model (LLM) to provide accurate results.

## Prerequisites

* Python 3.x installed on your system
* A Bitbucket workspace with API access enabled
* Environment variables set for `APP_USERNAME` and `APP_PASSWORD`

## Usage

1. Clone this repository to your local machine.
2. Set the environment variables for your Bitbucket credentials and workspace name.
3. Run the script using `python bitbucket_tool.py --prompt "Your search prompt" --workspace "Your workspace name"`.

## Command Line Arguments

* `--prompt`: The natural language prompt to use for searching code (required).
* `--workspace`: The name of your Bitbucket workspace.
* `--model`: The LLM model to use for generating results (default: "llama3.3").
* `--temperature`: The temperature for LLM generation (default: 0.2).

## Example

```bash
APP_USERNAME=myapp APP_PASSWORD=mypass uv run bitbucket_tool.py --model=devstral --prompt 'Find all files containing ABCD in MYPROJ project. Fetch 10 pages max.' --workspace=myworkspace --temperature=0.2
```
