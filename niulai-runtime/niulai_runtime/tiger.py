"""Compatibility entry point; credential ownership lives in shared.tiger."""
from shared.tiger.bridge import main, run_bridge, TigerBridgeError

if __name__ == "__main__":
    raise SystemExit(main())
