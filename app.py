from flask import Flask, render_template, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import os
import glob
import pandas as pd
import requests
from datetime import datetime, timedelta

# === CONFIG ===
LOGIN_URL = "http://qcws.cikbusiness.com/"
USERNAME = "BCTran"
PASSWORD = "Aewr7848#"

# Where Chrome will download files
DOWNLOAD_DIR = os.path.dirname(os.path.abspath(__file__))

# Flask app
app = Flask(__name__)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/run_automation", methods=["POST"])
def run_automation():
    print("== Starting Selenium automation v5.0 ==")

    chrome_options = Options()
    chrome_options.add_experimental_option("prefs", {
        "download.default_directory": DOWNLOAD_DIR,
        "download.prompt_for_download": False,
        "directory_upgrade": True,
        "safebrowsing.enabled": True
    })
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--remote-debugging-port=9222")
    chrome_options.add_argument("--disable-software-rasterizer")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137 Safari/537.36")

    driver = webdriver.Chrome(executable_path="/usr/bin/chromedriver", options=chrome_options)

    try:
        wait = WebDriverWait(driver, 15)
        driver.get(LOGIN_URL)
        time.sleep(2)

        driver.find_element(By.ID, "username").send_keys(USERNAME)
        driver.find_element(By.ID, "password").send_keys(PASSWORD)
        driver.find_element(By.CLASS_NAME, "login-form-button").click()

        wait.until(EC.presence_of_element_located((By.LINK_TEXT, "Activity Log")))
        driver.find_element(By.LINK_TEXT, "Activity Log").click()
        time.sleep(3)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))

        export_link_elem = driver.find_element(By.XPATH, "//a[contains(@href, '/api/report/cdr')]")
        export_link = export_link_elem.get_attribute("href")

        session = requests.Session()
        for cookie in driver.get_cookies():
            session.cookies.set(cookie['name'], cookie['value'])

        csv_response = session.get(export_link)
        if csv_response.status_code == 200:
            with open('export.csv', 'wb') as f:
                f.write(csv_response.content)

            print("✅ export.csv downloaded successfully.")
        else:
            print("❌ CSV download failed:", csv_response.status_code)

        time.sleep(5)
        # Use the directory where app.py is located
        project_dir = os.path.dirname(os.path.abspath(__file__))
        csv_path = os.path.join(project_dir, "export.csv")

        print(f"✅ Looking for CSV at: {csv_path}")

        # Check if the file exists
        if not os.path.exists(csv_path):
            driver.quit()
            return jsonify({"error": f"No CSV file found in {project_dir}."})


        df = pd.read_csv(csv_path, encoding='utf-8-sig', skip_blank_lines=True)
        df.columns = df.columns.str.strip().str.lower()

        print("Cleaned CSV columns:", df.columns.tolist())

        required = {'start', 'end', 'from', 'to', 'direction', 'endpoint'}
        if not required.issubset(set(df.columns)):
            raise ValueError(f"Missing required columns. Found: {df.columns.tolist()}")

        df['start'] = pd.to_datetime(df['start'])
        df['end'] = pd.to_datetime(df['end'])

        now = pd.Timestamp.now(tz='UTC')
        today_start = now.normalize()
        last_7_days_start = now - pd.Timedelta(days=7)

        df_today = df[df['start'] >= today_start]
        df_last7 = df[df['start'] >= last_7_days_start]
        # === LAST 7 DAYS stats
        df_last7_inbound = df_last7[df_last7['direction'] == 'inbound'].copy()
        df_last7_outbound = df_last7[df_last7['direction'] == 'outbound'].copy()

        last7_vm = df_last7_inbound[df_last7_inbound['endpoint'].astype(str).str.contains("VM")]
        last7_vm_count = len(last7_vm)

        last7_missed_raw = df_last7_inbound[
            df_last7_inbound["endpoint"].isna() |
            (df_last7_inbound["endpoint"].astype(str).str.strip() == "")
        ]

        last7_callback_needed = []
        for _, missed_row in last7_missed_raw.iterrows():
            missed_number = missed_row["from"]
            missed_time = missed_row["end"]
            was_called_back = df_last7_outbound[
                (df_last7_outbound["to"] == missed_number) &
                (df_last7_outbound["start"] > missed_time)
            ]
            if was_called_back.empty:
                last7_callback_needed.append(missed_number)

        real_missed_last7 = len(last7_callback_needed)
        real_calls_last7 = len(df_last7) - last7_vm_count
        pct_missed_last7 = (real_missed_last7 / real_calls_last7 * 100) if real_calls_last7 else 0


        # === TODAY stats
        total_today = len(df_today)
        df_today_inbound = df_today[df_today['direction'] == 'inbound'].copy()
        df_today_outbound = df_today[df_today['direction'] == 'outbound'].copy()

        today_vm = df_today_inbound[df_today_inbound['endpoint'].astype(str).str.contains("VM")]
        today_vm_count = len(today_vm)

        today_missed_raw = df_today_inbound[
            df_today_inbound["endpoint"].isna() |
            (df_today_inbound["endpoint"].astype(str).str.strip() == "")
        ]

        today_callback_needed = []
        for _, missed_row in today_missed_raw.iterrows():
            missed_number = missed_row["from"]
            missed_time = missed_row["end"]
            was_called_back = df_today_outbound[
                (df_today_outbound["to"] == missed_number) &
                (df_today_outbound["start"] > missed_time)
            ]
            if was_called_back.empty:
                today_callback_needed.append(missed_number)

        real_missed_today = len(today_callback_needed)
        real_calls_today = total_today - today_vm_count
        pct_missed_today = (real_missed_today / real_calls_today * 100) if real_calls_today else 0

        # Inbound and outbound
        df_inbound = df[df["direction"] == "inbound"].copy()
        df_outbound = df[df["direction"] == "outbound"].copy()

        vm_calls = df_inbound[df_inbound["endpoint"].astype(str).str.contains("VM")]
        vm_calls_count = len(vm_calls)

        missed_calls_raw = df_inbound[
            df_inbound["endpoint"].isna() |
            (df_inbound["endpoint"].astype(str).str.strip() == "")
        ].copy()

        callback_needed = []
        for _, missed_row in missed_calls_raw.iterrows():
            missed_number = missed_row["from"]
            missed_time = missed_row["end"]
            was_called_back = df_outbound[(df_outbound["to"] == missed_number) & (df_outbound["start"] > missed_time)]
            if was_called_back.empty:
                callback_needed.append({
                    "missed_from": missed_number,
                    "missed_time": missed_time.strftime("%Y-%m-%d %H:%M:%S"),
                })

        missed_calls_count = len(callback_needed)
        total_calls = len(df)
        real_missed = missed_calls_count
        real_calls = total_calls - len(vm_calls)
        percent_missed = (real_missed / real_calls * 100) if real_calls else 0

        driver.quit()
        callback_df = pd.DataFrame(callback_needed)

        return render_template(
            "result.html",
            callback_df=callback_df if not callback_df.empty else None,
            empty=callback_df.empty,
            total_calls=total_calls,
            missed_calls=missed_calls_count,
            vm_calls=vm_calls_count,
            percent_missed=percent_missed,
            total_today=total_today,
            missed_today=real_missed_today,
            vm_today=today_vm_count,
            percent_today=round(pct_missed_today, 1),
            total_last7=len(df_last7),
            missed_last7=real_missed_last7,
            vm_last7=last7_vm_count,
            percent_last7=round(pct_missed_last7, 1)
        )

    except Exception as e:
        print("❌ Exception occurred:", e)
        driver.quit()
        return jsonify({"error": str(e)})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port)
