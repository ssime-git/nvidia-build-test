.PHONY: run

run:
	uvx --with python-dotenv --with requests python api-call.py "$(PROMPT)" --show-reasoning
