"""Tests of Ace: `python -m unittest discover -s tests -t . -v`, in the app's image or in a venv with requirements.txt."""
import logging

# With a handler on the root logger, MCPServer() does not install its own, which would print every request of every test
logging.getLogger().addHandler(logging.NullHandler())
