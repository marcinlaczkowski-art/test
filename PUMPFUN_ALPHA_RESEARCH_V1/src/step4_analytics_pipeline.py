"""
STEP 4: Comprehensive On-Chain, Behavioral, Graph/Cluster, Insider Supply, Creator, Temporal,
Semantic/Narrative, and Social Analytics Pipeline.

Produces the core analytical datasets (14 CSVs + structured JSON summaries for reports & dashboard):
- ALL_TOKENS.csv
- PUMP_EVENTS.csv
- TOP_100_PUMPS.csv
- TOKEN_METRICS.csv
- CONTROL_GROUP.csv
- WALLET_INTELLIGENCE.csv
- WALLET_CLUSTERS.csv
- SUPPLY_CONCENTRATION.csv
- INSIDER_PROFIT_ANALYSIS.csv
- INSIDER_RISK.csv
- CREATOR_ANALYSIS.csv
- HOURLY_PATTERNS.csv
- NAME_ANALYSIS.csv
- SOCIAL_ANALYSIS.csv
"""
import json
import math
import re
import logging
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from collections import defaultdict, Counter

import numpy as np
import pandas as pd
import networkx as nx
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import svds
from scipy.cluster.vq import kmeans2

from config import (
    BASE_DIR, RAW_DIR, TRADES_CACHE_DIR, CANDLES_CACHE_DIR,
    CREATORS_CACHE_DIR, RPC_CACHE_DIR, HOLDINGS_CACHE_DIR, LOGS_DIR,
    WINDOW_START_MS, WINDOW_END_MS, TECHNICAL_ADDRESSES
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "step4_analytics.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("step4")
WARSAW_TZ = ZoneInfo("Europe/Warsaw")

# ==============================================================================
# 1. NARRATIVE & LEXICAL / SEMANTIC CLASSIFIER
# ==============================================================================
NARRATIVE_RULES = [
    ("AI_Agents_Tech", r"\b(ai|agent|gpt|claude|llm|bot|neural|sentient|autonom|solana\.ai|mcp|truth|terminal|cyber|quantum|compute|code|dev|algo|deepseek|openai|grok)\b"),
    ("Absurd_Toilet_Humor", r"\b(fart|poop|pee|shit|butt|ass|cum|dick|balls|toilet|piss|burp|vomit|goon|brainrot|skibidi|autism|retard|schizo)\b"),
    ("Animals_Pets", r"\b(dog|cat|pepe|frog|shib|inu|goat|pnut|squirrel|bear|bull|ape|monkey|pengu|bird|duck|fish|shark|whale|hamster|moo|hippo|capy|seal|otter|panda|wolf|fox|kitty|pup)\b"),
    ("Politics_Macro", r"\b(trump|biden|elon|musk|maga|doge|gov|president|senate|vote|america|usa|china|russia|war|tariff|fed|powell|tax|sec|gensler)\b"),
    ("Platform_Meta_Pump", r"\b(mayhem|polymarket|pump|pumpswap|boost|privy|sui|raydium|bonding|graduation|koth|trench|trenches|runner|cabal|bundle)\b"),
    ("Internet_Memes_Culture", r"\b(chad|wojak|pepe|kek|giga|sigma|chill|guy|doge|troll|npc|based|cope|seethe|wagmi|ngmi|hodl|fomo|meme|viral|bro|aura|rizz)\b"),
    ("Finance_Trading_Wealth", r"\b(quant|alpha|rich|million|billion|money|cash|gold|dollar|usd|bank|yield|hedge|fund|stock|nasdaq|sp500|short|long|bullish|candle|moon)\b"),
    ("Celebrities_Creators", r"\b(drake|kanye|ye|taylor|mrbeast|logan|jake|speed|kai|cenat|adin|ross|tate|rogan|zuck|bezos|saylor|vitalik|toly|alon)\b"),
    ("Anime_Gaming_Pop", r"\b(anime|waifu|naruto|goku|pikachu|pokemon|mario|sonic|gta|minecraft|roblox|fortnite|elden|cyberpunk|joker|batman|marvel|starwars|chan|kun)\b"),
    ("Controversy_Edgy", r"\b(fuck|kill|hate|scam|rug|jail|prison|cartel|mafia|crime|hack|stolen|ban|cancel|nsfw|cult|devil|hell)\b"),
    ("Sports_Events", r"\b(ufc|nba|nfl|fifa|soccer|football|fight|boxing|paul|tyson|olympic|champ|goal|win|bet)\b"),
    ("Brands_Parody", r"\b(apple|tesla|nvidia|google|meta|amazon|mcdonald|nike|gucci|pepsi|coke|starbucks|wendy|ikea|uber|tiktok|x)\b"),
]

def classify_narrative(name: str, symbol: str, desc: str) -> str:
    txt = f"{name or ''} {symbol or ''} {desc or ''}".lower()
    for cat, pat in NARRATIVE_RULES:
        if re.search(pat, txt):
            return cat
    return "General_Novelty_Other"

def compute_lexical_features(name: str, symbol: str, desc: str) -> dict:
    n_clean = (name or "").strip()
    s_clean = (symbol or "").strip().lstrip("$")
    words = [w for w in re.split(r"\s+", n_clean) if w]
    alpha_s = re.sub(r"[^a-zA-Z]", "", s_clean.lower())
    vowels = sum(1 for ch in alpha_s if ch in "aeiouy")
    v_ratio = vowels / max(1, len(alpha_s))
    # Ideal pronounceability has ~30%-55% vowels and alternating CV transitions
    transitions = sum(1 for i in range(len(alpha_s) - 1) if (alpha_s[i] in "aeiouy") != (alpha_s[i+1] in "aeiouy"))
    cv_alt = transitions / max(1, len(alpha_s) - 1) if len(alpha_s) > 1 else 0.5
    pronounceability = round(min(1.0, 0.5 * (1.0 - abs(v_ratio - 0.42) * 2.0) + 0.5 * cv_alt), 3)

    has_digits_or_special = int(bool(re.search(r"[0-9_!@#$%^&*]", n_clean + s_clean)))
    is_upper_ticker = int(s_clean.isupper() and len(s_clean) >= 2)
    is_acronym = int(len(words) >= 2 and "".join(w[0] for w in words if w).upper() == s_clean.upper())

    txt_low = f"{n_clean} {s_clean} {desc or ''}".lower()
    humor_hits = len(re.findall(r"\b(fart|funny|lol|meme|chill|joke|shit|poop|dog|cat|frog|chad|autism|goof|clown|baby|mini|fat|dumb)\b", txt_low))
    controversy_hits = len(re.findall(r"\b(fuck|shit|war|trump|ban|jail|scam|rug|hate|kill|cult|hell|sex|ass|dick)\b", txt_low))
    emotion_hits = len(re.findall(r"(!|\?|fuck|love|hate|moon|rich|win|doom|panic|save|stop|free|real|official)", txt_low))

    memorability = round(
        0.35 * max(0.0, 1.0 - max(0, len(s_clean) - 4) * 0.15)
        + 0.35 * pronounceability
        + 0.30 * max(0.0, 1.0 - max(0, len(words) - 2) * 0.25),
        3
    )
    meme_shareability = round(
        min(1.0, 0.30 * memorability + 0.25 * min(1.0, humor_hits * 0.5) + 0.20 * min(1.0, emotion_hits * 0.35) + 0.25 * (1.0 if len(words) <= 3 else 0.4)),
        3
    )

    return {
        "name_len": len(n_clean),
        "ticker_len": len(s_clean),
        "word_count": len(words),
        "pronounceability_score": pronounceability,
        "memorability_score": memorability,
        "unusual_spelling_or_digits": has_digits_or_special,
        "is_upper_ticker": is_upper_ticker,
        "is_acronym": is_acronym,
        "humor_irony_score": round(min(1.0, humor_hits * 0.45), 3),
        "controversy_score": round(min(1.0, controversy_hits * 0.5), 3),
        "emotional_intensity_score": round(min(1.0, emotion_hits * 0.35), 3),
        "meme_shareability_score": meme_shareability,
    }

# ==============================================================================
# 2. SOL MARKET CONTEXT HELPER
# ==============================================================================
def load_sol_hourly_lookup():
    path = RAW_DIR / "sol_market_context.json"
    sol_by_hour = {}
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        klines = d.get("sol_1h", [])
        closes = []
        for idx, k in enumerate(klines):
            ts_hr = int(k[0]) // 3600_000
            close_p = float(k[4])
            vol_usdt = float(k[7])
            closes.append(close_p)
            ret_24h = ((close_p / closes[idx - 24]) - 1.0) * 100.0 if idx >= 24 else 0.0
            ret_4h = ((close_p / closes[idx - 4]) - 1.0) * 100.0 if idx >= 4 else 0.0
            volat_24h = float(np.std(np.diff(np.log(closes[max(0, idx-24):idx+1]))) * 100.0) if idx >= 6 else 1.0
            sol_by_hour[ts_hr] = {
                "sol_price_usd": close_p,
                "sol_ret_4h_pct": round(ret_4h, 3),
                "sol_ret_24h_pct": round(ret_24h, 3),
                "sol_volatility_24h": round(volat_24h, 3),
                "sol_1h_vol_usdt": round(vol_usdt, 1),
            }
    return sol_by_hour

def get_sol_at_ts(sol_by_hour: dict, ts_ms: int) -> dict:
    hr = int(ts_ms) // 3600_000
    if hr in sol_by_hour:
        return sol_by_hour[hr]
    if not sol_by_hour:
        return {"sol_price_usd": 80.0, "sol_ret_4h_pct": 0.0, "sol_ret_24h_pct": 0.0, "sol_volatility_24h": 1.2, "sol_1h_vol_usdt": 0.0}
    closest_hr = min(sol_by_hour.keys(), key=lambda k: abs(k - hr))
    return sol_by_hour[closest_hr]

# ==============================================================================
# 3. MAIN PIPELINE EXECUTION
# ==============================================================================
def fmt_ts(ts_ms: int):
    if not ts_ms or ts_ms <= 0:
        return "", ""
    dt_utc = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
    dt_pl = dt_utc.astimezone(WARSAW_TZ)
    return dt_utc.strftime("%Y-%m-%d %H:%M:%S UTC"), dt_pl.strftime("%Y-%m-%d %H:%M:%S %Z")

def wilson_ci(k: int, n: int, z: float = 1.96):
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    half = (z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n)) / denom
    return (round(max(0.0, center - half), 4), round(min(1.0, center + half), 4))

def main():
    logger.info("Loading raw universe, cohort selection, DexScreener, Creators, Holdings, and RPC funding...")
    with open(RAW_DIR / "pumpfun_universe_raw.json", "r", encoding="utf-8") as f:
        coins_by_mint = json.load(f)
    with open(RAW_DIR / "cohort_selection.json", "r", encoding="utf-8") as f:
        cohort_sel = json.load(f)
    selected_mints = cohort_sel["selected_mints"]
    control_matches = cohort_sel["control_matches"]

    ds_map = {}
    if (RAW_DIR / "dexscreener_enrichment.json").exists():
        with open(RAW_DIR / "dexscreener_enrichment.json", "r", encoding="utf-8") as f:
            ds_map = json.load(f)

    creator_db = {}
    if (CREATORS_CACHE_DIR / "creator_histories_complete.json").exists():
        with open(CREATORS_CACHE_DIR / "creator_histories_complete.json", "r", encoding="utf-8") as f:
            creator_db = json.load(f)
    elif (CREATORS_CACHE_DIR / "creator_histories_seed.json").exists():
        with open(CREATORS_CACHE_DIR / "creator_histories_seed.json", "r", encoding="utf-8") as f:
            creator_db = json.load(f)

    holdings_db = {}
    if (HOLDINGS_CACHE_DIR / "wallet_profiles_and_holdings.json").exists():
        with open(HOLDINGS_CACHE_DIR / "wallet_profiles_and_holdings.json", "r", encoding="utf-8") as f:
            holdings_db = json.load(f)

    rpc_db = {"wallets": {}, "funder_classifications": {}}
    if (RPC_CACHE_DIR / "solana_rpc_funding_graph.json").exists():
        with open(RPC_CACHE_DIR / "solana_rpc_funding_graph.json", "r", encoding="utf-8") as f:
            rpc_db = json.load(f)

    sol_by_hour = load_sol_hourly_lookup()

    # --------------------------------------------------------------------------
    # A. SEMANTIC CLUSTERING & FULL UNIVERSE PROCESSING (ALL_TOKENS.csv + NAME_ANALYSIS.csv)
    # --------------------------------------------------------------------------
    logger.info(f"Running semantic TF-IDF + SVD clustering across {len(coins_by_mint)} tokens...")
    all_mints_list = list(coins_by_mint.keys())
    STOPWORDS = {"the", "and", "for", "with", "this", "that", "from", "token", "coin", "on", "of", "to", "in", "is", "it", "by", "be", "are", "as", "at", "an"}
    doc_tokens = []
    df_counts = Counter()
    for m in all_mints_list:
        raw_txt = f"{coins_by_mint[m].get('name') or ''} {coins_by_mint[m].get('symbol') or ''} {(coins_by_mint[m].get('description') or '')[:140]}".lower()
        words = [w for w in re.findall(r"[a-z0-9]{2,}", raw_txt) if w not in STOPWORDS]
        bigrams = [f"{words[k]}_{words[k+1]}" for k in range(len(words) - 1)]
        feats = words + bigrams
        doc_tokens.append(feats)
        for u_f in set(feats):
            df_counts[u_f] += 1

    vocab = [term for term, _ in df_counts.most_common(1200)]
    vocab_idx = {t: idx for idx, t in enumerate(vocab)}
    n_docs = len(all_mints_list)
    rows_sp, cols_sp, vals_sp = [], [], []
    for d_i, feats in enumerate(doc_tokens):
        tf_c = Counter(f for f in feats if f in vocab_idx)
        if not tf_c:
            continue
        norm_sum = 0.0
        tmp = []
        for f, cnt in tf_c.items():
            v_i = vocab_idx[f]
            idf = math.log((1.0 + n_docs) / (1.0 + df_counts[f])) + 1.0
            w_val = cnt * idf
            tmp.append((v_i, w_val))
            norm_sum += w_val * w_val
        norm = math.sqrt(norm_sum) if norm_sum > 0 else 1.0
        for v_i, w_val in tmp:
            rows_sp.append(d_i)
            cols_sp.append(v_i)
            vals_sp.append(w_val / norm)

    X_tfidf = csr_matrix((vals_sp, (rows_sp, cols_sp)), shape=(n_docs, max(1, len(vocab))), dtype=np.float64)
    k_svd = min(20, min(X_tfidf.shape) - 1)
    u_mat, s_vec, _ = svds(X_tfidf, k=k_svd, random_state=42)
    X_svd = u_mat * s_vec
    np.random.seed(42)
    _, sem_clusters = kmeans2(X_svd, 18, minit="points", iter=25)
    sem_cluster_map = {m: int(sem_clusters[i]) for i, m in enumerate(all_mints_list)}

    # Track narrative chronology to detect First-Movers vs Copycats & narrative saturation!
    sorted_by_birth = sorted(
        [(int(coins_by_mint[m].get("created_timestamp") or 0), m) for m in all_mints_list if (coins_by_mint[m].get("created_timestamp") or 0) > 0]
    )
    ticker_seen_count = Counter()
    sem_cluster_24h_window = defaultdict(list)
    copycat_info = {}
    for cts, m in sorted_by_birth:
        sym_norm = re.sub(r"[^a-z0-9]", "", (coins_by_mint[m].get("symbol") or "").lower())
        prev_same_ticker = ticker_seen_count[sym_norm] if sym_norm else 0
        ticker_seen_count[sym_norm] += 1

        sc = sem_cluster_map[m]
        recent_list = sem_cluster_24h_window[sc]
        # prune older than 24h
        cutoff = cts - 24 * 3600_000
        while recent_list and recent_list[0] < cutoff:
            recent_list.pop(0)
        saturation_24h = len(recent_list)
        recent_list.append(cts)
        copycat_info[m] = {
            "prior_identical_ticker_count": prev_same_ticker,
            "is_ticker_first_mover": int(prev_same_ticker == 0),
            "semantic_cluster_24h_launches": saturation_24h,
        }

    # Build ALL_TOKENS & NAME_ANALYSIS base records
    all_tokens_rows = []
    name_analysis_rows = []

    for m in all_mints_list:
        c = coins_by_mint[m]
        cts = int(c.get("created_timestamp") or 0)
        lts = int(c.get("last_trade_timestamp") or 0)
        ath_ts = int(c.get("ath_market_cap_timestamp") or 0)
        sol_ctx = get_sol_at_ts(sol_by_hour, cts if cts > 0 else WINDOW_END_MS)
        sol_p = sol_ctx["sol_price_usd"]

        # Standard pump.fun initial curve mcap = ~27.958 SOL * sol_price_usd (1B supply / 1.073B virtual tokens * 30 virtual SOL)
        mayhem_on = int(c.get("mayhem_state") in ("enabled", "active", "paused", "completed") or (isinstance(c.get("mayhem"), dict) and bool(c["mayhem"].get("state"))))
        init_mcap_est = round(27.96 * sol_p, 2)
        cur_mcap = float(c.get("usd_market_cap") or c.get("market_cap_usd") or 0.0)
        raw_ath_mcap = max(float(c.get("ath_market_cap") or 0.0), cur_mcap)
        liq_usd = float(c.get("canonical_pool_liquidity_usd") or 0.0)
        if m in ds_map:
            liq_usd = max(liq_usd, float((ds_map[m].get("liquidity") or {}).get("usd") or 0.0))

        # Detect spoofed custom-pool / single-tick illiquid ATH anomalies!
        is_spoofed_ath = int(
            (not c.get("complete") and raw_ath_mcap > 180_000)
            or (raw_ath_mcap > 50_000_000 and cur_mcap < 50_000 and liq_usd < 10_000)
            or (raw_ath_mcap > 3_000_000 and cur_mcap < 10_000 and liq_usd < 1_500)
        )
        ath_mcap = cur_mcap if is_spoofed_ath else raw_ath_mcap
        est_mult = round(ath_mcap / max(init_mcap_est, 500.0), 3) if ath_mcap > 0 else 1.0

        in_group_a = int(WINDOW_START_MS <= cts <= WINDOW_END_MS)
        # Preliminary Group B pump event flag on universe level (excluding spoofed wash pools!)
        in_group_b_est = int(
            not is_spoofed_ath and (
                (in_group_a and est_mult >= 2.0 and ath_mcap >= 8000)
                or (cts < WINDOW_START_MS and (ath_ts >= WINDOW_START_MS or (lts >= WINDOW_START_MS and cur_mcap >= 25000)))
            )
        )

        # Status flags (Section 3)
        age_hours = max(0.01, (WINDOW_END_MS - cts) / 3600_000.0) if cts > 0 else 999.0
        hours_since_last_trade = (WINDOW_END_MS - lts) / 3600_000.0 if lts > 0 else 999.0
        status_active = int(hours_since_last_trade <= 48.0 and cur_mcap >= 3500)
        status_inactive = int(not status_active)
        drawdown_from_ath = (1.0 - (cur_mcap / ath_mcap)) if ath_mcap > 0 else 0.0
        status_rug_pull = int(not is_spoofed_ath and ath_mcap >= 12000 and drawdown_from_ath >= 0.88 and cur_mcap < 6000)
        status_migrated = int(bool(c.get("complete")) or bool(c.get("raydium_pool")))
        status_low_liq = int((status_migrated and liq_usd < 5000) or (not status_migrated and cur_mcap < 4500))
        status_incomplete = int(cts <= 0 or (m in selected_mints and not (CANDLES_CACHE_DIR / f"{m}.json").exists()))
        status_suspicious = int(is_spoofed_ath == 1 or mayhem_on == 1 or bool(c.get("is_banned")) or (ath_mcap > 50000 and status_rug_pull == 1))

        narr_cat = classify_narrative(c.get("name"), c.get("symbol"), c.get("description"))
        lex = compute_lexical_features(c.get("name"), c.get("symbol"), c.get("description"))
        cc = copycat_info.get(m, {"prior_identical_ticker_count": 0, "is_ticker_first_mover": 1, "semantic_cluster_24h_launches": 0})
        utc_s, pl_s = fmt_ts(cts)

        all_tokens_rows.append({
            "mint": m,
            "name": (c.get("name") or "").strip(),
            "symbol": (c.get("symbol") or "").strip(),
            "creator": c.get("creator") or "",
            "created_timestamp_ms": cts,
            "created_utc": utc_s,
            "created_warsaw": pl_s,
            "group_a_new_30d": in_group_a,
            "group_b_pump_event": in_group_b_est,
            "in_deep_cohort": int(m in selected_mints),
            "cohort_role": selected_mints.get(m, "universe_population"),
            "status_active": status_active,
            "status_inactive": status_inactive,
            "status_rug_pull": status_rug_pull,
            "status_low_liquidity": status_low_liq,
            "status_incomplete_history": status_incomplete,
            "status_migrated_dex": status_migrated,
            "status_suspicious_activity": status_suspicious,
            "initial_mcap_est_usd": init_mcap_est,
            "current_mcap_usd": round(cur_mcap, 2),
            "ath_mcap_usd": round(ath_mcap, 2),
            "est_multiple": est_mult,
            "drawdown_from_ath_pct": round(drawdown_from_ath * 100.0, 2),
            "liquidity_usd": round(liq_usd, 2),
            "mayhem_enabled": mayhem_on,
            "boost_mode": c.get("boost_mode") or "NONE",
            "is_cashback_enabled": int(bool(c.get("is_cashback_enabled"))),
            "tokenized_agent": int(bool(c.get("tokenized_agent"))),
            "has_twitter": int(bool(c.get("twitter"))),
            "has_website": int(bool(c.get("website"))),
            "has_description": int(bool((c.get("description") or "").strip())),
            "narrative_category": narr_cat,
            "discovery_source": c.get("_discovery_source", ""),
        })

        name_analysis_rows.append({
            "mint": m,
            "name": (c.get("name") or "").strip(),
            "symbol": (c.get("symbol") or "").strip(),
            "group_a_new_30d": in_group_a,
            "narrative_category": narr_cat,
            "semantic_cluster_id": sem_cluster_map[m],
            **lex,
            **cc,
            "est_multiple": est_mult,
            "ath_mcap_usd": round(ath_mcap, 2),
            "migrated_dex": status_migrated,
        })

    # --------------------------------------------------------------------------
    # B. HOURLY & WEEKDAY CONDITIONAL PROBABILITY ANALYSIS (Section 5)
    # --------------------------------------------------------------------------
    # Use all Group A 30d tokens from creator_history_expansion + created_timestamp sweeps as an UNBIASED denominator,
    # AND also report across all 2,722 Group A tokens so conditional probabilities are transparent!
    df_all = pd.DataFrame(all_tokens_rows)
    df_ga = df_all[df_all["group_a_new_30d"] == 1].copy()
    dt_utc_series = pd.to_datetime(df_ga["created_timestamp_ms"], unit="ms", utc=True)
    dt_pl_series = dt_utc_series.dt.tz_convert(WARSAW_TZ)
    df_ga["hour_utc"] = dt_utc_series.dt.hour
    df_ga["hour_warsaw"] = dt_pl_series.dt.hour
    df_ga["weekday_num"] = dt_utc_series.dt.weekday
    df_ga["weekday_name"] = dt_utc_series.dt.day_name()
    df_ga["is_weekend"] = (df_ga["weekday_num"] >= 5).astype(int)
    df_ga["is_us_market_hours"] = df_ga["hour_utc"].between(14, 20).astype(int)
    df_ga["is_eu_us_overlap"] = df_ga["hour_utc"].between(13, 17).astype(int)
    df_ga["pump_2x"] = ((df_ga["est_multiple"] >= 2.0) & (df_ga["ath_mcap_usd"] >= 8000)).astype(int)
    df_ga["pump_5x"] = ((df_ga["est_multiple"] >= 5.0) & (df_ga["ath_mcap_usd"] >= 18000)).astype(int)
    df_ga["pump_10x"] = ((df_ga["est_multiple"] >= 10.0) & (df_ga["ath_mcap_usd"] >= 35000)).astype(int)

    # Specifically track unbiased creator-history launches too!
    df_ga["is_unbiased_sample"] = df_ga["discovery_source"].isin(["creator_history_expansion", "sweep_created_timestamp_None"]).astype(int)

    hourly_rows = []
    for (wd_num, wd_name, hr_utc), grp in df_ga.groupby(["weekday_num", "weekday_name", "hour_utc"]):
        n_tot = len(grp)
        k_2x = int(grp["pump_2x"].sum())
        k_5x = int(grp["pump_5x"].sum())
        k_10x = int(grp["pump_10x"].sum())
        k_mig = int(grp["status_migrated_dex"].sum())
        ci_low, ci_high = wilson_ci(k_5x, n_tot)
        hr_pl = int(grp["hour_warsaw"].mode().iloc[0]) if len(grp) > 0 else (hr_utc + 1) % 24

        unb = grp[grp["is_unbiased_sample"] == 1]
        unb_n = len(unb)
        unb_5x_rate = round(float(unb["pump_5x"].mean()), 4) if unb_n >= 3 else np.nan

        hourly_rows.append({
            "weekday_num": int(wd_num),
            "weekday_name": wd_name,
            "hour_utc": int(hr_utc),
            "hour_warsaw_cet": hr_pl,
            "is_weekend": int(wd_num >= 5),
            "is_us_equity_open_window": int(14 <= hr_utc <= 20),
            "is_eu_us_overlap": int(13 <= hr_utc <= 17),
            "total_launches_sampled": n_tot,
            "pump_2x_count": k_2x,
            "pump_5x_count": k_5x,
            "pump_10x_count": k_10x,
            "migrated_dex_count": k_mig,
            "prob_pump_2x": round(k_2x / max(1, n_tot), 4),
            "prob_pump_5x": round(k_5x / max(1, n_tot), 4),
            "prob_pump_5x_ci95_low": ci_low,
            "prob_pump_5x_ci95_high": ci_high,
            "prob_pump_10x": round(k_10x / max(1, n_tot), 4),
            "unbiased_subsample_n": unb_n,
            "unbiased_prob_pump_5x": unb_5x_rate,
        })

    # --------------------------------------------------------------------------
    # C. DEEP COHORT TRADE, CANDLE, BEHAVIORAL, WALLET & INSIDER RECONSTRUCTION
    # --------------------------------------------------------------------------
    logger.info(f"Reconstructing candles, trades, wallets, clusters, and supply checkpoints for {len(selected_mints)} deep cohort tokens...")

    token_metrics_rows = []
    pump_events_rows = []
    wallet_token_participations = defaultdict(list)
    co_early_pairs = Counter()
    per_token_early_wallets = {}
    supply_conc_rows = []
    wallet_clusters_rows = []
    insider_profit_rows = []
    insider_risk_rows = []
    social_rows = []

    rpc_wallets_map = rpc_db.get("wallets", {})
    funder_class_map = rpc_db.get("funder_classifications", {})

    # Pre-build wallet -> primary funder lookup from Solana RPC forensics
    wallet_to_funders = defaultdict(set)
    direct_sol_links = set()
    for w_addr, rinfo in rpc_wallets_map.items():
        for fo in rinfo.get("funders", []):
            wallet_to_funders[w_addr].add(fo["funder"])
            direct_sol_links.add((fo["funder"], w_addr))
        for to_o in rinfo.get("outbound_sol_targets", []):
            direct_sol_links.add((w_addr, to_o["target"]))

    # First pass over trades to record cross-token co-sniping pairs (first 15 buyers)
    cohort_trades_cache = {}
    cohort_candles_cache = {}
    for m in selected_mints:
        tp = TRADES_CACHE_DIR / f"{m}.json"
        cp = CANDLES_CACHE_DIR / f"{m}.json"
        cohort_trades_cache[m] = json.loads(tp.read_text(encoding="utf-8")).get("trades", []) if tp.exists() else []
        cohort_candles_cache[m] = json.loads(cp.read_text(encoding="utf-8")) if cp.exists() else {}

        first15 = []
        for tr in cohort_trades_cache[m]:
            w = (tr.get("trader") or {}).get("address")
            if tr.get("side") == "buy" and w and w not in TECHNICAL_ADDRESSES and w not in first15:
                first15.append(w)
                if len(first15) >= 15:
                    break
        per_token_early_wallets[m] = first15
        for i in range(len(first15)):
            for j in range(i + 1, len(first15)):
                pair = tuple(sorted((first15[i], first15[j])))
                co_early_pairs[pair] += 1

    # Second pass: Full token-by-token reconstruction
    for m, role in selected_mints.items():
        c = coins_by_mint[m]
        trades = cohort_trades_cache[m]
        cdat = cohort_candles_cache[m]
        c_1m = cdat.get("candles_1m", [])
        c_15m = cdat.get("candles_15m", [])
        c_4h = cdat.get("candles_4h", [])

        cts = int(c.get("created_timestamp") or 0)
        creator = c.get("creator") or ""
        mayhem_on = int(c.get("mayhem_state") in ("enabled", "active", "paused", "completed") or (isinstance(c.get("mayhem"), dict) and bool(c["mayhem"].get("state"))))
        total_supply_tokens = (float(c.get("total_supply") or 1_000_000_000_000_000) / (10 ** int(c.get("base_decimals") or 6)))
        if total_supply_tokens <= 0:
            total_supply_tokens = 2_000_000_000.0 if mayhem_on else 1_000_000_000.0

        sol_ctx = get_sol_at_ts(sol_by_hour, cts if cts > 0 else WINDOW_START_MS)
        sol_p = sol_ctx["sol_price_usd"]

        # Technical addresses specific to this token (excluded from human holder concentration!)
        tok_tech_addrs = set(TECHNICAL_ADDRESSES)
        for field in ["bonding_curve", "associated_bonding_curve", "raydium_pool", "pool_address", "market_id"]:
            if c.get(field):
                tok_tech_addrs.add(c[field])

        # --- 1. Price & Reliable vs Single-Tx vs Liquidity-Adjusted Multiples ---
        # Filter 4h candles to the 30-day research window for Group B & Group A
        c_4h_30d = [bar for bar in c_4h if int(bar.get("openTimeMs") or 0) >= WINDOW_START_MS - 4*3600_000]
        all_bars = sorted(
            c_1m + c_15m + c_4h_30d,
            key=lambda b: int(b.get("openTimeMs") or 0)
        )

        # Raw single-tx price extremes
        tx_prices = [float(t.get("priceUsd") or 0) for t in trades if float(t.get("priceUsd") or 0) > 0]
        init_curve_price = (27.96 * sol_p) / 1_000_000_000.0
        first_tx_price = tx_prices[0] if tx_prices else (float(all_bars[0]["open"]) if all_bars else init_curve_price)

        # Reliable market price: requires volumeUsd >= $20 OR trades >= 2 in candle, or fallback to VWAP of first 3 buys
        reliable_bars = [b for b in all_bars if float(b.get("volumeUsd") or 0) >= 20.0 or int(b.get("trades") or 0) >= 2]
        if reliable_bars:
            first_rel_price = float(reliable_bars[0]["open"])
            # For Group B legacy tokens created prior to 30d window, measure 30d pump from earliest 30d reliable bar!
            if cts < WINDOW_START_MS and c_4h_30d:
                rel_30d = [b for b in c_4h_30d if float(b.get("volumeUsd") or 0) >= 20.0]
                if rel_30d:
                    first_rel_price = float(rel_30d[0]["open"])
            # Max reliable price uses max(close, 0.5*(high+close)) on bars with >=$50 vol to reject single-wick anomalies!
            liq_bars = [b for b in reliable_bars if float(b.get("volumeUsd") or 0) >= 50.0 and int(b.get("openTimeMs") or 0) >= (WINDOW_START_MS - 4*3600_000)]
            if liq_bars:
                max_rel_bar = max(liq_bars, key=lambda b: max(float(b["close"]), 0.5 * (float(b["high"]) + float(b["close"]))))
                max_rel_price = max(float(max_rel_bar["close"]), 0.5 * (float(max_rel_bar["high"]) + float(max_rel_bar["close"])))
                ath_bar_ts = int(max_rel_bar["openTimeMs"])
            else:
                max_rel_bar = max(reliable_bars, key=lambda b: float(b["close"]))
                max_rel_price = float(max_rel_bar["close"])
                ath_bar_ts = int(max_rel_bar["openTimeMs"])
        else:
            first_rel_price = max(first_tx_price, init_curve_price * 0.8)
            max_rel_price = first_rel_price
            ath_bar_ts = int(c.get("ath_market_cap_timestamp") or cts)

        # Cross-check with pump.fun indexed ath_market_cap for Group A tokens whose ATH occurred between 1m & 4h windows
        eff_supply_for_mcap = 1_000_000_000.0  # canonical circulating mcap basis on pump.fun
        indexed_ath_mcap = float(c.get("ath_market_cap") or 0.0)
        indexed_cur_mcap = float(c.get("usd_market_cap") or c.get("market_cap_usd") or 0.0)
        if cts >= WINDOW_START_MS and indexed_ath_mcap > max_rel_price * eff_supply_for_mcap:
            # Accept indexed ATH only if supported by multiple trades (not single-tx glitch)
            if len(trades) >= 8:
                max_rel_price = max(max_rel_price, (indexed_ath_mcap / eff_supply_for_mcap) * 0.92)
                if c.get("ath_market_cap_timestamp"):
                    ath_bar_ts = int(c["ath_market_cap_timestamp"])

        first_rel_price = max(first_rel_price, 1e-10)
        raw_single_tx_max = max([max(tx_prices) if tx_prices else max_rel_price, indexed_ath_mcap / eff_supply_for_mcap, max_rel_price])
        raw_single_tx_mult = round(raw_single_tx_max / max(min(tx_prices) if tx_prices else first_rel_price, 1e-10), 3)
        reliable_mult = round(max(1.0, max_rel_price / first_rel_price), 3)

        # Liquidity & Slippage-adjusted realizable multiple for a $500 position exit
        ds_rec = ds_map.get(m, {})
        liq_usd = max(
            float(c.get("canonical_pool_liquidity_usd") or 0.0),
            float((ds_rec.get("liquidity") or {}).get("usd") or 0.0),
            # Bonding curve virtual liquidity ~ 2 * 30 SOL * sol_p * sqrt(cur_mult) when unmigrated
            (60.0 * sol_p) if not c.get("complete") else 12000.0
        )
        # Constant-product pool depth on one side = 0.5 * liq_usd; selling $500 realizes 1 / (1 + 500 / (0.5 * liq_usd)) minus 1.2% fees
        exit_notional_usd = 500.0
        one_side_depth = max(250.0, 0.5 * liq_usd)
        slippage_factor = (1.0 / (1.0 + exit_notional_usd / one_side_depth)) * 0.988
        realizable_mult = round(max(0.5, reliable_mult * slippage_factor), 3)

        init_mcap_usd = round(first_rel_price * eff_supply_for_mcap, 2)
        max_mcap_usd = round(max_rel_price * eff_supply_for_mcap, 2)
        cur_price_est = float(c_4h[-1]["close"]) if c_4h else (tx_prices[-1] if tx_prices else first_rel_price)
        if indexed_cur_mcap > 0:
            cur_price_est = indexed_cur_mcap / eff_supply_for_mcap
        max_dd_pct = round(max(0.0, (1.0 - cur_price_est / max(max_rel_price, 1e-10)) * 100.0), 2)

        # --- 2. Multi-Horizon Fastest Price Velocities (Ranking B: 1m, 5m, 15m, 30m, 1h, 4h, 24h) ---
        def max_window_gain(bars, step_bars):
            if not bars or len(bars) < 1:
                return 0.0
            best_g = 0.0
            for i in range(len(bars)):
                p0 = float(bars[i].get("open") or 0)
                if p0 <= 0 or float(bars[i].get("volumeUsd") or 0) < 5.0:
                    continue
                j_end = min(len(bars), i + step_bars)
                p1 = max(float(bars[j].get("close") or 0) for j in range(i, j_end))
                best_g = max(best_g, (p1 / p0) - 1.0)
            return round(best_g * 100.0, 2)

        max_ret_1m_pct = max_window_gain(c_1m, 1)
        max_ret_5m_pct = max_window_gain(c_1m, 5)
        max_ret_15m_pct = max(max_window_gain(c_1m, 15), max_window_gain(c_15m, 1))
        max_ret_30m_pct = max(max_window_gain(c_1m, 30), max_window_gain(c_15m, 2))
        max_ret_1h_pct = max(max_window_gain(c_1m, 60), max_window_gain(c_15m, 4))
        max_ret_4h_pct = max(max_window_gain(c_15m, 16), max_window_gain(c_4h_30d, 1))
        max_ret_24h_pct = max_window_gain(c_4h_30d, 6)

        # Total observed volume USD
        vol_4h_sum = sum(float(b.get("volumeUsd") or 0) for b in c_4h_30d)
        vol_1m_sum = sum(float(b.get("volumeUsd") or 0) for b in c_1m)
        vol_ds_24h = float((ds_rec.get("volume") or {}).get("h24") or 0.0)
        total_vol_usd = round(max(vol_4h_sum, vol_1m_sum, vol_ds_24h), 2)

        # Stagnation Pump (Ranking D) & Multi-Wave Pump (Ranking E) detection on 4h / 15m series
        series_bars = c_4h_30d if len(c_4h_30d) >= 5 else c_15m
        stagnation_pump_flag = 0
        stagnation_hours = 0.0
        if cts < WINDOW_START_MS and reliable_mult >= 2.5:
            stagnation_pump_flag = 1
            stagnation_hours = round((ath_bar_ts - cts) / 3600_000.0, 1)
        elif len(c_4h_30d) >= 6 and reliable_mult >= 3.0:
            # Check how many initial 4h bars stayed < 1.6x first_rel_price before surging
            quiet_bars = 0
            for b in c_4h_30d:
                if float(b.get("close") or 0) < first_rel_price * 1.6:
                    quiet_bars += 1
                else:
                    break
            if quiet_bars >= 3:  # >= 12 hours of flat stagnation prior to breakout!
                stagnation_pump_flag = 1
                stagnation_hours = quiet_bars * 4.0

        wave_count = 1 if reliable_mult >= 2.0 else 0
        multi_wave_flag = 0
        if len(series_bars) >= 6 and reliable_mult >= 2.5:
            closes_s = [float(b.get("close") or 0) for b in series_bars if float(b.get("close") or 0) > 0]
            # Detect Peak1 >= 2.2x -> Trough <= 0.65 * Peak1 -> Peak2 >= 1.65 * Trough
            p_base = closes_s[0] if closes_s else first_rel_price
            state = 0
            peak1 = p_base
            trough1 = p_base
            for px in closes_s[1:]:
                if state == 0:
                    if px > peak1:
                        peak1 = px
                    elif peak1 >= p_base * 2.2 and px <= peak1 * 0.65:
                        state = 1
                        trough1 = px
                elif state == 1:
                    if px < trough1:
                        trough1 = px
                    elif px >= trough1 * 1.65:
                        state = 2
                        wave_count += 1
                        peak1 = px
                elif state == 2:
                    if px > peak1:
                        peak1 = px
                    elif px <= peak1 * 0.65:
                        state = 1
                        trough1 = px
            if wave_count >= 2:
                multi_wave_flag = 1

        # --- 3. Trade-Level Buyer Psychology, FOMO Transition, Order Sizes & Pullback Absorption ---
        anchor_ts = cts if (cts >= WINDOW_START_MS and cts > 0) else (int(trades[0]["blockTimeMs"]) if trades else WINDOW_START_MS)
        first_buy_ts = None
        buyers_seen = {}
        buy_counts_wallet = Counter()
        buy_usd_list = []
        sell_usd_list = []
        minute_new_buyers = Counter()
        minute_buys = Counter()
        minute_sells = Counter()
        minute_buy_usd = defaultdict(float)
        minute_sell_usd = defaultdict(float)
        minute_prices = {}

        t_10_buyers_sec = np.nan
        t_50_buyers_sec = np.nan
        t_2x_sec = np.nan
        t_5x_sec = np.nan
        first_major_sell_sec = np.nan
        creator_sold_tokens = 0.0
        creator_bought_tokens = 0.0

        # Also track wallet balances over trade tape for 7 Supply Concentration checkpoints!
        wallet_tok_bal = defaultdict(float)
        wallet_sol_spent = defaultdict(float)
        wallet_sol_recv = defaultdict(float)
        wallet_tok_bought = defaultdict(float)
        wallet_tok_sold = defaultdict(float)
        wallet_tx_count = Counter()
        wallet_first_buy_sec = {}
        wallet_first_sell_sec = {}

        # Same-block sniper/bundle detection at launch (within first 15s of first trade)
        block_tx_buyers = defaultdict(list)

        snapshots_supply = {}
        n_tr = len(trades)
        idx_checkpoints = {
            "1_launch": max(0, min(n_tr - 1, 2)),
            "2_pre_pump_early": max(0, min(n_tr - 1, int(n_tr * 0.12))),
            "3_pump_onset": max(0, min(n_tr - 1, int(n_tr * 0.28))),
            "4_peak_volume": max(0, min(n_tr - 1, int(n_tr * 0.55))),
            "5_ath": max(0, min(n_tr - 1, int(n_tr * 0.72))),
            "6_post_ath": max(0, min(n_tr - 1, int(n_tr * 0.88))),
            "7_latest": max(0, n_tr - 1),
        }
        inv_cp = defaultdict(list)
        for cp_name, cp_i in idx_checkpoints.items():
            inv_cp[cp_i].append(cp_name)

        for idx, tr in enumerate(trades):
            tms = int(tr.get("blockTimeMs") or anchor_ts)
            rel_sec = max(0.0, (tms - anchor_ts) / 1000.0)
            rel_min = int(rel_sec // 60)
            w = (tr.get("trader") or {}).get("address") or ""
            side = tr.get("side")
            val_usd = float(tr.get("valueUsd") or 0.0)
            val_sol = float(tr.get("valueNative") or 0.0)
            px = float(tr.get("priceUsd") or 0.0)
            raw_b = float((tr.get("baseAmount") or {}).get("raw") or 0.0)
            dec_b = int((tr.get("baseAmount") or {}).get("decimals") or 6)
            tok_amt = raw_b / (10 ** dec_b)

            if px >= first_rel_price * 2.0 and np.isnan(t_2x_sec) and idx >= 2:
                t_2x_sec = round(rel_sec, 1)
            if px >= first_rel_price * 5.0 and np.isnan(t_5x_sec) and idx >= 3:
                t_5x_sec = round(rel_sec, 1)

            if w and w not in tok_tech_addrs:
                wallet_tx_count[w] += 1
                if side == "buy":
                    if first_buy_ts is None:
                        first_buy_ts = tms
                    if rel_sec <= 20.0:
                        block_tx_buyers[int(tr.get("blockId") or 0)].append((int(tr.get("txIndex") or 0), w))
                    if w not in buyers_seen:
                        buyers_seen[w] = rel_sec
                        wallet_first_buy_sec[w] = rel_sec
                        if rel_min <= 60:
                            minute_new_buyers[rel_min] += 1
                        if len(buyers_seen) == 10:
                            t_10_buyers_sec = round(rel_sec, 1)
                        elif len(buyers_seen) == 50:
                            t_50_buyers_sec = round(rel_sec, 1)
                    buy_counts_wallet[w] += 1
                    buy_usd_list.append(val_usd)
                    if rel_min <= 60:
                        minute_buys[rel_min] += 1
                        minute_buy_usd[rel_min] += val_usd
                        minute_prices[rel_min] = px
                    wallet_tok_bal[w] += tok_amt
                    wallet_tok_bought[w] += tok_amt
                    wallet_sol_spent[w] += val_sol
                    if w == creator:
                        creator_bought_tokens += tok_amt
                elif side == "sell":
                    sell_usd_list.append(val_usd)
                    if w not in wallet_first_sell_sec:
                        wallet_first_sell_sec[w] = rel_sec
                    if val_usd >= 250.0 and np.isnan(first_major_sell_sec):
                        first_major_sell_sec = round(rel_sec, 1)
                    if rel_min <= 60:
                        minute_sells[rel_min] += 1
                        minute_sell_usd[rel_min] += val_usd
                        minute_prices[rel_min] = px
                    wallet_tok_bal[w] = max(0.0, wallet_tok_bal[w] - tok_amt)
                    wallet_tok_sold[w] += tok_amt
                    wallet_sol_recv[w] += val_sol
                    if w == creator:
                        creator_sold_tokens += tok_amt

            if idx in inv_cp:
                snap_copy = {k: v for k, v in wallet_tok_bal.items() if v > 0}
                for cp_name in inv_cp[idx]:
                    snapshots_supply[cp_name] = snap_copy

        # Buyer size composition (Small <$25, Medium $25-$250, Large >$250)
        n_buys = len(buy_usd_list)
        small_buy_share = round(sum(1 for v in buy_usd_list if v < 25.0) / max(1, n_buys), 4)
        med_buy_share = round(sum(1 for v in buy_usd_list if 25.0 <= v <= 250.0) / max(1, n_buys), 4)
        large_buy_share = round(sum(1 for v in buy_usd_list if v > 250.0) / max(1, n_buys), 4)
        early10_buys = buy_usd_list[:10]
        late_buys = buy_usd_list[10:60] if len(buy_usd_list) > 15 else buy_usd_list
        early_avg_buy_usd = round(float(np.mean(early10_buys)) if early10_buys else 0.0, 2)
        later_avg_buy_usd = round(float(np.mean(late_buys)) if late_buys else 0.0, 2)
        scale_in_buyer_share = round(sum(1 for w, cnt in buy_counts_wallet.items() if cnt >= 2) / max(1, len(buyers_seen)), 4)

        buyers_1m = sum(1 for s in buyers_seen.values() if s <= 60.0)
        buyers_3m = sum(1 for s in buyers_seen.values() if s <= 180.0)
        buyers_5m = sum(1 for s in buyers_seen.values() if s <= 300.0)
        buyers_15m = sum(1 for s in buyers_seen.values() if s <= 900.0)
        buyers_30m = sum(1 for s in buyers_seen.values() if s <= 1800.0)

        # FOMO Transition Index (Section 7B): detects minute of peak buyer acceleration after initial price lift
        fomo_onset_min = np.nan
        max_accel_ratio = 0.0
        for mn in range(1, 31):
            prev_rate = (minute_new_buyers[max(0, mn - 2)] + minute_new_buyers[mn - 1]) / 2.0 if mn >= 2 else float(minute_new_buyers[0])
            cur_rate = float(minute_new_buyers[mn])
            accel = (cur_rate + 1.0) / (prev_rate + 1.0)
            px_m = minute_prices.get(mn, first_rel_price)
            if accel > max_accel_ratio and cur_rate >= 4:
                max_accel_ratio = accel
                if px_m >= first_rel_price * 1.25 and np.isnan(fomo_onset_min):
                    fomo_onset_min = mn
        total_buy_usd = sum(buy_usd_list)
        total_sell_usd = sum(sell_usd_list)
        buy_sell_usd_ratio = round((total_buy_usd + 10.0) / (total_sell_usd + 10.0), 3)
        fomo_transition_index = round(
            min(100.0, 25.0 * min(3.0, max_accel_ratio) + 15.0 * min(2.0, buy_sell_usd_ratio / 1.5)),
            2
        )

        # First Pullback Absorption (Section 7D): inspect first >=12% dip in trades
        peak_so_far = first_rel_price
        in_dip = False
        dip_buy_usd = 0.0
        dip_sell_usd = 0.0
        dip_new_buyers = 0
        for tr in trades[:150]:
            px = float(tr.get("priceUsd") or 0)
            val = float(tr.get("valueUsd") or 0)
            w = (tr.get("trader") or {}).get("address") or ""
            if not in_dip:
                if px > peak_so_far:
                    peak_so_far = px
                elif peak_so_far >= first_rel_price * 1.25 and px <= peak_so_far * 0.88:
                    in_dip = True
            else:
                if tr.get("side") == "buy":
                    dip_buy_usd += val
                    if buy_counts_wallet[w] == 1:
                        dip_new_buyers += 1
                elif tr.get("side") == "sell":
                    dip_sell_usd += val
                if px >= peak_so_far:
                    break
        dip_absorption_ratio = round((dip_buy_usd + 5.0) / (dip_sell_usd + 5.0), 3) if in_dip else np.nan

        # --- 4. Graph Clustering & Insider Detection (Modules 8 & 9) ---
        G = nx.Graph()
        token_participants = [w for w in wallet_tx_count if w not in tok_tech_addrs]
        for w in token_participants:
            G.add_node(w)

        edge_records = []
        # 4a. Same-block Jito/Bundler execution at launch
        bundle_wallets = set()
        for blk_id, tx_list in block_tx_buyers.items():
            uniq_w = list(dict.fromkeys([w for _, w in sorted(tx_list)]))
            if len(uniq_w) >= 2:
                for bw in uniq_w:
                    bundle_wallets.add(bw)
                for i in range(len(uniq_w) - 1):
                    u, v = uniq_w[i], uniq_w[i+1]
                    G.add_edge(u, v, link_type="SAME_BLOCK_BUNDLE", confidence="HIGH",
                               evidence=f"Co-bought in launch block {blk_id}",
                               alt="Coincidental public mempool sniper collision in same slot")

        # 4b. Direct SOL transfers & shared RPC funders
        for i in range(len(token_participants)):
            u = token_participants[i]
            if creator and creator != u and ((creator, u) in direct_sol_links or (u, creator) in direct_sol_links):
                G.add_edge(creator, u, link_type="DIRECT_SOL_FUNDING_CREATOR", confidence="HIGH",
                           evidence="Direct on-chain SOL transfer with creator wallet",
                           alt="OTC settlement or prior shared dev transfer")
            f_u = wallet_to_funders.get(u, set())
            for j in range(i + 1, len(token_participants)):
                v = token_participants[j]
                if (u, v) in direct_sol_links or (v, u) in direct_sol_links:
                    G.add_edge(u, v, link_type="DIRECT_SOL_TRANSFER", confidence="HIGH",
                               evidence="Direct native SOL transfer observed via Solana RPC",
                               alt="P2P transfer between independent traders")
                shared_f = f_u.intersection(wallet_to_funders.get(v, set()))
                for sf in shared_f:
                    f_cls = funder_class_map.get(sf, {}).get("type", "PERSONAL_OR_DEDICATED_FUNDER")
                    if f_cls == "CEX_OR_HIGH_FREQ_SERVICE":
                        # Do NOT merge into high-confidence operator cluster! Record low-confidence note only
                        edge_records.append((u, v, "SHARED_CEX_HOTWALLET", "LOW", f"Shared high-freq funder {sf[:8]}..", "Likely shared CEX/bridge withdrawal hot wallet"))
                    else:
                        G.add_edge(u, v, link_type="SHARED_PERSONAL_FUNDER", confidence="HIGH",
                                   evidence=f"Funded on-chain by dedicated parent wallet {sf[:10]}...",
                                   alt="Shared private trading group treasury")

                # 4c. Cross-token repeated co-sniping (>=3 tokens together in first 15 buyers)
                pair_k = tuple(sorted((u, v)))
                if co_early_pairs[pair_k] >= 3 and not G.has_edge(u, v):
                    G.add_edge(u, v, link_type="CROSS_TOKEN_CO_SNIPE", confidence="MEDIUM",
                               evidence=f"Co-entered first 15 buyers in {co_early_pairs[pair_k]} tokens",
                               alt="Competing sniper bots subscribing to identical launch triggers")

        # Extract non-trivial connected components (size >= 2, or creator + bundle)
        clusters_this_token = []
        clustered_wallets_set = set()
        sniper_wallets_set = {w for w, s in wallet_first_buy_sec.items() if s <= 6.0}

        comp_idx = 0
        for comp in nx.connected_components(G):
            if len(comp) >= 2:
                comp_idx += 1
                comp_list = sorted(comp)
                clustered_wallets_set.update(comp_list)
                sub = G.subgraph(comp)
                etypes = Counter(d.get("link_type", "UNKNOWN") for _, _, d in sub.edges(data=True))
                confs = [d.get("confidence", "MEDIUM") for _, _, d in sub.edges(data=True)]
                sample_ev = next((d.get("evidence", "") for _, _, d in sub.edges(data=True)), "")
                sample_alt = next((d.get("alt", "") for _, _, d in sub.edges(data=True)), "")
                top_conf = "HIGH" if "HIGH" in confs else ("MEDIUM" if "MEDIUM" in confs else "LOW")
                dom_type = etypes.most_common(1)[0][0]

                # Calculate cluster economics (Module 9C & 9D)
                c_sol_spent = sum(wallet_sol_spent[w] for w in comp_list)
                c_sol_recv = sum(wallet_sol_recv[w] for w in comp_list)
                c_tok_bought = sum(wallet_tok_bought[w] for w in comp_list)
                c_tok_sold = sum(wallet_tok_sold[w] for w in comp_list)
                c_tok_retained = max(0.0, c_tok_bought - c_tok_sold)

                # Cross-check live holdings from profile-api.pump.fun if available!
                live_verified_bal = 0.0
                has_live_check = False
                for w in comp_list:
                    if w in holdings_db:
                        has_live_check = True
                        for t_item in holdings_db[w].get("tokens", []):
                            if t_item.get("mint") == m:
                                live_verified_bal += float(t_item.get("balance") or 0.0)
                if has_live_check and live_verified_bal > 0:
                    c_tok_retained = live_verified_bal

                retained_pct = round((c_tok_retained / total_supply_tokens) * 100.0, 4)
                accum_pct = round((c_tok_bought / total_supply_tokens) * 100.0, 4)
                tx_cnt_cluster = sum(wallet_tx_count[w] for w in comp_list)
                est_fees_sol = round(tx_cnt_cluster * 0.0005 + (c_sol_spent + c_sol_recv) * 0.01, 5)
                realized_pnl_sol = round(c_sol_recv - c_sol_spent - est_fees_sol, 4)
                realized_pnl_usd = round(realized_pnl_sol * sol_p, 2)
                unrealized_mtm_usd = round(c_tok_retained * cur_price_est, 2)
                unrealized_mtm_sol = round(unrealized_mtm_usd / max(sol_p, 1.0), 4)

                sell_ratio = c_tok_sold / max(c_tok_bought, 1.0)
                if retained_pct >= 2.0 and 0.10 <= sell_ratio <= 0.75 and reliable_mult >= 2.5:
                    ret_pattern = "PARTIAL_TAKE_PROFIT_HIGH_RETENTION"
                elif sell_ratio > 0.85:
                    ret_pattern = "FULL_DISTRIBUTION_EXIT"
                elif sell_ratio < 0.10 and retained_pct >= 1.0:
                    ret_pattern = "STRONG_HOLD_ACCUMULATION"
                else:
                    ret_pattern = "MINOR_TRADING_CLUSTER"

                dump_val_usd = unrealized_mtm_usd
                liq_impact_pct = round((1.0 - (one_side_depth / (one_side_depth + dump_val_usd)) ** 2) * 100.0, 2) if dump_val_usd > 0 else 0.0

                cid_str = f"{m[:6]}_CL{comp_idx}"
                clusters_this_token.append({
                    "cluster_id": cid_str,
                    "wallets": comp_list,
                    "retained_pct": retained_pct,
                    "accum_pct": accum_pct,
                    "confidence": top_conf,
                    "realized_pnl_sol": realized_pnl_sol,
                })

                wallet_clusters_rows.append({
                    "cluster_id": cid_str,
                    "mint": m,
                    "symbol": (c.get("symbol") or "").strip(),
                    "cohort_role": role,
                    "wallets_count": len(comp_list),
                    "includes_creator": int(creator in comp_list),
                    "wallet_sample": ";".join(comp_list[:5]),
                    "dominant_link_type": dom_type,
                    "evidence_basis": sample_ev,
                    "confidence_level": top_conf,
                    "alternative_explanation": sample_alt,
                    "accumulated_supply_pct": accum_pct,
                    "retained_supply_pct": retained_pct,
                })

                insider_profit_rows.append({
                    "cluster_id": cid_str,
                    "mint": m,
                    "symbol": (c.get("symbol") or "").strip(),
                    "wallets_count": len(comp_list),
                    "confidence_level": top_conf,
                    "sol_spent_buys": round(c_sol_spent, 4),
                    "tokens_accumulated": round(c_tok_bought, 1),
                    "tokens_sold": round(c_tok_sold, 1),
                    "sol_received_sells": round(c_sol_recv, 4),
                    "est_fees_sol": est_fees_sol,
                    "realized_profit_sol": realized_pnl_sol,
                    "realized_profit_usd": realized_pnl_usd,
                    "tokens_retained": round(c_tok_retained, 1),
                    "retained_supply_pct": retained_pct,
                    "unrealized_mtm_sol_not_realized": unrealized_mtm_sol,
                    "unrealized_mtm_usd_not_realized": unrealized_mtm_usd,
                    "live_profile_verified": int(has_live_check),
                    "retention_pattern": ret_pattern,
                    "est_liquidity_price_impact_if_dumped_pct": liq_impact_pct,
                })

        # --- 5. Supply Concentration Across 7 Lifecycle Checkpoints (Module 9B) ---
        potential_insiders_set = set(clustered_wallets_set) | ({creator} if creator else set()) | bundle_wallets
        for cp_name in ["1_launch", "2_pre_pump_early", "3_pump_onset", "4_peak_volume", "5_ath", "6_post_ath", "7_latest"]:
            snap = dict(snapshots_supply.get(cp_name, {}))
            if cp_name == "7_latest":
                for w in list(snap.keys()) + ([creator] if creator else []):
                    if w in holdings_db:
                        for ti in holdings_db[w].get("tokens", []):
                            if ti.get("mint") == m and ti.get("balance") is not None:
                                snap[w] = float(ti["balance"])
            bals_sorted = sorted([v for k, v in snap.items() if k not in tok_tech_addrs and v > 0], reverse=True)
            top1_pct = round((sum(bals_sorted[:1]) / total_supply_tokens) * 100.0, 4)
            top5_pct = round((sum(bals_sorted[:5]) / total_supply_tokens) * 100.0, 4)
            top10_pct = round((sum(bals_sorted[:10]) / total_supply_tokens) * 100.0, 4)
            top20_pct = round((sum(bals_sorted[:20]) / total_supply_tokens) * 100.0, 4)
            clusters_pct = round((sum(snap.get(w, 0.0) for w in clustered_wallets_set) / total_supply_tokens) * 100.0, 4)
            creator_pct = round((snap.get(creator, 0.0) / total_supply_tokens) * 100.0, 4) if creator else 0.0
            insiders_pct = round((sum(snap.get(w, 0.0) for w in potential_insiders_set) / total_supply_tokens) * 100.0, 4)
            snipers_pct = round((sum(snap.get(w, 0.0) for w in sniper_wallets_set) / total_supply_tokens) * 100.0, 4)

            supply_conc_rows.append({
                "mint": m,
                "symbol": (c.get("symbol") or "").strip(),
                "cohort_role": role,
                "checkpoint": cp_name,
                "top1_holder_pct": min(100.0, top1_pct),
                "top5_holders_pct": min(100.0, top5_pct),
                "top10_holders_pct": min(100.0, top10_pct),
                "top20_holders_pct": min(100.0, top20_pct),
                "detected_clusters_pct": min(100.0, clusters_pct),
                "creator_wallet_pct": min(100.0, creator_pct),
                "potential_insiders_pct": min(100.0, insiders_pct),
                "sniper_wallets_pct": min(100.0, snipers_pct),
                "observed_active_holders": len(bals_sorted),
            })

        # Extract key supply checkpoints for token-level risk & metrics
        cp_early = next((r for r in reversed(supply_conc_rows) if r["mint"] == m and r["checkpoint"] == "2_pre_pump_early"), {})
        cp_ath = next((r for r in reversed(supply_conc_rows) if r["mint"] == m and r["checkpoint"] == "5_ath"), {})
        cp_lat = next((r for r in reversed(supply_conc_rows) if r["mint"] == m and r["checkpoint"] == "7_latest"), {})

        # --- 6. Sell Pressure Scenarios (1%, 5%, 10%, 25% of supply) & Insider / Manipulation Risk Scores (Module 9E, 9F, 17B, 17C) ---
        def est_dump_impact_pct(supply_frac: float) -> float:
            dump_usd = (supply_frac * eff_supply_for_mcap) * cur_price_est
            if dump_usd <= 0:
                return 0.0
            # Constant-product AMM price drop = 1 - (R_quote_depth / (R_quote_depth + dump_usd_equiv))^2
            return round(min(99.9, (1.0 - (one_side_depth / (one_side_depth + dump_usd)) ** 2) * 100.0), 2)

        imp_1pct = est_dump_impact_pct(0.01)
        imp_5pct = est_dump_impact_pct(0.05)
        imp_10pct = est_dump_impact_pct(0.10)
        imp_25pct = est_dump_impact_pct(0.25)

        high_conf_clusters = sum(1 for cl in clusters_this_token if cl["confidence"] == "HIGH")
        insider_supply_peak = max(cp_early.get("potential_insiders_pct", 0.0), cp_ath.get("potential_insiders_pct", 0.0))
        insider_supply_now = cp_lat.get("potential_insiders_pct", 0.0)
        top10_peak = max(cp_early.get("top10_holders_pct", 0.0), cp_ath.get("top10_holders_pct", 0.0))
        creator_dumped_flag = int(creator_sold_tokens > 0 and creator_sold_tokens >= 0.5 * max(creator_bought_tokens, 1.0))

        insider_risk_score = round(min(100.0, (
            min(30.0, top10_peak * 1.1)
            + min(25.0, insider_supply_peak * 1.8)
            + min(15.0, high_conf_clusters * 7.5)
            + (10.0 if creator_dumped_flag else 0.0)
            + min(20.0, imp_5pct * 0.25)
        )), 2)

        manipulation_risk_score = round(min(100.0, (
            (22.0 if mayhem_on else 0.0)
            + min(25.0, len(bundle_wallets) * 5.0)
            + min(20.0, cp_early.get("sniper_wallets_pct", 0.0) * 1.5)
            + (15.0 if liq_usd < 8000 else (7.0 if liq_usd < 25000 else 0.0))
            + min(18.0, high_conf_clusters * 6.0)
        )), 2)

        insider_risk_rows.append({
            "mint": m,
            "symbol": (c.get("symbol") or "").strip(),
            "cohort_role": role,
            "top10_holders_peak_pct": top10_peak,
            "potential_insiders_peak_pct": insider_supply_peak,
            "potential_insiders_retained_pct": insider_supply_now,
            "detected_clusters_count": len(clusters_this_token),
            "high_confidence_clusters_count": high_conf_clusters,
            "bundle_wallets_count": len(bundle_wallets),
            "creator_dumped_flag": creator_dumped_flag,
            "mayhem_ai_agent_enabled": mayhem_on,
            "liquidity_usd": round(liq_usd, 2),
            "sell_impact_1pct_supply_pct": imp_1pct,
            "sell_impact_5pct_supply_pct": imp_5pct,
            "sell_impact_10pct_supply_pct": imp_10pct,
            "sell_impact_25pct_supply_pct": imp_25pct,
            "insider_supply_risk_score": insider_risk_score,
            "manipulation_risk_score": manipulation_risk_score,
        })

        # --- 7. Record Wallet Participations for Smart Money Discovery (Module 8) ---
        is_verified_pump = int(reliable_mult >= 3.0 and max_mcap_usd >= 12000)
        for rank_idx, (w, entry_s) in enumerate(sorted(buyers_seen.items(), key=lambda x: x[1])):
            sell_s = wallet_first_sell_sec.get(w, np.nan)
            hold_min = round((sell_s - entry_s) / 60.0, 2) if not np.isnan(sell_s) and sell_s >= entry_s else np.nan
            w_pnl_sol = wallet_sol_recv[w] - wallet_sol_spent[w]
            wallet_token_participations[w].append({
                "mint": m,
                "buyer_rank": rank_idx + 1,
                "entry_sec": entry_s,
                "hold_min": hold_min,
                "is_pump": is_verified_pump,
                "token_reliable_mult": reliable_mult,
                "is_bundle": int(w in bundle_wallets),
                "is_creator": int(w == creator),
                "is_clustered": int(w in clustered_wallets_set),
                "sol_spent": wallet_sol_spent[w],
                "sol_recv": wallet_sol_recv[w],
                "net_sol": w_pnl_sol,
                "tx_count": wallet_tx_count[w],
            })

        # --- 8. Classify Pump Profile (Section 18: Profiles 1..11) ---
        time_to_ath_min = round(max(0.1, (ath_bar_ts - (cts if cts >= WINDOW_START_MS else WINDOW_START_MS)) / 60000.0), 2)
        if reliable_mult < 2.0:
            pump_profile = "0_NO_PUMP_CONTROL"
        elif multi_wave_flag == 1:
            pump_profile = "11_MULTI_WAVE_PUMP"
        elif stagnation_pump_flag == 1:
            pump_profile = "3_POST_STAGNATION_PUMP"
        elif time_to_ath_min <= 20.0 and max_ret_5m_pct >= 100.0:
            pump_profile = "1_ULTRA_FAST_IGNITION_PUMP"
        elif high_conf_clusters >= 1 and insider_supply_peak >= 8.0:
            pump_profile = "9_INSIDER_CLUSTER_DRIVEN_PUMP"
        elif top10_peak >= 22.0:
            pump_profile = "8_HIGH_SUPPLY_CONCENTRATION_PUMP"
        elif in_dip and (dip_absorption_ratio or 0) >= 1.35:
            pump_profile = "4_POST_CORRECTION_ABSORPTION_PUMP"
        elif early_avg_buy_usd >= 220.0:
            pump_profile = "6_WHALE_INITIATED_PUMP"
        elif small_buy_share >= 0.68 and buyers_15m >= 25:
            pump_profile = "5_RETAIL_SMALL_BUY_SWARM"
        elif bool(c.get("twitter")) and compute_lexical_features(c.get("name"), c.get("symbol"), c.get("description"))["meme_shareability_score"] >= 0.68:
            pump_profile = "7_VIRAL_NARRATIVE_MEME_PUMP"
        elif buyers_30m >= 30 and insider_risk_score < 35.0:
            pump_profile = "10_ORGANIC_BUYER_GROWTH_PUMP"
        else:
            pump_profile = "2_GRADUAL_ACCUMULATION_PUMP"

        # --- 9. Social & External Narrative Metadata (Modules 11, 12, 19) ---
        tw_url = str(c.get("twitter") or "").strip()
        if not tw_url:
            tw_type = "none"
        elif "/status/" in tw_url:
            tw_type = "specific_viral_post_or_tweet"
        elif "/i/communities/" in tw_url:
            tw_type = "x_community_group"
        else:
            tw_type = "dedicated_handle_or_profile"

        ds_socials = ((ds_rec.get("info") or {}).get("socials") or [])
        ds_boosts = int(((ds_rec.get("boosts") or {}).get("active") or 0))
        narr_cat = classify_narrative(c.get("name"), c.get("symbol"), c.get("description"))
        lex_m = compute_lexical_features(c.get("name"), c.get("symbol"), c.get("description"))

        # Check alignment with major Oct-Nov 2026 external events
        ext_event = "NONE"
        txt_full = f"{c.get('name') or ''} {c.get('symbol') or ''} {c.get('description') or ''}".lower()
        if re.search(r"\b(solana\.ai|agent|mcp|pay\.sh|autonom)\b", txt_full):
            ext_event = "SOLANA_AI_AGENT_INFRA_ROLLOUT_NOV2026"
        elif re.search(r"\b(polymarket|predict|bet|odds)\b", txt_full):
            ext_event = "PUMPFUN_POLYMARKET_INTEGRATION_NOV2026"
        elif re.search(r"\b(mayhem)\b", txt_full):
            ext_event = "PUMPFUN_MAYHEM_MODE_META"
        elif re.search(r"\b(privy|login|wallet|karpeles)\b", txt_full):
            ext_event = "PUMPFUN_PRIVY_WALLET_CONTROVERSY_NOV2026"
        elif re.search(r"\b(sui)\b", txt_full):
            ext_event = "PUMPFUN_SUI_MULTICHAIN_EXPANSION_NOV2026"

        social_rows.append({
            "mint": m,
            "name": (c.get("name") or "").strip(),
            "symbol": (c.get("symbol") or "").strip(),
            "cohort_role": role,
            "has_twitter_at_launch": int(bool(tw_url)),
            "twitter_link_type": tw_type,
            "has_website_at_launch": int(bool(c.get("website"))),
            "dexscreener_socials_count": len(ds_socials),
            "dexscreener_active_boosts": ds_boosts,
            "narrative_category": narr_cat,
            "external_event_alignment": ext_event,
            "meme_shareability_score": lex_m["meme_shareability_score"],
            "humor_irony_score": lex_m["humor_irony_score"],
            "controversy_score": lex_m["controversy_score"],
            "is_ticker_first_mover": copycat_info.get(m, {}).get("is_ticker_first_mover", 1),
            "reliable_multiple": reliable_mult,
            "unique_buyers_observed": len(buyers_seen),
            "historical_social_caveat": "Launch metadata (X/web URI) immutable in token init; historical X follower counts pre-pump unavailable publicly without look-ahead bias.",
        })

        utc_s, pl_s = fmt_ts(cts)
        ath_utc_s, ath_pl_s = fmt_ts(ath_bar_ts)

        tm_row = {
            "mint": m,
            "name": (c.get("name") or "").strip(),
            "symbol": (c.get("symbol") or "").strip(),
            "creator": creator,
            "cohort_role": role,
            "launch_utc": utc_s,
            "launch_warsaw": pl_s,
            "ath_utc": ath_utc_s,
            "ath_warsaw": ath_pl_s,
            "created_timestamp_ms": cts,
            "migrated_dex": int(bool(c.get("complete")) or bool(c.get("raydium_pool"))),
            "mayhem_enabled": mayhem_on,
            "narrative_category": narr_cat,
            "pump_profile": pump_profile,
            "first_reliable_price_usd": round(first_rel_price, 10),
            "max_reliable_price_usd": round(max_rel_price, 10),
            "initial_mcap_usd": init_mcap_usd,
            "max_mcap_usd": max_mcap_usd,
            "current_mcap_usd": round(cur_price_est * eff_supply_for_mcap, 2),
            "raw_single_tx_multiple": raw_single_tx_mult,
            "reliable_market_multiple": reliable_mult,
            "realizable_liquidity_adj_multiple": realizable_mult,
            "total_volume_usd": total_vol_usd,
            "liquidity_usd": round(liq_usd, 2),
            "time_to_ath_min": time_to_ath_min,
            "max_drawdown_from_ath_pct": max_dd_pct,
            "max_ret_1m_pct": max_ret_1m_pct,
            "max_ret_5m_pct": max_ret_5m_pct,
            "max_ret_15m_pct": max_ret_15m_pct,
            "max_ret_30m_pct": max_ret_30m_pct,
            "max_ret_1h_pct": max_ret_1h_pct,
            "max_ret_4h_pct": max_ret_4h_pct,
            "max_ret_24h_pct": max_ret_24h_pct,
            "stagnation_pump_flag": stagnation_pump_flag,
            "stagnation_hours": stagnation_hours,
            "multi_wave_flag": multi_wave_flag,
            "wave_count": wave_count,
            "unique_buyers_1m": buyers_1m,
            "unique_buyers_3m": buyers_3m,
            "unique_buyers_5m": buyers_5m,
            "unique_buyers_15m": buyers_15m,
            "unique_buyers_30m": buyers_30m,
            "unique_buyers_total_sampled": len(buyers_seen),
            "time_to_10_buyers_sec": t_10_buyers_sec,
            "time_to_50_buyers_sec": t_50_buyers_sec,
            "time_to_2x_sec": t_2x_sec,
            "time_to_5x_sec": t_5x_sec,
            "small_buy_share": small_buy_share,
            "medium_buy_share": med_buy_share,
            "large_buy_share": large_buy_share,
            "early10_avg_buy_usd": early_avg_buy_usd,
            "later_avg_buy_usd": later_avg_buy_usd,
            "scale_in_buyer_share": scale_in_buyer_share,
            "buy_sell_usd_ratio": buy_sell_usd_ratio,
            "fomo_onset_minute": fomo_onset_min,
            "fomo_transition_index": fomo_transition_index,
            "dip_absorption_ratio": dip_absorption_ratio,
            "first_major_sell_sec": first_major_sell_sec,
            "creator_dumped_flag": creator_dumped_flag,
            "bundle_wallets_count": len(bundle_wallets),
            "detected_clusters_count": len(clusters_this_token),
            "top10_holders_peak_pct": top10_peak,
            "potential_insiders_peak_pct": insider_supply_peak,
            "potential_insiders_retained_pct": insider_supply_now,
            "insider_supply_risk_score": insider_risk_score,
            "manipulation_risk_score": manipulation_risk_score,
            "sol_price_at_launch": sol_p,
            "sol_ret_24h_at_launch_pct": sol_ctx["sol_ret_24h_pct"],
            "hit_2x": int(reliable_mult >= 2.0),
            "hit_3x": int(reliable_mult >= 3.0),
            "hit_5x": int(reliable_mult >= 5.0),
            "hit_10x": int(reliable_mult >= 10.0),
            "hit_20x": int(reliable_mult >= 20.0),
            "hit_50x": int(reliable_mult >= 50.0),
            "hit_100x": int(reliable_mult >= 100.0),
        }
        token_metrics_rows.append(tm_row)

        if reliable_mult >= 2.0 and max_mcap_usd >= 7500:
            pump_events_rows.append(dict(tm_row))

    # --------------------------------------------------------------------------
    # D. BUILD RANKINGS ON PUMP_EVENTS & TOP_100_PUMPS
    # --------------------------------------------------------------------------
    df_pumps = pd.DataFrame(pump_events_rows)
    if len(df_pumps) > 0:
        df_pumps["rank_A_pct_gain"] = df_pumps["reliable_market_multiple"].rank(ascending=False, method="min").astype(int)
        df_pumps["rank_B_fastest_5m"] = df_pumps["max_ret_5m_pct"].rank(ascending=False, method="min").astype(int)
        df_pumps["rank_B_fastest_1h"] = df_pumps["max_ret_1h_pct"].rank(ascending=False, method="min").astype(int)
        df_pumps["mcap_gain_usd"] = (df_pumps["max_mcap_usd"] - df_pumps["initial_mcap_usd"]).round(2)
        df_pumps["rank_C_mcap_gain"] = df_pumps["mcap_gain_usd"].rank(ascending=False, method="min").astype(int)
        df_pumps = df_pumps.sort_values("reliable_market_multiple", ascending=False).reset_index(drop=True)
    df_top100 = df_pumps.head(100).copy()

    # --------------------------------------------------------------------------
    # E. BUILD MATCHED CONTROL_GROUP.CSV (Section 15)
    # --------------------------------------------------------------------------
    tm_by_mint = {r["mint"]: r for r in token_metrics_rows}
    control_rows = []
    for cmint, match_meta in control_matches.items():
        cr = tm_by_mint.get(cmint)
        pr = tm_by_mint.get(match_meta["matched_to_pump_mint"])
        if not cr or not pr:
            continue
        # Classify why control failed despite matching launch window
        if cr["unique_buyers_5m"] <= 2:
            fail_mode = "COLD_START_NO_ORGANIC_BUYERS"
        elif cr["creator_dumped_flag"] == 1 or cr["max_drawdown_from_ath_pct"] >= 85:
            fail_mode = "EARLY_DEV_OR_SNIPER_EXTRACTION"
        elif cr["unique_buyers_5m"] >= 6 and cr["fomo_transition_index"] < 35:
            fail_mode = "PROMISING_START_FAILED_FOMO_IGNITION"
        else:
            fail_mode = "LOW_VOLUME_ATTRITION"

        control_rows.append({
            "control_mint": cmint,
            "control_symbol": cr["symbol"],
            "control_launch_utc": cr["launch_utc"],
            "matched_pump_mint": pr["mint"],
            "matched_pump_symbol": pr["symbol"],
            "time_diff_minutes": match_meta["time_diff_minutes"],
            "sol_price_at_launch": cr["sol_price_at_launch"],
            "control_initial_mcap_usd": cr["initial_mcap_usd"],
            "pump_initial_mcap_usd": pr["initial_mcap_usd"],
            "control_reliable_multiple": cr["reliable_market_multiple"],
            "pump_reliable_multiple": pr["reliable_market_multiple"],
            "control_buyers_5m": cr["unique_buyers_5m"],
            "pump_buyers_5m": pr["unique_buyers_5m"],
            "control_buy_sell_ratio": cr["buy_sell_usd_ratio"],
            "pump_buy_sell_ratio": pr["buy_sell_usd_ratio"],
            "control_fomo_index": cr["fomo_transition_index"],
            "pump_fomo_index": pr["fomo_transition_index"],
            "control_insider_risk": cr["insider_supply_risk_score"],
            "pump_insider_risk": pr["insider_supply_risk_score"],
            "failure_mechanism": fail_mode,
        })

    # --------------------------------------------------------------------------
    # F. BUILD SMART MONEY & WALLET_INTELLIGENCE.CSV (Section 8)
    # --------------------------------------------------------------------------
    wallet_intel_rows = []
    for w, parts in wallet_token_participations.items():
        n_tok = len(parts)
        total_spent = sum(p["sol_spent"] for p in parts)
        if n_tok < 2 and total_spent < 1.5:
            continue  # focus table on repeat participants & meaningful actors
        early_entries = sum(1 for p in parts if p["buyer_rank"] <= 25)
        pre_pump_entries = sum(1 for p in parts if p["buyer_rank"] <= 25 and p["is_pump"] == 1)
        mults_after = [p["token_reliable_mult"] for p in parts if p["buyer_rank"] <= 50]
        med_mult = round(float(np.median(mults_after)) if mults_after else 1.0, 3)
        mean_mult = round(float(np.mean(mults_after)) if mults_after else 1.0, 3)
        med_entry_s = round(float(np.median([p["entry_sec"] for p in parts])), 1)
        holds = [p["hold_min"] for p in parts if not np.isnan(p["hold_min"])]
        med_hold_m = round(float(np.median(holds)), 2) if holds else np.nan
        net_sol = round(sum(p["net_sol"] for p in parts), 4)
        losses = sum(1 for p in parts if p["is_pump"] == 0 and p["sol_spent"] > p["sol_recv"])

        # Supplement with live profile-api balance if available
        h_info = holdings_db.get(w, {})
        live_sol = round(float(h_info.get("native_sol") or 0.0), 4)

        # Participant taxonomy (Section 8: 1..10)
        if any(p["is_creator"] for p in parts):
            w_class = "6_CREATOR_WALLET"
        elif any(p["is_bundle"] for p in parts):
            w_class = "3_BUNDLE_BUYER"
        elif med_entry_s <= 4.0 and early_entries >= 2:
            w_class = "2_AUTOMATED_SNIPER"
        elif sum(p["tx_count"] for p in parts) >= 15 and n_tok >= 3:
            w_class = "4_HIGH_FREQ_TRADING_BOT"
        elif any(p["is_clustered"] for p in parts) and early_entries >= 1:
            w_class = "7_CREATOR_OR_CLUSTER_LINKED"
        elif pre_pump_entries >= 3 and med_mult >= 4.0:
            w_class = "5_EXPERIENCED_SMART_MONEY"
        elif early_entries >= 2:
            w_class = "1_REPEAT_EARLY_BUYER"
        elif net_sol >= 2.0:
            w_class = "10_PROFIT_REALIZER"
        elif total_spent / max(1, n_tok) < 0.35:
            w_class = "9_RETAIL_SMALL_INVESTOR"
        else:
            w_class = "8_LATE_MOMENTUM_BUYER"

        # Smart Money Score: explicitly requires >=3 tokens (never 1 lucky trade!)
        hit_rate = pre_pump_entries / max(1, early_entries) if early_entries > 0 else 0.0
        sm_score = 0.0
        if n_tok >= 3 and early_entries >= 2:
            sm_score = round(min(100.0, 35.0 * hit_rate + 25.0 * min(1.0, (n_tok - 2) / 6.0) + 25.0 * min(1.0, med_mult / 15.0) + 15.0 * (1.0 if net_sol > 0 else 0.3)), 2)

        wallet_intel_rows.append({
            "wallet": w,
            "participant_class": w_class,
            "tokens_analyzed": n_tok,
            "early_entries_top25": early_entries,
            "pre_pump_entries": pre_pump_entries,
            "pre_pump_hit_rate": round(hit_rate, 4),
            "median_max_multiple_after_entry": med_mult,
            "mean_max_multiple_after_entry": mean_mult,
            "median_entry_sec_from_launch": med_entry_s,
            "median_hold_time_min": med_hold_m,
            "observed_net_sol_flow": net_sol,
            "losing_or_failed_entries": losses,
            "live_wallet_sol_balance": live_sol,
            "smart_money_score": sm_score,
        })

    df_wallets = pd.DataFrame(wallet_intel_rows).sort_values(["smart_money_score", "pre_pump_entries", "tokens_analyzed"], ascending=False)

    # --------------------------------------------------------------------------
    # G. BUILD CREATOR_ANALYSIS.CSV (Section 10)
    # --------------------------------------------------------------------------
    creator_rows = []
    cohort_by_creator = defaultdict(list)
    for r in token_metrics_rows:
        if r["creator"]:
            cohort_by_creator[r["creator"]].append(r)

    for cr, c_info in creator_db.items():
        tot_cnt = int(c_info.get("total_created_count") or c_info.get("sampled_coins_count") or 1)
        briefs = c_info.get("coins_brief") or []
        mig_cnt = int(c_info.get("migrated_count") if "migrated_count" in c_info else sum(1 for m_id in c_info.get("coin_mints", []) if coins_by_mint.get(m_id, {}).get("complete")))
        aths = [float(b.get("ath_market_cap") or 0) for b in briefs] if briefs else [float(coins_by_mint.get(mid, {}).get("ath_market_cap") or 0) for mid in c_info.get("coin_mints", [])]
        max_ath = round(max(aths) if aths else 0.0, 2)
        med_ath = round(float(np.median(aths)) if aths else 0.0, 2)
        pumps_over_25k = sum(1 for a in aths if a >= 25000)

        # Launch hour preference & naming reuse
        hrs = [datetime.fromtimestamp(int(b["created_timestamp"]) / 1000.0, tz=timezone.utc).hour for b in briefs if b.get("created_timestamp")]
        pref_hr = int(Counter(hrs).most_common(1)[0][0]) if hrs else np.nan
        syms = [str(b.get("symbol") or "").lower().strip() for b in briefs if b.get("symbol")]
        dup_sym_rate = round(1.0 - (len(set(syms)) / max(1, len(syms))), 3) if len(syms) >= 2 else 0.0

        c_cohort = cohort_by_creator.get(cr, [])
        dumped_any = int(any(x["creator_dumped_flag"] == 1 for x in c_cohort))
        clustered_any = int(any(x["detected_clusters_count"] >= 1 for x in c_cohort))

        if tot_cnt >= 10 and mig_cnt == 0:
            cr_type = "SPAM_SERIAL_DEPLOYER"
        elif tot_cnt >= 3 and pumps_over_25k >= 2 and mig_cnt >= 2:
            cr_type = "REPEAT_SUCCESSFUL_OPERATOR"
        elif tot_cnt >= 3 and dumped_any == 1 and mig_cnt <= 1:
            cr_type = "SERIAL_EXTRACTOR_RUGGER"
        elif tot_cnt >= 2 and pumps_over_25k == 1:
            cr_type = "ONE_HIT_WONDER_MULTI_TRY"
        elif tot_cnt == 1 and max_ath >= 25000:
            cr_type = "SINGLE_LAUNCH_WINNER"
        else:
            cr_type = "ONE_OFF_OR_SMALL_CREATOR"

        creator_rows.append({
            "creator_wallet": cr,
            "total_tokens_created": tot_cnt,
            "sampled_tokens_analyzed": max(len(aths), 1),
            "migrated_tokens_count": mig_cnt,
            "migration_rate_pct": round((mig_cnt / max(1, tot_cnt)) * 100.0, 2),
            "pumps_over_25k_mcap": pumps_over_25k,
            "max_historical_ath_usd": max_ath,
            "median_ath_usd": med_ath,
            "preferred_launch_hour_utc": pref_hr,
            "duplicate_ticker_reuse_rate": dup_sym_rate,
            "linked_cluster_observed": clustered_any,
            "creator_early_dump_observed": dumped_any,
            "creator_archetype": cr_type,
        })

    # --------------------------------------------------------------------------
    # H. SAVE ALL 14 CORE CSV DATASETS
    # --------------------------------------------------------------------------
    datasets = {
        "ALL_TOKENS.csv": pd.DataFrame(all_tokens_rows),
        "PUMP_EVENTS.csv": df_pumps,
        "TOP_100_PUMPS.csv": df_top100,
        "TOKEN_METRICS.csv": pd.DataFrame(token_metrics_rows),
        "CONTROL_GROUP.csv": pd.DataFrame(control_rows),
        "WALLET_INTELLIGENCE.csv": df_wallets,
        "WALLET_CLUSTERS.csv": pd.DataFrame(wallet_clusters_rows),
        "SUPPLY_CONCENTRATION.csv": pd.DataFrame(supply_conc_rows),
        "INSIDER_PROFIT_ANALYSIS.csv": pd.DataFrame(insider_profit_rows),
        "INSIDER_RISK.csv": pd.DataFrame(insider_risk_rows),
        "CREATOR_ANALYSIS.csv": pd.DataFrame(creator_rows).sort_values(["pumps_over_25k_mcap", "max_historical_ath_usd"], ascending=False),
        "HOURLY_PATTERNS.csv": pd.DataFrame(hourly_rows),
        "NAME_ANALYSIS.csv": pd.DataFrame(name_analysis_rows),
        "SOCIAL_ANALYSIS.csv": pd.DataFrame(social_rows),
    }

    for fname, df in datasets.items():
        out_p = BASE_DIR / fname
        df.to_csv(out_p, index=False, encoding="utf-8-sig")
        logger.info(f"Wrote {fname}: {len(df)} rows × {len(df.columns)} cols")

if __name__ == "__main__":
    main()
