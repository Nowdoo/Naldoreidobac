#!/        return False
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
