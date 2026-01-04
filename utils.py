import json
import time
import os
import random
import math
import asyncio
import discord
from datetime import datetime
from discord.ext import commands
# Import Supabase
try:
    from supabase import create_client, Client
except ImportError:
    print("❌ CRITICAL: 'supabase' library not found. Run 'pip install supabase'")
    Client = None

# ==========================================================
# 🧰 HELPER: ENVIRONMENT VARIABLES
# ==========================================================
def _env(key, default): 
    return os.getenv(key, str(default))

def _env_int(key, default): 
    try: return int(os.getenv(key, default))
    except: return default

def _env_str(key, default):
    return os.getenv(key, default)

# ==========================================================
# 🧰 CONFIGURATION & CONSTANTS
# ==========================================================
GAME_VERSION_DISPLAY = "4.2.0+TYCOON" 
THIRST_LIMIT = 86400

# SUPABASE CREDENTIALS
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# --- GAME CONSTANTS ---
POT_UPGRADE_LIMITS = {"clay pot": 3, "plastic pot": 5, "smart pot": 10}

STREAK_BONUSES = {
    7:  {"mult": 1.1, "name": "Regular"},
    14: {"mult": 1.25, "name": "Dedicated"},
    30: {"mult": 1.5, "name": "Addict"},
    60: {"mult": 2.0, "name": "Legend"},
    100: {"mult": 3.0, "name": "Godlike"}
}

ITEM_DURABILITY_MAX = {
    "led lights": 50, "hydroponic": 100, "lights": 30,
    "bho setup": 40, "rosin press": 60
}

SKILLS_CONFIG = {
    "botanist":  {"name": "Master Botanist", "max": 5, "effect": lambda lvl: 1.0 + (lvl * 0.05)},
    "chemist":   {"name": "Mad Chemist", "max": 3, "effect": lambda lvl: 1.0 + (lvl * 0.10)},
    "dealmaker": {"name": "Dealmaker", "max": 5, "effect": lambda lvl: 1.0 - (lvl * 0.02)}
}

WEATHER_TYPES = {
    "Sunny ☀️": {"growth": 1.15, "thirst": 1.2, "price": 1.10},
    "Rainy 🌧️": {"growth": 1.00, "thirst": 0.50, "price": 0.90},
    "Heatwave 🔥": {"growth": 1.30, "thirst": 2.50, "price": 1.20},
    "Cloudy ☁️": {"growth": 1.05, "thirst": 1.00, "price": 1.00},
    "Misty 🌫️": {"growth": 0.90, "thirst": 0.80, "price": 1.05},
    "Windy 💨": {"growth": 0.95, "thirst": 1.50, "price": 0.95},
    "420 Day 🍁": {"growth": 2.00, "thirst": 0.50, "price": 2.00},
    "Harvest Moon 🌕": {"growth": 1.50, "thirst": 0.70, "price": 1.50},
}

GROWTH_CYCLES = {
    "schwag": {"time": 300, "base_value": 15, "yield": (5, 10), "level_req": 1, "genetics": ["Indica"], "display_name": "Schwag"},
    "mexican brick": {"time": 600, "base_value": 20, "yield": (8, 12), "level_req": 1, "genetics": ["Sativa"], "display_name": "Mexican Brick"},
    "purple haze": {"time": 1800, "base_value": 60, "yield": (10, 20), "level_req": 3, "genetics": ["Sativa"], "display_name": "Purple Haze"},
    "sour diesel": {"time": 3600, "base_value": 125, "yield": (15, 30), "level_req": 5, "genetics": ["Sativa"], "display_name": "Sour Diesel"},
    "granddaddy purp": {"time": 5400, "base_value": 150, "yield": (20, 35), "level_req": 7, "genetics": ["Indica"], "display_name": "Granddaddy Purp"},
    "og kush": {"time": 7200, "base_value": 250, "yield": (20, 40), "level_req": 10, "genetics": ["Indica"], "display_name": "OG Kush"},
    "blue dream": {"time": 14400, "base_value": 500, "yield": (30, 60), "level_req": 15, "genetics": ["Hybrid"], "display_name": "Blue Dream"},
    "girl scout cookies": {"time": 18000, "base_value": 600, "yield": (35, 70), "level_req": 18, "genetics": ["Hybrid"], "display_name": "GSC"},
    "white widow": {"time": 28800, "base_value": 1000, "yield": (50, 100), "level_req": 20, "genetics": ["Indica"], "display_name": "White Widow"},
    "alaskan thunder f*ck": {"time": 30000, "base_value": 1100, "yield": (55, 110), "level_req": 22, "genetics": ["Sativa"], "display_name": "ATF"},
    "gelato": {"time": 21600, "base_value": 750, "yield": (40, 80), "level_req": 25, "genetics": ["Hybrid"], "display_name": "Gelato #33"},
    "zkittlez": {"time": 32400, "base_value": 1200, "yield": (60, 120), "level_req": 30, "genetics": ["Indica"], "display_name": "Zkittlez"},
    "mac 1": {"time": 43200, "base_value": 2000, "yield": (80, 160), "level_req": 40, "genetics": ["Hybrid"], "display_name": "MAC 1"},
    "donny burger": {"time": 50000, "base_value": 2500, "yield": (100, 200), "level_req": 45, "genetics": ["Indica", "GMO"], "display_name": "Donny Burger"},
    "durban poison": {"time": 55000, "base_value": 2800, "yield": (110, 220), "level_req": 50, "genetics": ["Sativa", "Landrace"], "display_name": "Durban Poison"},
}

QUEST_TEMPLATES = [
    {"type": "harvest_any", "min": 5, "max": 15, "reward_xp": 100, "reward_cash": 500, "title": "Green Thumb", "desc": "Harvest {} plants."},
    {"type": "earn_cash", "min": 1000, "max": 5000, "reward_xp": 150, "reward_cash": 1000, "title": "Money Maker", "desc": "Earn ${:,} from sales."},
    {"type": "process_dabs", "min": 10, "max": 50, "reward_xp": 200, "reward_cash": 1500, "title": "Lab Rat", "desc": "Process {}g of concentrates."},
    {"type": "gamble_win", "min": 3, "max": 5, "reward_xp": 300, "reward_cash": 2000, "title": "High Roller", "desc": "Win {} gambles."},
    {"type": "buy_item", "min": 1, "max": 3, "reward_xp": 50, "reward_cash": 300, "title": "Consumer", "desc": "Buy {} items from the shop."},
]

SLOTS_SYMBOLS = ["🍒", "🍋", "🍇", "💎", "7️⃣"]
SLOTS_PAYOUTS = {"🍒": 2.0, "🍋": 3.0, "🍇": 5.0, "💎": 10.0, "7️⃣": 25.0}

GAMBLE_CONFIG = {
    "dice_min": 100, "dice_max": 50000, "slots_min": 50, "slots_max": 10000, "blackjack_min": 200, "blackjack_max": 25000
}

SHOP_ITEMS = {
    "schwag seed": {"type": "seed", "cost": 15, "description": "Grow Schwag. Low yield, low risk.", "level_req": 1},
    "mexican brick seed": {"type": "seed", "cost": 30, "description": "Classic brick weed seeds.", "level_req": 1},
    "purple haze seed": {"type": "seed", "cost": 200, "description": "Legendary sativa strain.", "level_req": 3},
    "sour diesel seed": {"type": "seed", "cost": 500, "description": "Pungent, fast-acting sativa.", "level_req": 5},
    "granddaddy purp seed": {"type": "seed", "cost": 800, "description": "Deep purple indica.", "level_req": 7},
    "og kush seed": {"type": "seed", "cost": 1200, "description": "The backbone of West Coast cannabis.", "level_req": 10},
    "blue dream seed": {"type": "seed", "cost": 2500, "description": "High yielding hybrid.", "level_req": 15},
    "white widow seed": {"type": "seed", "cost": 5000, "description": "Potent crystal-covered buds.", "level_req": 20},
    "clay pot": {"type": "pot_upgrade", "cost": 500, "description": "Increases max pot capacity by 1 (Limit 3).", "level_req": 1},
    "plastic pot": {"type": "pot_upgrade", "cost": 2000, "description": "Increases max pot capacity by 1 (Limit 5).", "level_req": 5},
    "smart pot": {"type": "pot_upgrade", "cost": 10000, "description": "Increases max pot capacity by 1 (Limit 10).", "level_req": 15},
    "nutes": {"type": "consumable", "cost": 100, "description": "Reduces grow time by 50% for one plant.", "stackable": True},
    "premium nutes": {"type": "consumable", "cost": 500, "description": "Instantly finishes one plant.", "stackable": True},
    "lights": {"type": "equipment", "cost": 1500, "description": "+50% Yield. Requires electricity.", "level_req": 3},
    "led lights": {"type": "equipment", "cost": 5000, "description": "+75% Yield. Efficient.", "level_req": 10},
    "hydroponic": {"type": "equipment", "cost": 15000, "description": "Plants never need water. +100% Yield.", "level_req": 20},
    "greenhouse": {"type": "equipment", "cost": 8000, "description": "Protects plants from storms and thirst.", "level_req": 12},
    "harvest bot": {"type": "equipment", "cost": 25000, "description": "Auto-harvests plants (90% efficiency).", "level_req": 25},
    "aqua globe": {"type": "consumable", "cost": 50, "description": "Saves a plant from dying of thirst once.", "stackable": True},
    "bho setup": {"type": "tool", "cost": 3000, "description": "Required to make Wax and Shatter.", "level_req": 5},
    "rosin press": {"type": "tool", "cost": 12000, "description": "Required to make Rosin and Live Resin.", "level_req": 15},
    "burner phone": {"type": "tool", "cost": 750, "description": "Faster heat decay.", "level_req": 2},
    "lockpick": {"type": "consumable", "cost": 150, "description": "Increases steal chance slightly.", "stackable": True},
    "cam": {"type": "defense", "cost": 2000, "description": "Helps identify robbers.", "level_req": 5},
    "dog": {"type": "defense", "cost": 5000, "description": "Protects against robberies (20% chance).", "level_req": 8},
    "fake id": {"type": "consumable", "cost": 5000, "description": "Used for !appeal to reduce jail time.", "stackable": True},
    "bribe pack": {"type": "consumable", "cost": 2500, "description": "Used for !bail.", "stackable": True},
    "ice bath": {"type": "tool", "cost": 1500, "description": "Used to cool off heat instantly.", "level_req": 4},
    "repair kit": {"type": "consumable", "cost": 500, "description": "Repairs broken equipment.", "stackable": True},
    "pager": {"type": "tool", "cost": 2500, "description": "+20% Daily Rewards.", "level_req": 5},
    "lawyer": {"type": "tool", "cost": 50000, "description": "Reduces jail time by 25%.", "level_req": 30},
}

CONCENTRATE_TYPES = {
    "hash": {"level_req": 3, "req_item": None, "yield_ratio": 0.20, "value_mult": 2.0},
    "wax": {"level_req": 8, "req_item": "bho setup", "yield_ratio": 0.15, "value_mult": 3.5},
    "shatter": {"level_req": 15, "req_item": "bho setup", "yield_ratio": 0.12, "value_mult": 4.5},
    "rosin": {"level_req": 20, "req_item": "rosin press", "yield_ratio": 0.18, "value_mult": 5.0},
    "live resin": {"level_req": 30, "req_item": "rosin press", "yield_ratio": 0.10, "value_mult": 7.0},
    "diamonds": {"level_req": 50, "req_item": "rosin press", "yield_ratio": 0.05, "value_mult": 12.0}
}

ACHIEVEMENTS = {
    "first_grow":   {"name": "🌱 First Harvest", "desc": "Harvest your first plant", "reward": 500},
    "green_thumb":  {"name": "🌿 Green Thumb",   "desc": "Harvest 100 plants",     "reward": 5000},
    "weed_baron":   {"name": "💰 Weed Baron",    "desc": "Earn $1,000,000 total",  "reward": 50000},
    "dab_king":     {"name": "🍯 Dab King",      "desc": "Process 100g concentrates", "reward": 10000},
    "iron_lungs":   {"name": "😮‍💨 Iron Lungs",   "desc": "Reach High Tolerance (Level 50)", "reward": 25000},
    "robbery_king": {"name": "🔫 Stickup Kid",   "desc": "Successfully rob 50 times", "reward": 15000},
    "prestige_1":   {"name": "👑 Ascended",      "desc": "Prestige for the first time", "reward": 100000},
    "loyalist":     {"name": "📅 Loyalist",      "desc": "Reach a 30-day streak",  "reward": 50000},
}

SPECIAL_EVENTS = {
    "HEAT_WAVE": {"name": "Heat Wave", "desc": "🔥 **Heat Wave!** Plants are drying out 2x faster!", "duration": 3600, "effect": "water_drain", "multiplier": 1.0},
    "MARKET_BOOM": {"name": "Market Boom", "desc": "📈 **Market Boom!** Prices are sky high!", "duration": 7200, "effect": "price_up", "multiplier": 1.5},
    "MARKET_CRASH": {"name": "Market Crash", "desc": "📉 **Market Crash!** The economy is in shambles.", "duration": 3600, "effect": "price_down", "multiplier": 0.6},
    "POLICE_RAID": {"name": "Increased Patrols", "desc": "🚓 **Police Raid!** Heat generation is doubled!", "duration": 3600, "effect": "heat_up", "multiplier": 0.8},
    "RAVE": {"name": "Underground Rave", "desc": "🎉 **Rave!** Demand is high. Sales are faster.", "duration": 10800, "effect": "demand_up", "multiplier": 1.25}
}
    
SESH_MESSAGES = ["Pass the boof.", "Sesh time.", "Who's holding?", "Cloud 9.", "Stay lifted."]
SESH_COLORS = {"SESH": 0x2ecc71, "MOVIE": 0x3498db, "KARAOKE": 0x9b59b6, "DEFAULT": 0xe74c3c}
SESSION_MEDIA = {"SESH": ["https://media.tenor.com/26AHD1wUpdF7i96da/giphy.gif"], "MOVIE": [], "KARAOKE": []}
JAIL_ACTION_BLOCK = {"plant", "harvest", "process", "sell", "buy", "shop", "heist", "raid", "crew", "district", "gamble", "slots", "dice", "steal", "trade", "launder", "lab", "sellconc", "auction", "daily", "water"}

STONER_ROLE_ID = _env_int("STONER_ROLE_ID", 0)
STONER_ROLE_NAME = _env_str("STONER_ROLE_NAME", "Stoner")

# ==========================================================
# 💾 DATABASE MANAGER (SUPABASE HYBRID)
# ==========================================================

def make_default_user():
    return {
        "grams": 500, "dirty_cash": 0, "heat": 0, "jail_until": 0,
        "items": {}, "inventory": [], "item_wear": {}, "flower_stash": {}, "concentrates": {},
        "plants": [], "max_pots": 3, "processing_queue": [], "unlocked_strains": ["schwag", "mexican brick"],
        "xp": 0, "level": 1, "prestige": 0, "achievements": [], "skills": {},
        "crew_id": None, "stats": {}, "created_at": time.time(), "daily_streak": 0,
        "settings": {"notifications": True}, "daily_quests": [],
        "last_daily": 0, "last_login": time.time()
    }

class Database:
    def __init__(self):
        self.supabase: Client = None
        self.local_cache = {}
        self.lock = asyncio.Lock()
        self.dirty = False
        self._init_connection()
        
        # Background sync task
        asyncio.create_task(self._background_sync())

    def _init_connection(self):
        if not SUPABASE_URL or not SUPABASE_KEY:
            print("⚠️ SUPABASE CONFIG MISSING. Data will NOT persist after restart.")
            self.local_cache["__world__"] = self._default_world()
            return
        try:
            self.supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            print("✅ Connected to Supabase!")
            self._initial_load()
        except Exception as e:
            print(f"❌ Connection Error: {e}")
            self.local_cache["__world__"] = self._default_world()

    def _default_world(self):
        return {
            "weather": "Sunny ☀️",
            "market_multiplier": 1.0,
            "event": None,
            "crews": {},
            "district": {"owner_crew_id": None, "owner_name": None, "multiplier": 1.10, "expires_at": 0},
            "auctions": {}, "auction_counter": 0
        }

    def _initial_load(self):
        """Loads World + All Users on startup to prevent freezing later."""
        if not self.supabase: return
        try:
            # 1. Load World
            w = self.supabase.table("world").select("data").eq("id", 1).execute()
            if w.data: self.local_cache["__world__"] = w.data[0]["data"]
            else: self.local_cache["__world__"] = self._default_world()
            
            # 2. Load All Users (Batch)
            # Warning: For massive DBs, this should be paginated or lazy-loaded.
            # For typical bot usage (<5k users), RAM loading is fastest.
            u = self.supabase.table("users").select("id, data").execute()
            for row in u.data:
                uid = row['id']
                udata = row['data']
                # Migration: Convert old inventory lists to dicts immediately
                if isinstance(udata.get("inventory"), list): _inv_dict(udata)
                self.local_cache[uid] = udata
                
            print(f"📦 Loaded {len(self.local_cache)-1} users into memory.")
        except Exception as e:
            print(f"⚠️ Load Error: {e}")

    @property
    def world_state(self):
        return self.local_cache.setdefault("__world__", self._default_world())
    
    @property
    def data(self):
        return self.local_cache

    def get_user(self, user_id):
        uid = str(user_id)
        if uid not in self.local_cache:
            # Check Cloud if not in RAM (Lazy Load) - optional double check
            self.local_cache[uid] = make_default_user()
        return self.local_cache[uid]

    async def save(self):
        """Mark as dirty. Background task handles upload."""
        self.dirty = True

    async def _background_sync(self):
        """Uploads changes every 10 seconds to avoid blocking commands."""
        while True:
            await asyncio.sleep(10)
            if self.dirty and self.supabase:
                await self._push_data()
                self.dirty = False

    async def _push_data(self):
        """Heavy lifting: Upload to Supabase."""
        def _sync():
            try:
                # 1. Save World
                self.supabase.table("world").upsert({"id": 1, "data": self.world_state}).execute()
                
                # 2. Save Users
                # In a real production app, we would only save modified users.
                # For this implementation, we save in chunks.
                payload = []
                for k, v in self.local_cache.items():
                    if k == "__world__": continue
                    payload.append({"id": k, "data": v})
                
                # Chunking (Supabase limit is usually row-count based)
                chunk_size = 50
                for i in range(0, len(payload), chunk_size):
                    chunk = payload[i:i+chunk_size]
                    self.supabase.table("users").upsert(chunk).execute()
                    
            except Exception as e:
                print(f"❌ Cloud Sync Failed: {e}")

        # Run in thread so Discord doesn't lag
        await asyncio.to_thread(_sync)

# HELPER FUNCTIONS
def _norm_item_key(k): return str(k or "").lower().strip().replace("_", " ")

def _inv_dict(user):
    current = user.get("items")
    if isinstance(current, dict): return current
    new_inv = {}
    raw = user.get("inventory")
    if isinstance(raw, list):
        for item in raw:
            nk = _norm_item_key(item)
            new_inv[nk] = new_inv.get(nk, 0) + 1
    user["items"] = new_inv
    return new_inv

def inv_get(user, key): return int(_inv_dict(user).get(_norm_item_key(key), 0))
def has_item(user, key): return inv_get(user, key) > 0
def inv_add(user, key, amt=1): 
    inv = _inv_dict(user)
    want = _norm_item_key(key)
    inv[want] = inv.get(want, 0) + amt

def inv_take(user, key, amt=1):
    inv = _inv_dict(user)
    want = _norm_item_key(key)
    current = inv.get(want, 0)
    if current < amt: return False
    inv[want] = current - amt
    if inv[want] <= 0: inv.pop(want, None)
    return True

def heat_value(user): return int(user.get("heat", 0) or 0)
def set_heat(user, v): user["heat"] = max(0, min(100, int(v)))
def add_heat(user, delta): set_heat(user, heat_value(user) + int(delta))
def jail_left_seconds(user): return max(0, int(user.get("jail_until", 0) or 0) - int(time.time()))

async def jail_guard(ctx, user, cmd_name="action"):
    left = jail_left_seconds(user)
    if left > 0:
        m, s = divmod(left, 60)
        await ctx.send(f"🚔 **Jailed!** Wait {int(m)}m {int(s)}s.")
        return True
    return False

def get_plant_grow_time(user, world, plant):
    strain_key = _norm_item_key(plant.get("strain", "schwag"))
    info = GROWTH_CYCLES.get(strain_key, {})
    base = float(info.get("time", 300))
    if has_item(user, "led lights"): base *= 0.80
    elif has_item(user, "lights"): base *= 0.90
    if has_item(user, "nutes"): base *= 0.50
    return int(max(60, base))

def _xp_needed_for_level(level): return int(100 * (max(1, int(level)) ** 1.5))

async def add_xp(ctx, user, amount, source="activity"):
    user["xp"] = int(user.get("xp", 0)) + int(amount)
    lvl = int(user.get("level", 1))
    if user["xp"] >= _xp_needed_for_level(lvl):
        user["xp"] -= _xp_needed_for_level(lvl)
        user["level"] = lvl + 1
        if ctx: await ctx.send(f"🎉 **Level Up!** You are now level {user['level']}!")

def add_quest_progress(user, quest_type, amount=1):
    for q in user.get("daily_quests", []):
        if q.get("type") == quest_type and not q.get("completed", False):
            q["progress"] = q.get("progress", 0) + amount
            if q["progress"] >= q.get("target", 1):
                q["progress"] = q.get("target", 1)
                q["completed"] = True

def add__progress(user, qt, amt=1): return add_quest_progress(user, qt, amt)

async def check_achievements(ctx, user):
    # Achievement logic stub
    pass

def _shop_price(item):
    return int(item.get("price", item.get("cost", 0)) or 0)

def discord_relative_time(timestamp):
    return f"<t:{int(timestamp)}:R>"

class SafeView(discord.ui.View):
    async def on_timeout(self): self.stop()
    async def on_error(self, interaction, error, item): print(f"UI Error: {error}")

# Initialize Database
db_manager = Database()