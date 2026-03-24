import os
import sys
import json
import argparse
import re
import shutil
from dotenv import load_dotenv

load_dotenv()
import requests

DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"
CLEAR_TO_END = "\033[J"
MOVE_TO_LINE_START = "\r"

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def write(text, bold=False, dim=False):
    if dim:
        sys.stdout.write(DIM)
    if bold:
        sys.stdout.write(BOLD)
    sys.stdout.write(text)
    sys.stdout.write(RESET)
    sys.stdout.flush()


def styled(text, bold=False, dim=False):
    prefix = ""
    if dim:
        prefix += DIM
    if bold:
        prefix += BOLD
    return f"{prefix}{text}{RESET}"


def visible_len(text):
    return len(ANSI_RE.sub("", text))


def wrapped_line_count(text, width):
    if not text:
        return 1

    total = 0
    for line in text.splitlines() or [""]:
        line_width = max(visible_len(line), 1)
        total += max((line_width + width - 1) // width, 1)

    if text.endswith("\n"):
        total += 1
    return total


class LiveRenderer:
    def __init__(self, show_reasoning):
        self.show_reasoning = show_reasoning
        self.rendered_lines = 0
        self.enabled = sys.stdout.isatty()

    def render(self, reasoning_text, content_text):
        if not self.enabled:
            return

        if self.rendered_lines:
            sys.stdout.write(f"\033[{self.rendered_lines}F")
            sys.stdout.write(MOVE_TO_LINE_START)

        sys.stdout.write(CLEAR_TO_END)
        block = self._build_block(reasoning_text, content_text)
        sys.stdout.write(block)
        sys.stdout.flush()
        self.rendered_lines = wrapped_line_count(
            block, max(shutil.get_terminal_size(fallback=(80, 24)).columns, 20)
        )

    def _build_block(self, reasoning_text, content_text):
        parts = []
        if self.show_reasoning:
            parts.append(styled("REASONING:", dim=True))
            parts.append(styled(reasoning_text or "...", dim=True))
            parts.append("")

        parts.append(styled("FINAL ANSWER:", bold=True))
        parts.append(styled(content_text or "...", bold=True))
        return "\n".join(parts)


parser = argparse.ArgumentParser()
parser.add_argument("prompt", nargs="?", default="Hello")
parser.add_argument("--no-stream", action="store_true")
parser.add_argument("--show-reasoning", action="store_true", default=True)
parser.add_argument("--no-reasoning", action="store_true")
args = parser.parse_args()

if args.no_reasoning:
    args.show_reasoning = False

invoke_url = "https://integrate.api.nvidia.com/v1/chat/completions"
stream = not args.no_stream


headers = {
    "Authorization": f"Bearer {os.environ.get('NVIDIA_API_KEY', '')}",
    "Accept": "text/event-stream" if stream else "application/json",
}

payload = {
    "model": "moonshotai/kimi-k2.5",
    "messages": [{"role": "user", "content": args.prompt}],
    "max_tokens": 16384,
    "temperature": 0.61,
    "top_p": 1.00,
    "stream": stream,
    "chat_template_kwargs": {"thinking": True},
}


def parse_chunk(line):
    if not line.startswith("data: "):
        return None
    data = line[6:]
    if data.strip() == "[DONE]":
        return None
    return json.loads(data)


response = requests.post(invoke_url, headers=headers, json=payload, stream=stream)

if stream:
    reasoning = []
    content = []
    renderer = LiveRenderer(show_reasoning=args.show_reasoning)
    for line in response.iter_lines():
        if line:
            decoded = line.decode("utf-8")
            chunk = parse_chunk(decoded)
            if chunk and chunk.get("choices"):
                delta = chunk["choices"][0].get("delta", {})
                if delta.get("reasoning"):
                    reasoning.append(delta["reasoning"])
                if delta.get("content"):
                    content.append(delta["content"])
                renderer.render("".join(reasoning), "".join(content))
            elif "usage" in decoded:
                pass
            elif decoded != "data: [DONE]":
                print(decoded)

    if renderer.enabled:
        print()
    else:
        if args.show_reasoning and reasoning:
            print(styled("REASONING:", dim=True))
            print(styled("".join(reasoning), dim=True))
            print()
        print(styled("FINAL ANSWER:", bold=True))
        print(styled("".join(content), bold=True))
else:
    resp_json = response.json()
    if args.show_reasoning and resp_json.get("choices"):
        choice = resp_json["choices"][0]
        reasoning = choice.get("message", {}).get("reasoning", "")
        content = choice.get("message", {}).get("content", "")
        print(DIM + "REASONING:" + RESET)
        print(DIM + reasoning + RESET)
        print(BOLD + "CONTENT:" + RESET)
        print(BOLD + content + RESET)
    else:
        print(json.dumps(resp_json, indent=2))
