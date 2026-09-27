import os

# Tests exercise failed connects on purpose; never let them open Fusion.
os.environ["FUSION_MCP_AUTOLAUNCH"] = "0"
