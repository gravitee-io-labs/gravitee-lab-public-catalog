import logging

# the app logs one line per step: the tests read them when they care, and keep the output clean when they do not
logging.getLogger("bank-web").addHandler(logging.NullHandler())
logging.getLogger("a2a").setLevel(logging.ERROR)
