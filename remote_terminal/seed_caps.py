import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nous_core.capability import seed_default_capabilities, list_capabilities
n = seed_default_capabilities()
print(f"Seeded: {n}")
caps = list_capabilities()
print(f"Total: {len(caps)}")
for c in caps[:5]:
    print(f"  {c['name']} [{c['category']}] risk={c['risk']}")
