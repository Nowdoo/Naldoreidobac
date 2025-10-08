#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rei dos Dados — Ultra PRO (Railway Ready)
Ajustes para compatibilidade com Railway:
 - Chrome rodando em modo headless com opções corretas
 - Inclusão de heartbeat HTTP opcional (mantém o container vivo)
 - Melhoria na reinicialização do driver
"""

import time, os, traceback, requests, json, re, threading
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from bs4 import BeautifulSoup
import chromedriver_autoinstaller
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from flask import Flask

# ---------------- KEEP-ALIVE (Railway mata container se não escutar porta) ----------------
app = Flask(__name__)

@app.route("/")
def home():
    return "🤖 Rei dos Dados está rodando!"

def start_keep_alive():
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=port), daemon=True).start()

# ---------------- AUTORIZAÇÃO ----------------
ALLOWED_USERS = ["1185534823"]

def is_authorized(chat_id):
    return str(chat_id) in ALLOWED_USERS

# ---------------- CONFIGURAÇÃO ----------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8044483200:AAE88Yih3IDKSq3bMe0jc0kaD_30UQTmDnY")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1185534823")
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
            r = requests.post(url, data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=10)
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

# ---------------- DRIVER (Corrigido p/ Railway) ----------------
def make_driver():
    chromedriver_path = chromedriver_autoinstaller.install()
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")

    for candidate in ("/usr/bin/chromium-browser", "/usr/bin/chromium", "/usr/bin/google-chrome-stable"):
        if os.path.exists(candidate):
            options.binary_location = candidate
            print("✅ Usando navegador:", candidate)
            break

    try:
        driver = webdriver.Chrome(service=Service(chromedriver_path), options=options)
        driver.set_page_load_timeout(30)
        print("✅ ChromeDriver iniciado com sucesso.")
        return driver
    except Exception as e:
        print("❌ Erro ao iniciar ChromeDriver:", e)
        traceback.print_exc()
        raise

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

# ---------------- RESTANTE DO BOT ----------------
# (mantém o restante do seu código original sem alterações)
# Copie o restante do arquivo a partir da função `scrape_history(...)`
# até o final, exatamente como estava.

if __name__ == "__main__":
    start_keep_alive()  # <-- mantém o container Railway ativo
    from rei_dados_ultra_pro import run_bot  # se o código estiver em outro arquivo, importe aqui
    run_bot()
