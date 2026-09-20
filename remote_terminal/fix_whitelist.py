import json
import os
NOUS_HOME = os.environ.get("NOUS_HOME", os.path.dirname(os.path.abspath(__file__)))
cfg_path = os.path.join(NOUS_HOME, "config.local.json")
with open(cfg_path) as f:
    cfg = json.load(f)
cfg["ALLOWED_IPS"] = os.environ.get("NOUS_ALLOWED_IPS", "127.0.0.1")
with open(cfg_path, "w") as f:
    json.dump(cfg, f, indent=2)
print("Whitelist updated")
