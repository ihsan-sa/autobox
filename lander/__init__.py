"""The lander: queues a PR, picks the checks its change reaches, runs them, buys a review where the policy says
so, merges, and hands merged main to the tip run and the deploy.

`types.py` is the contract every unit codes against; `cli.py` is the one entry point and collects each module's
COMMANDS. Run it through `bin/lander`, which prefers the pinned release at ~/.cc/lander/current.
"""
