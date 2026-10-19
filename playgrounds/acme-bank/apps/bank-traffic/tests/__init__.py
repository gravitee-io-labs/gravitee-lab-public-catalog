"""Tests of bank-traffic. They run against a fake platform in memory (tests/fakes.py): no socket, no gateway."""
import logging

# MCPServer configures the root logger when it is built (the fake platform builds two), and the SDKs log every request
# at INFO: the tests read the generator's log with assertLogs and want nothing else on the screen
logging.getLogger().addHandler(logging.NullHandler())
# The A2A server of the fake platform warns that its event queue is torn down with the test's event loop
logging.getLogger("a2a").setLevel(logging.ERROR)
