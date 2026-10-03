"""Shared terminal setup for Windows and Sober/X11.

No OS backend, dependency installation, config writes, or game input lives here.
The launcher supplies its active profile and engine before collecting answers.
"""
from __future__ import annotations

from .routes import buying_enabled, npc_route_enabled


def ask_input(prompt: str, default: str = "") -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return default


def setup_prompts(cfg, engine, *, ask=ask_input) -> bool:
    """Collect the run settings and show the pre-flight checklist.

    Returns False if the user backed out.
    """
    shop = cfg.shop

    # --- which NPC ------------------------------------------------------
    while True:
        ans = ask("Which NPC will you buy from?  [F]isherman "
                   "(Enter = Fisherman, or N for no buying): ", "f").lower()
        if ans in ("", "f", "fisherman"):
            shop.npc = "fisherman"
            break
        if ans in ("n", "no", "none"):
            shop.npc = "none"
            break
        print("  please answer F or N (N = fish-only, no buying or selling)")

    # --- how much bait per purchase -------------------------------------
    if shop.npc == "fisherman":
        step = max(1, shop.craft_step)
        while True:
            raw = ask(f"How much bait per purchase? (multiple of {step}, "
                       f"Enter = {shop.bait_per_purchase}): ")
            if not raw:
                break
            if raw.isdigit() and int(raw) >= step and int(raw) % step == 0:
                shop.bait_per_purchase = int(raw)
                break
            print(f"  must be a multiple of {step} and at least {step}")
        clicks = (shop.bait_per_purchase // step) - 1
        print(f"  -> {shop.bait_per_purchase} bait per trip "
              f"({clicks} '+' click{'s' if clicks != 1 else ''} in the craft window)")

    # --- fishing rod hotbar slot -----------------------------------------
    while True:
        raw = ask(f"Which hotbar slot is your fishing rod in? 1-9 or 0 "
                   f"(Enter = {cfg.rod_slot}): ")
        if not raw:
            break
        if raw in [str(d) for d in range(10)]:
            cfg.rod_slot = raw
            break
        print("  must be a single digit 1-9 or 0")
    print(f"  -> will press '{cfg.rod_slot}' to stow/draw the rod")

    # --- auto-sell --------------------------------------------------------
    if shop.npc == "fisherman":
        while True:
            raw = ask(f"Sell your fish every how many catches? 0 = never "
                       f"(Enter = {cfg.sell.every}): ")
            if not raw:
                break
            if raw.isdigit():
                cfg.sell.every = int(raw)
                cfg.sell.enabled = cfg.sell.every > 0
                break
            print("  must be a whole number (0 to disable)")
        print(f"  -> {'selling every %d catches' % cfg.sell.every}"
              if cfg.sell.enabled else "  -> auto-sell off")

    # --- current bait ----------------------------------------------------
    raw = ask("How much bait do you have right now? (Enter to skip tracking) ")
    engine.bait_count = int(raw) if raw.isdigit() else None
    if not buying_enabled(cfg, engine.bait_count):
        print("  automatic buying off; no restocking is scheduled")
    else:
        print(f"  tracking {engine.bait_count}; will restock at "
              f"{shop.buy_at}")

    # --- pre-flight checklist -------------------------------------------
    print("\n" + "=" * 62)
    print("BEFORE YOU START — get these exactly right or the clicks miss:")
    uses_npc = npc_route_enabled(cfg, engine.bait_count)
    if uses_npc:
        print("  1. Stand at the NPC, right on the edge of interaction range")
        print("     (the 'Interact' prompt should be showing).")
    else:
        print("  1. Fish-only: choose your fishing position and aim yourself.")
        print("     Stay outside NPC interaction range and close any menus.")
    print("  2. Turn OFF auto-run / running.")
    if uses_npc:
        print("  3. Turn OFF Shift Lock; the macro manages it for NPC trips.")
    else:
        print("  3. Set Shift Lock yourself. No automatic toggles or checks.")
    print("  4. Leave Roblox focused and don't touch the mouse while it runs.")
    print("  5. Don't let your editor/terminal overlap the game window — the")
    print("     bot reads the screen, and a covered panel reads as 'not there'.")
    print(f"  6. EQUIP your fishing rod now (slot {cfg.rod_slot}) and leave it out.")
    print("     The rod-flick catch shortcut uses this slot in every mode.")
    print("=" * 62)
    ans = ask("Ready? [Enter to continue, N to quit] ", "n").lower()
    if ans in ("n", "no", "q", "quit"):
        print("aborted")
        return False
    return True
