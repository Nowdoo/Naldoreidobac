
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rei dos Dados — Ultra PRO (corrigido)
Correções principais:
 - funções de modelo agora aceitam histórico (lista de dicts) ou lista de strings
 - latest_id agora usa timestamp + order + trecho raw para detectar rounds
 - debug/impressão das probabilidades quando nenhum sinal válido
 - fallback no scraper para tentar encontrar entradas mesmo que classes tenham mudado
"""

import time, os, traceback, requests, json, re
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from bs4 import BeautifulSoup
import chromedriver_autoinstaller
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

# ---------------- AUTORIZAÇÃO ----------------
ALLOWED_USERS = ["1185534823"]  # IDs autorizados

def is_authorized(chat_id):
    return str(chat_id) in ALLOWED_USERS

# ---------------- CONFIGURAÇÃO ----------------
TELEGRAM_TOKEN = "8044483200:AAE88Yih3IDKSq3bMe0jc0kaD_30UQTmDnY"
TELEGRAM_CHAT_ID = "1185534823"
SCRAPE_URL = "https://www.tipminer.com/br/historico/evolution/bac-bo"

WINDOW_1, WINDOW_2 = 40, 120
CONF_THRESHOLD_BASE = 0.05
SLEEP_INTERVAL = 5
DRIVER_RESTART_ATTEMPTS = 4
DRIVER_RESTART_WAIT = 3

OPERATION_MODE = "equilibrado"
MODE_SETTINGS = {
    "conservador": {"min_conf": 0.06, "surf_tolerance": 3, "sniper_multiplier": 1.5},
    "equilibrado": {"min_conf": 0.045, "surf_tolerance": 4, "sniper_multiplier": 1.0},
    "agressivo": {"min_conf": 0.035, "surf_tolerance": 6, "sniper_multiplier": 0.8}
}
MODE = MODE_SETTINGS.get(OPERATION_MODE, MODE_SETTINGS["equilibrado"])
PERSIST_FILE = "rei_dados_state.json"
DEBUG = True

LABELS = {
    "strong": 0.10,
    "moderate": 0.06,
    "weak": 0.00
}

# ---------------- TELEGRAM ----------------
def safe_send_telegram(text, retries=5, delay=2, chat_id=TELEGRAM_CHAT_ID):
    if not is_authorized(chat_id):
        print(f"⚠️ Bloqueado: ID {chat_id} não autorizado.")
        return False
    for attempt in range(1, retries + 1):
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            r = requests.post(url, data={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML"
            }, timeout=10)
            if r.status_code == 200:
                print(f"Telegram OK (tentativa {attempt})")
                return True
            else:
                print(f"Erro Telegram ({r.status_code}): {r.text[:150]}")
        except Exception as e:
            print(f"Falha Telegram (tentativa {attempt}): {e}")
        time.sleep(delay * attempt)
    print("❌ Falha permanente no envio ao Telegram.")
    return False

send_telegram = safe_send_telegram

def send_score(score, chat_id=TELEGRAM_CHAT_ID):
    msg = (f"📊 Score Atual:\n"
           f"🟢 GREENs: {score.get('green', 0)}\n"
           f"🔴 REDs: {score.get('red', 0)}\n"
           f"⚪ TIEs: {score.get('tie', 0)}")
    send_telegram(msg, chat_id=chat_id)

# ---------------- DRIVER ----------------
def make_driver():
    chromedriver_path = chromedriver_autoinstaller.install()
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")

    for candidate in (
        "/usr/bin/chromium-browser", "/usr/bin/chromium",
        "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable"
    ):
        if os.path.exists(candidate):
            options.binary_location = candidate
            print("Usando navegador em:", candidate)
            break

    driver = webdriver.Chrome(service=Service(chromedriver_path), options=options)
    driver.set_page_load_timeout(30)
    return driver

def restart_driver(old_driver=None):
    if old_driver:
        try:
            old_driver.quit()
        except:
            pass
    for i in range(1, DRIVER_RESTART_ATTEMPTS + 1):
        try:
            print(f"♻️ Tentando reiniciar driver ({i}/{DRIVER_RESTART_ATTEMPTS})...")
            d = make_driver()
            send_telegram(f"♻️ Driver reiniciado com sucesso ({i}/{DRIVER_RESTART_ATTEMPTS}).")
            return d
        except Exception as e:
            print(f"Falha ao reiniciar driver ({i}): {e}")
            traceback.print_exc()
            time.sleep(DRIVER_RESTART_WAIT * i)
    send_telegram("❌ Falha ao reiniciar driver após várias tentativas.")
    raise RuntimeError("Não foi possível reiniciar o driver.")

def is_driver_alive(driver):
    try:
        _ = driver.current_url
        return True
    except Exception:
        return False

# ---------------- SCRAPE ----------------
def scrape_history(driver, max_items=300):
    try:
        driver.get(SCRAPE_URL)
        time.sleep(4)
        soup = BeautifulSoup(driver.page_source, "html.parser")
        text = soup.get_text(" ", strip=True)
        # Checagem básica
        if "Evolution Bac Bo" not in text and "Bac Bo" not in text and "BAC-BO" not in text.upper():
            print("⚠️ Página aparentemente não carregada corretamente (checagem textual).")
            # mas tentamos mesmo assim prosseguir com buscas alternativas

        raw_els = soup.select("[class*='bg-cell-']")
        items = []
        # tentativa com as classes originais
        if raw_els:
            for idx, el in enumerate(raw_els):
                title = (el.get("title") or "").upper()
                txt = el.get_text(" ", strip=True).upper()
                if "PLAYER" in title or "PLAYER" in txt:
                    typ = "PLAYER"
                elif "BANKER" in title or "BANKER" in txt:
                    typ = "BANKER"
                elif "TIE" in title or "EMPATE" in title or "EMPATE" in txt or "TIE" in txt:
                    typ = "TIE"
                else:
                    continue
                # tentar extrair horário
                m = re.search(r"(\d{2}:\d{2})", title)
                ts = m.group(1) if m else None
                items.append({"type": typ, "timestamp": ts, "raw": el.get_text(" ", strip=True), "order": idx})
                if len(items) >= max_items:
                    break
        else:
            # fallback: procurar por palavras PLAYER/BANKER/TIE no HTML
            cand_texts = re.findall(r"([A-Za-z]{3,20}.*?)\s*(\d{2}:\d{2})?", soup.get_text(" ", strip=True))
            # essa busca pode gerar ruído, então fazemos varredura simples
            flat = soup.get_text(" ", strip=True).upper().split()
            # tentaremos encontrar sequências 'PLAYER' ou 'BANKER' próximas de timestamps
            possible = []
            for i, tok in enumerate(flat):
                if tok in ("PLAYER", "BANKER", "TIE", "EMPATE"):
                    # pega janela ao redor pra criar um raw
                    left = max(0, i - 6)
                    right = min(len(flat), i + 6)
                    raw = " ".join(flat[left:right])
                    # tenta timestamp na vizinhança
                    ts_match = re.search(r"(\d{2}:\d{2})", raw)
                    ts = ts_match.group(1) if ts_match else None
                    typ = "TIE" if tok in ("TIE", "EMPATE") else ("PLAYER" if tok == "PLAYER" else "BANKER")
                    possible.append({"type": typ, "timestamp": ts, "raw": raw, "order": i})
                    if len(possible) >= max_items:
                        break
            items = possible

        # dedupe por (type, timestamp, prefix raw)
        uniq = []
        seen = set()
        for r in items:
            raw_prefix = (r.get("raw") or "")[:40]
            k = (r.get("type"), r.get("timestamp"), raw_prefix)
            if k not in seen:
                seen.add(k)
                uniq.append(r)

        # filtrar sem timestamp é OK, mas preferimos os com timestamp para ordenação
        def ordenar_por_timestamp(item):
            try:
                if not item.get("timestamp"):
                    return -1
                h, m = map(int, item["timestamp"].split(":"))
                return h * 60 + m
            except:
                return -1

        # manter só com timestamp se houver muitos itens sem timestamp
        uniq.sort(key=ordenar_por_timestamp, reverse=True)
        # limitar max_items
        return uniq[:max_items]
    except Exception as e:
        print("Erro scrape_history:", e)
        traceback.print_exc()
        return []

# ---------------- PERSISTÊNCIA ----------------
def load_state():
    default = {
        "score": {"green": 0, "red": 0, "tie": 0},
        "weights": {"markov1": 0.5, "markov2": 0.5, "freq": 0.0},
        "history_signals": []
    }
    if os.path.exists(PERSIST_FILE):
        try:
            with open(PERSIST_FILE, "r") as f:
                data = json.load(f)
                for k in default:
                    if k not in data:
                        data[k] = default[k]
                return data
        except Exception:
            return default
    else:
        return default

def save_state(state):
    try:
        with open(PERSIST_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        print("Erro ao salvar estado:", e)

# ---------------- MODELOS ----------------
def _normalize_seq_input(seq):
    """
    Aceita:
     - lista de strings (PLAYER/BANKER/TIE)
     - lista de dicts com key 'type'
    Retorna lista de strings ('PLAYER'/'BANKER'/'TIE')
    """
    out = []
    for s in seq:
        if isinstance(s, dict):
            t = s.get("type") or s.get("result") or s.get("raw")
            if isinstance(t, str):
                t_up = t.strip().upper()
                if "PLAYER" in t_up:
                    out.append("PLAYER")
                elif "BANKER" in t_up:
                    out.append("BANKER")
                elif "TIE" in t_up or "EMPATE" in t_up:
                    out.append("TIE")
            continue
        if isinstance(s, str):
            s_up = s.strip().upper()
            if "PLAYER" in s_up:
                out.append("PLAYER")
            elif "BANKER" in s_up:
                out.append("BANKER")
            elif "TIE" in s_up or "EMPATE" in s_up:
                out.append("TIE")
    return out

def calc_markov1(seq, window=WINDOW_1, a=1.0):
    seq = _normalize_seq_input(seq)
    seq = [s for s in seq if s in ("PLAYER", "BANKER")]
    if not seq:
        return {"PLAYER": 0.5, "BANKER": 0.5}
    seq = seq[-window:]
    c = Counter(seq)
    tot = sum(c.values())
    return {k: (c.get(k, 0) + a) / (tot + a * 2) for k in ("PLAYER", "BANKER")}

def calc_markov2(seq, window=WINDOW_2, a=1.0):
    seq = _normalize_seq_input(seq)
    seq = [s for s in seq if s in ("PLAYER", "BANKER")]
    if len(seq) < 2:
        return {"PLAYER": 0.5, "BANKER": 0.5}
    seq = seq[-(window + 2):]
    pairs = defaultdict(Counter)
    # construir modelo de ordem 2 (pares -> próximo)
    for a1, a2, a3 in zip(seq, seq[1:], seq[2:]):
        pairs[(a1, a2)][a3] += 1
    last = (seq[-2], seq[-1])
    row = pairs.get(last, {})
    tot = sum(row.values())
    return {k: (row.get(k, 0) + a) / (tot + a * 2) for k in ("PLAYER", "BANKER")}

def calc_freq(seq, window=40, a=1.0):
    seq = _normalize_seq_input(seq)
    seq = [s for s in seq if s in ("PLAYER", "BANKER")]
    if not seq:
        return {"PLAYER": 0.5, "BANKER": 0.5}
    seq = seq[-window:]
    c = Counter(seq)
    tot = sum(c.values())
    return {k: (c.get(k, 0) + a) / (tot + a * 2) for k in ("PLAYER", "BANKER")}

# ---------------- ESTRATÉGIAS AUX ----------------
def detect_surf(seq, tolerance=4):
    seq = _normalize_seq_input(seq)
    seq = [s for s in seq if s in ("PLAYER", "BANKER")]
    if len(seq) < tolerance:
        return False, None, 0
    last = seq[-1]
    run = 1
    for s in reversed(seq[:-1]):
        if s == last:
            run += 1
        else:
            break
    return run >= tolerance, last, run

def adjust_weights(state):
    ws = state.get("weights", {"markov1": 0.5, "markov2": 0.5, "freq": 0.0})
    hist = state.get("history_signals", [])[-200:]
    if not hist:
        return ws
    score_by_model = {"m1": 0, "m2": 0, "f": 0}
    tot = 0
    for h in hist:
        res = h.get("result")
        if not res:
            continue
        tot += 1
        probs = {"m1": h.get("p_m1", 0), "m2": h.get("p_m2", 0), "f": h.get("p_f", 0)}
        best = max(probs, key=probs.get)
        if h.get("choice") == res:
            score_by_model[best] += 1
        else:
            score_by_model[best] -= 0.2
    if tot <= 0:
        return ws
    raw = [max(0.0, score_by_model["m1"]), max(0.0, score_by_model["m2"]), max(0.0, score_by_model["f"])]
    s = sum(raw)
    if s <= 0:
        return {"markov1": 0.5, "markov2": 0.5, "freq": 0.0}
    new_ws = {"markov1": raw[0] / s, "markov2": raw[1] / s, "freq": raw[2] / s}
    alpha = 0.25
    ws_final = {
        "markov1": ws["markov1"] * (1 - alpha) + new_ws["markov1"] * alpha,
        "markov2": ws["markov2"] * (1 - alpha) + new_ws["markov2"] * alpha,
        "freq": ws["freq"] * (1 - alpha) + new_ws["freq"] * alpha,
    }
    s2 = ws_final["markov1"] + ws_final["markov2"] + ws_final["freq"]
    if s2 <= 0:
        return {"markov1": 0.5, "markov2": 0.5, "freq": 0.0}
    for k in ws_final:
        ws_final[k] /= s2
    return ws_final

def pick_action(hist_chrono, state):
    # hist_chrono chega como lista de dicts (cada item com 'type' etc)
    if len(hist_chrono) < 2:
        return None, {}, 0.0, {}

    # construir seq apenas com tipos (strings)
    seq_types = _normalize_seq_input(hist_chrono)

    weights = state.get("weights", {"markov1": 0.5, "markov2": 0.5, "freq": 0.0})
    min_conf = MODE.get("min_conf", CONF_THRESHOLD_BASE)
    surf_tolerance = MODE.get("surf_tolerance", 4)
    sniper_multiplier = MODE.get("sniper_multiplier", 1.0)

    p_m1 = calc_markov1(seq_types)
    p_m2 = calc_markov2(seq_types)
    p_f = calc_freq(seq_types)

    p_combined = combine_probs_ensemble(p_m1, p_m2, p_f, weights)

    is_surf, surf_type, surf_len = detect_surf(seq_types)

    pick = None
    p = {}
    conf = 0.0
    meta = {}

    # Estratégia 1: Surf (Prioridade Alta)
    if is_surf:
        pick = surf_type
        p = p_combined
        conf = abs(p_combined.get(pick, 0.5) - 0.5) * 2  # Confiança baseada na probabilidade combinada
        meta = {
            "strategy": "surf",
            "surf": {"type": surf_type, "len": surf_len, "tolerance": surf_tolerance},
            "p_m1": p_m1.get(pick), "p_m2": p_m2.get(pick), "p_f": p_f.get(pick),
            "diff": conf, "conf_threshold": min_conf,
            "weights": weights
        }
        if conf >= min_conf * sniper_multiplier:  # Multiplicador para entrada mais "agressiva" no surf
            print(f"Sinal Surf: {pick} (Conf: {conf:.3f})")
            return pick, p, conf, meta

    # Estratégia 2: Sniper (Baseado na maior probabilidade combinada)
    sorted_picks = sorted(p_combined, key=p_combined.get, reverse=True)
    best_pick = sorted_picks[0]
    second_pick = sorted_picks[1]

    conf_sniper = abs(p_combined.get(best_pick, 0.5) - 0.5) * 2

    if conf_sniper >= min_conf:
        pick = best_pick
        p = p_combined
        conf = conf_sniper
        meta = {
            "strategy": "sniper",
            "p_m1": p_m1.get(pick), "p_m2": p_m2.get(pick), "p_f": p_f.get(pick),
            "diff": conf, "conf_threshold": min_conf,
            "weights": weights,
            "secondary": second_pick if abs(p_combined.get(second_pick, 0.5) - 0.5) * 2 >= min_conf * 0.5 else None
        }
        print(f"Sinal Sniper: {pick} (Conf: {conf:.3f})")
        return pick, p, conf, meta

    # Nenhum sinal válido -> DEBUG output para entender porque
    if DEBUG:
        debug_msg = (
            f"Nenhum sinal válido (diff {conf_sniper:.3f} < min {min_conf}). Probabilidades:\n"
            f"COMBINED -> PLAYER: {p_combined.get('PLAYER',0):.3f} | BANKER: {p_combined.get('BANKER',0):.3f}\n"
            f"M1 -> PLAYER: {p_m1.get('PLAYER',0):.3f} | BANKER: {p_m1.get('BANKER',0):.3f}\n"
            f"M2 -> PLAYER: {p_m2.get('PLAYER',0):.3f} | BANKER: {p_m2.get('BANKER',0):.3f}\n"
            f"FREQ-> PLAYER: {p_f.get('PLAYER',0):.3f} | BANKER: {p_f.get('BANKER',0):.3f}\n"
            f"Weights: {weights}\n"
            f"Últimos 10 (cronológico): {[ (h.get('timestamp'), h.get('type')) for h in hist_chrono[-10:]]}"
        )
        print(debug_msg)
    return None, p_combined, conf_sniper, {"p_m1": p_m1.get(best_pick), "p_m2": p_m2.get(best_pick), "p_f": p_f.get(best_pick), "diff": conf_sniper, "conf_threshold": min_conf, "weights": weights}

def combine_probs_ensemble(p1, p2, pf, weights):
    w1 = weights.get("markov1", 0.5)
    w2 = weights.get("markov2", 0.5)
    wf = weights.get("freq", 0.0)
    p = {
        "PLAYER": w1 * p1.get("PLAYER", 0.5) + w2 * p2.get("PLAYER", 0.5) + wf * pf.get("PLAYER", 0.5),
        "BANKER": w1 * p1.get("BANKER", 0.5) + w2 * p2.get("BANKER", 0.5) + wf * pf.get("BANKER", 0.5)
    }
    s = p["PLAYER"] + p["BANKER"]
    if s > 0:
        p["PLAYER"] /= s
        p["BANKER"] /= s
    return p

# ---------------- LOOP PRINCIPAL ----------------
def run_bot():
    print("▶️ Iniciando Rei dos Dados — Ultra PRO (corrigido)")
    state = load_state()
    try:
        driver = make_driver()
    except Exception:
        driver = restart_driver(None)

    send_telegram("<b>🤖 O Rei dos Dados acordou — Modo: Equilibrado</b>")

    last_id = None
    bot_state = {"status": "searching", "signal": None}
    score = state.get("score", {"green": 0, "red": 0, "tie": 0})

    while True:
        try:
            if not is_driver_alive(driver):
                send_telegram("⚠️ Driver desconectado. Reiniciando...")
                driver = restart_driver(driver)
                time.sleep(1)
                continue

            hist = scrape_history(driver)
        except Exception as e:
            print("Erro crítico no loop:", e)
            traceback.print_exc()
            driver = restart_driver(driver)
            continue

        hist = [h for h in hist if h.get("type")]
        if not hist:
            if DEBUG:
                print("Scraper retornou histórico vazio. Aguardando...")
            time.sleep(SLEEP_INTERVAL)
            continue

        latest = hist[0]
        # construir latest_id mais robusto
        latest_id = f"{latest.get('timestamp')}_{latest.get('order')}_{(latest.get('raw') or '')[:30]}"
        new_round = latest_id != last_id
        if new_round:
            last_id = latest_id
            print("Novo round detectado:", latest)

        hist_chrono = list(reversed(hist))  # cronológico do mais antigo ao mais novo
        state["weights"] = adjust_weights(state)
        save_state(state)

        if bot_state["status"] == "searching" and new_round:
            pick, p, conf, meta = pick_action(hist_chrono, state)
            
            # <<< INÍCIO DA MODIFICAÇÃO >>>
            if pick:
                hora_analise = datetime.now().strftime("%H:%M")
                hora_entrada = (datetime.now() + timedelta(minutes=1)).strftime("%H:%M")
                
                # Lógica para definir os ícones e textos
                is_strong = conf >= LABELS["strong"]
                
                if is_strong:
                    strength_text = "forte"
                    strength_icon = "💪"
                    confidence_label = f"({strength_icon} Forte)"
                else: # Inclui moderado e fraco
                    strength_text = "fraco"
                    strength_icon = "📉"
                    confidence_label = f"({strength_icon} Fraco)"

                if pick == "PLAYER":
                    pick_icon = "🎲🔵"
                else: # BANKER
                    pick_icon = "🎲🔴"

                # Montagem da mensagem final com a nova lógica
                msg = (f"👑 O Rei dos Dados fala:\n"
                       f"🎯 Aposte no {pick_icon}, tá {strength_text} {strength_icon}\n"
                       f"PLAYER: {p['PLAYER']:.2f} | BANKER: {p['BANKER']:.2f}\n"
                       f"💥 Confiança: {conf:.3f} {confidence_label}\n"
                       f"🕒 Detectado: {hora_analise} | Entrar: {hora_entrada}")
                
                if meta.get("secondary"):
                    msg += f"\n⚪ Sugestão secundária: {meta['secondary']}"
                
                send_telegram(msg)
            # <<< FIM DA MODIFICAÇÃO >>>

                sig_record = {
                    "time": datetime.now().isoformat(),
                    "choice": pick,
                    "p_m1": meta.get("p_m1"),
                    "p_m2": meta.get("p_m2"),
                    "p_f": meta.get("p_f"),
                    "prob_choice": p.get(pick),
                    "diff": meta.get("diff"),
                    "conf_threshold": meta.get("conf_threshold"),
                    "surf": meta.get("surf"),
                    "tie_count": meta.get("tie_count"),
                    "result": None
                }
                state.setdefault("history_signals", []).append(sig_record)
                save_state(state)

                bot_state = {"status": "apostando", "signal": {"aposta": pick, "p": p, "conf": conf, "tentativa": 1, "meta_idx": len(state["history_signals"]) - 1}}
            else:
                # Debug já impresso dentro de pick_action
                if DEBUG:
                    print(f"Nenhum sinal válido (diff {conf:.3f}).")
                # sem sinal -> continuar buscando
        elif bot_state["status"] == "apostando" and new_round:
            result = latest["type"]
            sig = bot_state["signal"]
            aposta = sig["aposta"]
            tentativa = sig["tentativa"]

            meta_idx = sig.get("meta_idx")
            if meta_idx is not None and meta_idx < len(state.get("history_signals", [])):
                if state["history_signals"][meta_idx].get("result") is None:
                    state["history_signals"][meta_idx]["result"] = result
                    save_state(state)

            if result == "TIE":
                score["tie"] += 1
                score["green"] += 1
                send_telegram("⚪ Empate detectado — <b>contabilizado como GREEN!</b>")
                send_score(score)
                bot_state = {"status": "searching", "signal": None}
                state["weights"] = adjust_weights(state)
                save_state(state)
                continue

            if result == aposta:
                score["green"] += 1
                if tentativa == 1:
                    send_telegram(f"🤑 O Rei sorri: GREEN direto! (Tentativa {tentativa}) — Resultado: {result}")
                else:
                    send_telegram(f"🤑 Recuperou no Gale! GREEN (Tentativa {tentativa}) — Resultado: {result}")
                send_score(score)
                bot_state = {"status": "searching", "signal": None}
                state["weights"] = adjust_weights(state)
                save_state(state)
            else:
                tentativa += 1
                sig["tentativa"] = tentativa
                if tentativa == 2:
                    send_telegram(f"⚠️ RED na 1ª tentativa — Fazer Gale 1 (tentativa {tentativa}) em {aposta}")
                    bot_state["signal"] = sig
                elif tentativa == 3:
                    send_telegram(f"⚠️ RED na 2ª tentativa — Fazer Gale 2 (tentativa {tentativa}) em {aposta}")
                    bot_state["signal"] = sig
                elif tentativa >= 4:
                    score["red"] += 1
                    send_telegram(f"❌ RED final! (Tentativa {tentativa - 1}) — Resultado: {result}")
                    send_score(score)
                    bot_state = {"status": "searching", "signal": None}
                    state["weights"] = adjust_weights(state)
                    save_state(state)

        state["score"] = score
        save_state(state)
        time.sleep(SLEEP_INTERVAL)

# ---------------- EXECUÇÃO ----------------
if __name__ == "__main__":
    run_bot()
