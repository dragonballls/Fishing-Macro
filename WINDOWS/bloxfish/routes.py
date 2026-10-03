"""Decide which automatic NPC actions a session actually needs.

These checks have no input, capture, or persistence side effects. A disabled
route must not become an NPC visit merely because a bait counter reaches zero.
"""
from __future__ import annotations

from .config import Config


def buying_enabled(cfg: Config, bait_count: int | None, failures: int = 0) -> bool:
    return (cfg.shop.npc.strip().lower() not in ("none", "off", "")
            and bait_count is not None
            and cfg.shop.bait_per_purchase > 0
            and failures < max(0, cfg.shop.max_failures))


def selling_enabled(cfg: Config) -> bool:
    return (cfg.shop.npc.strip().lower().startswith("f")
            and cfg.sell.enabled and cfg.sell.every > 0)


def npc_route_enabled(cfg: Config, bait_count: int | None,
                      failures: int = 0) -> bool:
    return buying_enabled(cfg, bait_count, failures) or selling_enabled(cfg)
