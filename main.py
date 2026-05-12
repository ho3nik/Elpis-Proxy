import asyncio
import json
import logging
import platform
import sys
import threading
from pathlib import Path

import flet as ft

# Import the core proxy server
try:
    from proxy_logic import ProxyServer, _run as run_proxy_internal
except ImportError:
    # If running from a different directory
    sys.path.append(str(Path(__file__).parent))
    from proxy_logic import ProxyServer, _run as run_proxy_internal

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "config.json"

DEFAULT_CONFIG = {
    "auth_key": "",
    "script_ids": [],
    "listen_host": "127.0.0.1",
    "listen_port": 8080,
    "socks5_enabled": True,
    "socks5_port": 1080,
    "lan_sharing": False,
    "use_google_relay": True,
    "relay_worker_url": "",
    "tls_connect_timeout": 20,
    "tcp_connect_timeout": 15,
    "max_response_body_bytes": 209715200,
    "parallel_relay": 2,
    "sticky_scripts": False,
    "youtube_via_relay": True,
    "block_hosts": [],
    "bypass_hosts": ["localhost", ".local", ".lan", ".home.arpa"],
    "direct_google_exclude": [],
    "hosts": {},
}

# ── Custom Logger for Flet UI ──────────────────────────────────────────────
class FletLogHandler(logging.Handler):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def emit(self, record):
        log_entry = self.format(record)
        self.callback(log_entry)

def main(page: ft.Page):
    page.title = "Elpis Mobile"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 20
    page.window_width = 400
    page.window_height = 800
    page.window_resizable = True

    # ── State ──────────────────────────────────────────────────────────────
    proxy_task = None
    proxy_loop = None
    is_running = False
    config = dict(DEFAULT_CONFIG)

    # ── Helpers ────────────────────────────────────────────────────────────
    def load_config():
        nonlocal config
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH) as f:
                    config.update(json.load(f))
            except:
                pass

    def save_config():
        try:
            # Sync fields back to config
            config["auth_key"] = auth_key_field.value
            config["relay_worker_url"] = worker_url_field.value
            
            # Handle list fields
            s_ids = script_ids_field.value.strip().split("\n")
            config["script_ids"] = [s.strip() for s in s_ids if s.strip()]
            
            config["socks5_enabled"] = socks5_enabled_field.value
            config["socks5_port"] = int(socks5_port_field.value or 1080)
            
            with open(CONFIG_PATH, "w") as f:
                json.dump(config, f, indent=2)
            page.show_snack_bar(ft.SnackBar(ft.Text("Config saved!")))
        except Exception as e:
            page.show_snack_bar(ft.SnackBar(ft.Text(f"Error saving: {e}")))

    # ── UI Components ──────────────────────────────────────────────────────
    log_view = ft.ListView(expand=True, spacing=5, auto_scroll=True)
    
    def append_log(text):
        log_view.controls.append(ft.Text(text, size=12, font_family="monospace"))
        page.update()

    # Set up global logging to pipe to our UI
    flet_handler = FletLogHandler(append_log)
    flet_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
    logging.getLogger().addHandler(flet_handler)
    logging.getLogger().setLevel(logging.INFO)

    async def start_proxy_task():
        nonlocal is_running, proxy_task
        try:
            is_running = True
            update_status_ui()
            append_log("🚀 Starting proxy...")
            await run_proxy_internal(config)
        except Exception as e:
            append_log(f"❌ Error: {e}")
        finally:
            is_running = False
            update_status_ui()
            append_log("🛑 Proxy stopped.")

    def toggle_proxy(e):
        nonlocal proxy_task, is_running
        if not is_running:
            # Run the proxy in the background
            save_config()
            asyncio.create_task(start_proxy_task())
        else:
            # How to stop? main.py's server needs a way to be signaled.
            # For now, we'll suggest a restart.
            append_log("⚠️ To stop, please restart the app (Signal handling in same-process loop is complex).")

    def copy_tg_proxy():
        port = config.get("socks5_port", 1080)
        link = f"tg://socks?server=127.0.0.1&port={port}"
        page.set_clipboard(link)
        page.show_snack_bar(ft.SnackBar(ft.Text(f"Copied: {link}")))

    def update_status_ui():
        status_dot.color = ft.colors.GREEN if is_running else ft.colors.RED
        status_text.value = "RUNNING" if is_running else "STOPPED"
        start_btn.text = "STOP" if is_running else "START PROXY"
        start_btn.icon = ft.icons.STOP if is_running else ft.icons.PLAY_ARROW
        page.update()

    # ── Build UI Tabs ──────────────────────────────────────────────────────
    
    # 1. Status Tab
    status_dot = ft.Icon(ft.icons.CIRCLE, color=ft.colors.RED, size=12)
    status_text = ft.Text("STOPPED", weight=ft.FontWeight.BOLD)
    start_btn = ft.ElevatedButton(
        "START PROXY", 
        icon=ft.icons.PLAY_ARROW,
        on_click=toggle_proxy,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)),
        height=60,
        expand=True
    )
    
    tg_btn = ft.ElevatedButton(
        "TELEGRAM PROXY",
        icon=ft.icons.SEND,
        on_click=lambda _: copy_tg_proxy(),
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10), color=ft.colors.BLUE_400),
        height=60,
        expand=True
    )

    status_card = ft.Card(
        content=ft.Container(
            content=ft.Column([
                ft.Row([status_dot, status_text], alignment=ft.MainAxisAlignment.CENTER),
                ft.Divider(),
                ft.Row([start_btn]),
                ft.Row([tg_btn])
            ]),
            padding=20
        )
    )

    status_tab = ft.Column([
        ft.Text("Elpis Control Panel", size=24, weight=ft.FontWeight.BOLD),
        ft.Text("MasterHttpRelay for Android", size=14, color=ft.colors.GREY_400),
        ft.VerticalDivider(height=10),
        status_card,
        ft.Text("Logs", size=18, weight=ft.FontWeight.BOLD),
        ft.Container(content=log_view, expand=True, border=ft.border.all(1, ft.colors.GREY_800), border_radius=10, padding=10)
    ], expand=True)

    # 2. Config Tab
    load_config()
    auth_key_field = ft.TextField(label="Auth Key", value=config.get("auth_key", ""), password=True, can_reveal_password=True)
    worker_url_field = ft.TextField(label="Cloudflare Worker URL", value=config.get("relay_worker_url", ""))
    script_ids_field = ft.TextField(
        label="Google Apps Script IDs (one per line)", 
        value="\n".join(config.get("script_ids", [])),
        multiline=True,
        min_lines=3
    )
    socks5_enabled_field = ft.Switch(label="Enable SOCKS5 Proxy", value=config.get("socks5_enabled", True))
    socks5_port_field = ft.TextField(label="SOCKS5 Port", value=str(config.get("socks5_port", 1080)), keyboard_type=ft.KeyboardType.NUMBER)

    config_tab = ft.Column([
        ft.Text("Configuration", size=24, weight=ft.FontWeight.BOLD),
        ft.VerticalDivider(height=10),
        auth_key_field,
        worker_url_field,
        script_ids_field,
        ft.Divider(),
        socks5_enabled_field,
        socks5_port_field,
        ft.ElevatedButton("SAVE CONFIG", icon=ft.icons.SAVE, on_click=lambda _: save_config()),
        ft.Text("Note: After saving, restart the proxy to apply changes.", size=12, italic=True, color=ft.colors.GREY_400)
    ], scroll=ft.ScrollMode.AUTO)

    # 3. About Tab
    about_tab = ft.Column([
        ft.Text("About Elpis", size=24, weight=ft.FontWeight.BOLD),
        ft.Text("Version 1.0.0-Mobile"),
        ft.Text("A specialized HTTP relay for bypassing network restrictions."),
        ft.Text("\nInstructions:", weight=ft.FontWeight.BOLD),
        ft.Text("1. Fill in your Auth Key and Script IDs."),
        ft.Text("2. Click START PROXY."),
        ft.Text("3. Go to your Phone's WiFi Settings -> Modify Network -> Proxy -> Manual."),
        ft.Text("4. Set Proxy Host to 127.0.0.1 and Port to 8080."),
        ft.Text("\n🛡️ HTTPS Security Setup:", weight=ft.FontWeight.BOLD),
        ft.Text("To fix 'Your connection is not private' errors, you MUST install the Root Certificate:"),
        ft.Text("1. Connect your phone to your computer."),
        ft.Text("2. Locate 'ca/ca.crt' in the Elpis folder on your computer."),
        ft.Text("3. Copy 'ca.crt' to your phone's internal storage."),
        ft.Text("4. On your phone: Settings -> Security -> More Security Settings -> Encryption & credentials -> Install a certificate -> CA certificate."),
        ft.Text("5. Install 'ca.crt' and restart your browser."),
    ])

    tabs = ft.Tabs(
        selected_index=0,
        animation_duration=300,
        tabs=[
            ft.Tab(text="Status", icon=ft.icons.DASHBOARD, content=status_tab),
            ft.Tab(text="Config", icon=ft.icons.SETTINGS, content=config_tab),
            ft.Tab(text="About", icon=ft.icons.INFO, content=about_tab),
        ],
        expand=True
    )

    page.add(tabs)

if __name__ == "__main__":
    ft.app(target=main)
