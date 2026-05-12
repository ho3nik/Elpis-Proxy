#!/usr/bin/env python3
"""
Elpis GUI — Cross-platform CustomTkinter interface for MHR-CFW proxy.
Provides config editing, proxy start/stop, system proxy set/unset, and log viewer.
"""

import customtkinter as ctk
import json
import os
import sys
import signal
import queue
import smtplib
import traceback
import multiprocessing
import smtplib
import traceback
import urllib.parse
import subprocess
import threading
import platform
from pathlib import Path
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from tkinter import filedialog
import customtkinter as ctk

# Local imports
try:
    import proxy_logic
except ImportError:
    pass

CRASH_EMAIL = "rahaajeagar@gmail.com"
# Removed automated email reporting as per user request.

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "config.json"
MAIN_SCRIPT = HERE / "proxy_logic.py"
REQUIREMENTS = HERE / "requirements.txt"


def _find_python():
    """Return the best Python executable: prefer the project venv, then sys.executable."""
    if platform.system() == "Windows":
        venv_py = HERE / ".venv" / "Scripts" / "python.exe"
    else:
        venv_py = HERE / ".venv" / "bin" / "python"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable


def _auto_install_deps():
    """Ensure a venv exists and all requirements.txt deps are installed."""
    # SKIP if running as a bundled EXE to avoid infinite loop
    if getattr(sys, 'frozen', False):
        return
        
    venv_dir = HERE / ".venv"
    py = sys.executable

    # Create venv if missing
    if not venv_dir.exists():
        subprocess.run([py, "-m", "venv", str(venv_dir)], check=True)

    pip_py = _find_python()

    # Install/upgrade deps quietly
    cmd = [pip_py, "-m", "pip", "install", "--disable-pip-version-check",
           "-q", "-r", str(REQUIREMENTS)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
    except subprocess.CalledProcessError:
        # Retry with mirror for restricted networks
        cmd += ["-i", "https://mirror-pypi.runflare.com/simple/",
                "--trusted-host", "mirror-pypi.runflare.com"]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        except Exception:
            pass  # GUI will still open; proxy start will show the real error
    except Exception:
        pass

# ── Theme ────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

ACCENT      = "#6C63FF"
ACCENT_HOVER= "#5A52D5"
SUCCESS     = "#2ECC71"
DANGER      = "#E74C3C"
WARN        = "#F39C12"
BG_DARK     = "#1A1A2E"
BG_CARD     = "#16213E"
BG_INPUT    = "#0F3460"
FG_TEXT     = "#E8E8E8"
FG_DIM      = "#8D8DAA"

DEFAULT_CONFIG = {
    "mode": "apps_script",
    "google_ip": "216.239.38.120",
    "front_domain": "www.google.com",
    "script_ids": [],
    "auth_key": "",
    "listen_host": "127.0.0.1",
    "listen_port": 8085,
    "socks5_enabled": True,
    "socks5_port": 1080,
    "log_level": "INFO",
    "verify_ssl": True,
    "lan_sharing": False,
    "relay_timeout": 90,
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


class ElpisGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Elpis — MHR-CFW Proxy Manager")
        self.geometry("960x720")
        self.minsize(800, 600)
        self.configure(fg_color=BG_DARK)

        self.proxy_process = None
        self.log_queue = queue.Queue()
        self.system_proxy_active = False
        self.fields = {}
        self.log_history = []
        self.error_count = 0
        self.crash_email_sent = False
        self.python_exe = _find_python()

        self._load_config()
        self._build_ui()
        self._poll_log_queue()

    # ── Config I/O ────────────────────────────────────────────────────────
    def _load_config(self):
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH) as f:
                    self.config = json.load(f)
            except Exception:
                self.config = dict(DEFAULT_CONFIG)
        else:
            self.config = dict(DEFAULT_CONFIG)

    def _save_config(self):
        self._collect_fields()
        try:
            with open(CONFIG_PATH, "w") as f:
                json.dump(self.config, f, indent=2)
                f.write("\n")
            self._log("✅ Config saved to config.json")
        except Exception as e:
            self._log(f"❌ Save failed: {e}")

    def _collect_fields(self):
        for key, widget in self.fields.items():
            if isinstance(widget, ctk.CTkSwitch):
                self.config[key] = bool(widget.get())
            elif isinstance(widget, ctk.CTkOptionMenu):
                self.config[key] = widget.get()
            elif isinstance(widget, ctk.CTkTextbox):
                raw = widget.get("1.0", "end").strip()
                if key in ("script_ids", "block_hosts", "bypass_hosts",
                           "direct_google_exclude", "chunked_download_extensions"):
                    self.config[key] = [x.strip() for x in raw.split("\n") if x.strip()]
                elif key == "hosts":
                    try:
                        self.config[key] = json.loads(raw) if raw else {}
                    except json.JSONDecodeError:
                        self.config[key] = {}
                else:
                    self.config[key] = raw
            else:
                val = widget.get().strip()
                if key in ("listen_port", "socks5_port", "relay_timeout",
                           "tls_connect_timeout", "tcp_connect_timeout",
                           "max_response_body_bytes", "parallel_relay",
                           "chunked_download_min_size", "chunked_download_chunk_size",
                           "chunked_download_max_parallel", "chunked_download_max_chunks"):
                    try:
                        self.config[key] = int(val)
                    except ValueError:
                        pass
                else:
                    self.config[key] = val

    # ── UI Build ─────────────────────────────────────────────────────────
    def _build_ui(self):
        # Top bar
        top = ctk.CTkFrame(self, fg_color=BG_CARD, height=56, corner_radius=0)
        top.pack(fill="x")
        top.pack_propagate(False)
        ctk.CTkLabel(top, text="⚡ Elpis", font=("Helvetica", 22, "bold"),
                     text_color=ACCENT).pack(side="left", padx=16)
        ctk.CTkLabel(top, text="MHR-CFW Proxy Manager", font=("Helvetica", 13),
                     text_color=FG_DIM).pack(side="left", padx=4)

        # Status indicator
        self.status_label = ctk.CTkLabel(top, text="● Stopped", font=("Helvetica", 13, "bold"),
                                         text_color=DANGER)
        self.status_label.pack(side="right", padx=16)

        # Tabview
        self.tabs = ctk.CTkTabview(self, fg_color=BG_DARK, segmented_button_fg_color=BG_CARD,
                                    segmented_button_selected_color=ACCENT,
                                    segmented_button_unselected_color=BG_INPUT)
        self.tabs.pack(fill="both", expand=True, padx=12, pady=(8, 4))

        self._build_connection_tab()
        self._build_network_tab()
        self._build_advanced_tab()
        self._build_log_tab()

        # Bottom buttons
        bottom = ctk.CTkFrame(self, fg_color=BG_DARK, height=52)
        bottom.pack(fill="x", padx=12, pady=(0, 8))

        self.start_btn = ctk.CTkButton(bottom, text="▶  Start Proxy", fg_color=SUCCESS,
                                        hover_color="#27AE60", width=150, height=38,
                                        font=("Helvetica", 14, "bold"), command=self._start_proxy)
        self.start_btn.pack(side="left", padx=(0, 8))

        self.stop_btn = ctk.CTkButton(bottom, text="■  Stop Proxy", fg_color=DANGER,
                                       hover_color="#C0392B", width=150, height=38,
                                       font=("Helvetica", 14, "bold"), command=self._stop_proxy,
                                       state="disabled")
        self.stop_btn.pack(side="left", padx=(0, 8))

        self.cert_btn = ctk.CTkButton(bottom, text="🛡️ Install Cert", fg_color="#34495e",
                                       hover_color="#2c3e50", width=140, height=38,
                                       font=("Helvetica", 13), command=self._install_cert)
        self.cert_btn.pack(side="left", padx=(0, 8))

        self.folder_btn = ctk.CTkButton(bottom, text="📁 Cert Folder", fg_color="#34495e",
                                         hover_color="#2c3e50", width=140, height=38,
                                         font=("Helvetica", 13), command=self._open_cert_folder)
        self.folder_btn.pack(side="left", padx=(0, 8))

        self.proxy_btn = ctk.CTkButton(bottom, text="🌐 Set System Proxy", fg_color=ACCENT,
                                        hover_color=ACCENT_HOVER, width=170, height=38,
                                        font=("Helvetica", 13, "bold"), command=self._toggle_system_proxy)
        self.proxy_btn.pack(side="left", padx=(0, 8))

        ctk.CTkButton(bottom, text="💾 Save Config", fg_color=BG_INPUT,
                       hover_color="#1A4A80", width=130, height=38,
                       font=("Helvetica", 13), command=self._save_config).pack(side="right")

    def _build_connection_tab(self):
        tab = self.tabs.add("🔑 Connection")
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        self._section(scroll, "Authentication")
        self._add_entry(scroll, "auth_key", "Auth Key (must match Code.gs)")
        self._add_textbox(scroll, "script_ids", "Script Deployment IDs (one per line)", h=90)

        self._section(scroll, "Google Fronting")
        self._add_entry(scroll, "google_ip", "Google IP")
        self._add_entry(scroll, "front_domain", "Front Domain (SNI)")

    def _build_network_tab(self):
        tab = self.tabs.add("🌐 Network")
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        self._section(scroll, "Proxy Listener")
        self._add_entry(scroll, "listen_host", "Listen Host")
        self._add_entry(scroll, "listen_port", "HTTP Port")
        self._add_switch(scroll, "socks5_enabled", "Enable SOCKS5")
        self._add_entry(scroll, "socks5_port", "SOCKS5 Port")
        self._add_switch(scroll, "lan_sharing", "LAN Sharing")

        self._section(scroll, "Host Lists")
        self._add_textbox(scroll, "bypass_hosts", "Bypass Hosts (one per line)", h=70)
        self._add_textbox(scroll, "block_hosts", "Block Hosts (one per line)", h=70)
        self._add_textbox(scroll, "direct_google_exclude", "Direct Google Exclude (one per line)", h=70)

    def _build_advanced_tab(self):
        tab = self.tabs.add("⚙️ Advanced")
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        self._section(scroll, "Timeouts & Limits")
        self._add_entry(scroll, "relay_timeout", "Relay Timeout (s)")
        self._add_entry(scroll, "tls_connect_timeout", "TLS Connect Timeout (s)")
        self._add_entry(scroll, "tcp_connect_timeout", "TCP Connect Timeout (s)")
        self._add_entry(scroll, "max_response_body_bytes", "Max Response Body (bytes)")
        self._add_entry(scroll, "parallel_relay", "Parallel Relay Count")

        self._section(scroll, "Options")
        self._add_switch(scroll, "verify_ssl", "Verify SSL")
        self._add_switch(scroll, "sticky_scripts", "Sticky Scripts")
        self._add_switch(scroll, "youtube_via_relay", "YouTube via Relay")
        self._add_option(scroll, "log_level", "Log Level", ["DEBUG", "INFO", "WARNING", "ERROR"])

        self._section(scroll, "Custom Hosts (JSON)")
        self._add_textbox(scroll, "hosts", "hosts JSON mapping", h=80, is_json=True)

    def _build_log_tab(self):
        tab = self.tabs.add("📋 Logs")
        self.log_box = ctk.CTkTextbox(tab, fg_color=BG_INPUT, text_color="#00FF88",
                                       font=("Courier", 12), corner_radius=8, wrap="word")
        self.log_box.pack(fill="both", expand=True, padx=4, pady=4)
        self.log_box.configure(state="disabled")
        btn_bar = ctk.CTkFrame(tab, fg_color="transparent")
        btn_bar.pack(pady=(4, 0))
        ctk.CTkButton(btn_bar, text="Clear Logs", fg_color=BG_CARD, hover_color=BG_INPUT,
                       width=110, height=30, command=self._clear_logs).pack(side="left", padx=4)
        ctk.CTkButton(btn_bar, text="📁 Export Logs", fg_color=ACCENT, hover_color=ACCENT_HOVER,
                       width=130, height=30, command=self._export_logs).pack(side="left", padx=4)
        ctk.CTkButton(btn_bar, text="✈️ Telegram Proxy", fg_color="#24A1DE", hover_color="#1d86ba",
                       width=140, height=30, command=self._copy_tg_proxy).pack(side="left", padx=4)

    # ── Widget Helpers ────────────────────────────────────────────────────
    def _section(self, parent, title):
        ctk.CTkLabel(parent, text=title, font=("Helvetica", 15, "bold"),
                     text_color=ACCENT).pack(anchor="w", padx=8, pady=(12, 4))
        ctk.CTkFrame(parent, height=1, fg_color=BG_INPUT).pack(fill="x", padx=8, pady=(0, 6))

    def _add_entry(self, parent, key, label):
        frm = ctk.CTkFrame(parent, fg_color="transparent")
        frm.pack(fill="x", padx=8, pady=3)
        ctk.CTkLabel(frm, text=label, font=("Helvetica", 12), text_color=FG_DIM,
                     width=220, anchor="w").pack(side="left")
        entry = ctk.CTkEntry(frm, fg_color=BG_INPUT, border_color=BG_CARD, width=320, height=32)
        entry.pack(side="left", padx=(8, 0))
        val = self.config.get(key, "")
        entry.insert(0, str(val))
        self.fields[key] = entry

    def _add_switch(self, parent, key, label):
        frm = ctk.CTkFrame(parent, fg_color="transparent")
        frm.pack(fill="x", padx=8, pady=3)
        ctk.CTkLabel(frm, text=label, font=("Helvetica", 12), text_color=FG_DIM,
                     width=220, anchor="w").pack(side="left")
        var = ctk.BooleanVar(value=bool(self.config.get(key, False)))
        sw = ctk.CTkSwitch(frm, text="", variable=var, onvalue=True, offvalue=False,
                            progress_color=SUCCESS)
        sw.pack(side="left", padx=(8, 0))
        self.fields[key] = sw

    def _add_option(self, parent, key, label, options):
        frm = ctk.CTkFrame(parent, fg_color="transparent")
        frm.pack(fill="x", padx=8, pady=3)
        ctk.CTkLabel(frm, text=label, font=("Helvetica", 12), text_color=FG_DIM,
                     width=220, anchor="w").pack(side="left")
        menu = ctk.CTkOptionMenu(frm, values=options, fg_color=BG_INPUT,
                                  button_color=ACCENT, button_hover_color=ACCENT_HOVER, width=160)
        menu.set(str(self.config.get(key, options[0])))
        menu.pack(side="left", padx=(8, 0))
        self.fields[key] = menu

    def _add_textbox(self, parent, key, label, h=80, is_json=False):
        ctk.CTkLabel(parent, text=label, font=("Helvetica", 12), text_color=FG_DIM,
                     anchor="w").pack(anchor="w", padx=8, pady=(6, 2))
        tb = ctk.CTkTextbox(parent, fg_color=BG_INPUT, border_color=BG_CARD,
                             height=h, font=("Courier", 11), corner_radius=6, wrap="word")
        tb.pack(fill="x", padx=8, pady=(0, 4))
        val = self.config.get(key, [] if not is_json else {})
        if is_json:
            tb.insert("1.0", json.dumps(val, indent=2) if val else "{}")
        elif isinstance(val, list):
            tb.insert("1.0", "\n".join(str(v) for v in val))
        else:
            tb.insert("1.0", str(val))
        self.fields[key] = tb

    # ── Logging ──────────────────────────────────────────────────────────
    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] {msg}"
        self.log_history.append(entry)
        self.log_queue.put(entry)
        # Track errors for crash detection
        if any(word in msg.lower() for word in ["error", "exception", "crash", "fatal", "traceback"]):
            self.error_count += 1

    def _poll_log_queue(self):
        while not self.log_queue.empty():
            msg = self.log_queue.get_nowait()
            self.log_box.configure(state="normal")
            self.log_box.insert("end", msg + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.after(100, self._poll_log_queue)

    def _clear_logs(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self.log_history.clear()
        self.error_count = 0
        self.crash_email_sent = False

    def _copy_tg_proxy(self):
        port = self.config.get("socks5_port", 1080)
        link = f"tg://socks?server=127.0.0.1&port={port}"
        self.clipboard_clear()
        self.clipboard_append(link)
        self.update()
        self._log(f"📋 Telegram proxy link copied: {link}")
        from tkinter import messagebox
        messagebox.showinfo("Telegram Proxy", f"Link copied to clipboard!\n\n{link}\n\nPaste this in Telegram to use the proxy.")

    def _export_logs(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("Log files", "*.log"), ("All", "*.*")],
            initialfile=f"elpis_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write("\n".join(self.log_history))
                self._log(f"📁 Logs exported to {path}")
            except Exception as e:
                self._log(f"❌ Export failed: {e}")

    def _install_cert(self):
        self._log("🛡️ Attempting to install Root Certificate...")
        try:
            from proxy_logic import CA_CERT_FILE, install_ca
            if not CA_CERT_FILE.exists():
                from mitm import MITMCertManager
                MITMCertManager()
            
            ok = install_ca(CA_CERT_FILE)
            if ok:
                from tkinter import messagebox
                messagebox.showinfo("Certificate Installed", 
                    "Root Certificate installed to System Keychain!\n\n"
                    "CHROME USERS:\n"
                    "1. Chrome may need a FULL RESTART.\n"
                    "2. If it still fails, go to chrome://settings/security\n"
                    "3. Click 'Manage certificates' -> 'Trust' -> 'Import' and select ca.crt.")
                self._log("✅ Root Certificate installed.")
            else:
                self._log("❌ Certificate installation failed. Please install ca/ca.crt manually.")
        except Exception as e:
            self._log(f"❌ Cert installation error: {e}")

    def _open_cert_folder(self):
        cert_dir = HERE / "ca"
        if not cert_dir.exists():
            from mitm import MITMCertManager
            MITMCertManager()
        
        try:
            if platform.system() == "Darwin":
                subprocess.Popen(["open", str(cert_dir)])
            elif platform.system() == "Windows":
                os.startfile(str(cert_dir))
            self._log(f"📁 Opening certificate folder: {cert_dir}")
        except Exception as e:
            self._log(f"❌ Could not open folder: {e}")

    # ── Proxy Control ─────────────────────────────────────────────────────
    def _kill_port_holders(self, port):
        """Find and kill any process listening on the specified port."""
        if not port:
            return
        try:
            if platform.system() == "Darwin" or platform.system() == "Linux":
                # Use lsof to find PID and kill -9
                cmd = f"lsof -ti:{port} | xargs kill -9"
                subprocess.run(cmd, shell=True, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
            elif platform.system() == "Windows":
                # Use netstat and taskkill
                cmd = f'for /f "tokens=5" %a in (\'netstat -aon ^| findstr :{port} ^| findstr LISTENING\') do taskkill /f /pid %a'
                subprocess.run(cmd, shell=True, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
            self._log(f"⚡ Cleared any processes on port {port}")
        except Exception:
            pass

    def _start_proxy(self):
        if self.proxy_process and self.proxy_process.poll() is None:
            self._log("⚠️  Proxy is already running.")
            return
        self._save_config()
        
        # 1. Kill any existing port holders (HTTP and SOCKS)
        self._kill_port_holders(self.config.get("listen_port", 8080))
        if self.config.get("socks5_enabled", True):
            self._kill_port_holders(self.config.get("socks5_port", 1080))

        # 2. Auto-install certificate
        self._install_cert()

        # 3. Start proxy process
        self._log("🚀 Starting proxy...")
        try:
            if getattr(sys, 'frozen', False):
                # If bundled as EXE, run proxy_logic directly in a separate thread
                # instead of spawning the EXE again (which would cause infinite loop)
                threading.Thread(target=self._run_proxy_backend, daemon=False).start()
            else:
                cmd = [self.python_exe, str(MAIN_SCRIPT)]
                
                self.proxy_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    cwd=str(HERE), bufsize=1, text=True,
                )
                self.start_btn.configure(state="disabled")
                self.stop_btn.configure(state="normal")
                self.status_label.configure(text="● Running", text_color=SUCCESS)
                threading.Thread(target=self._read_output, daemon=True).start()
        except Exception as e:
            self._log(f"❌ Failed to start: {e}")

    def _run_proxy_backend(self):
        """Run proxy_logic.main() in a thread (for bundled EXE mode)."""
        try:
            self.start_btn.configure(state="disabled")
            self.stop_btn.configure(state="normal")
            self.status_label.configure(text="● Running", text_color=SUCCESS)
            
            import proxy_logic
            proxy_logic.main()
        except Exception as e:
            self._log(f"❌ Proxy error: {e}\n{traceback.format_exc()}")
        finally:
            self._on_proxy_stopped()

    def _read_output(self):
        proc = self.proxy_process
        try:
            for line in proc.stdout:
                self._log(line.rstrip())
        except Exception:
            pass
        rc = proc.wait()
        self._log(f"Proxy exited with code {rc}")
        self.after(0, self._on_proxy_stopped)

    def _on_proxy_stopped(self):
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.status_label.configure(text="● Stopped", text_color=DANGER)

    def _stop_proxy(self):
        if self.proxy_process and self.proxy_process.poll() is None:
            self._log("🛑 Stopping proxy...")
            if platform.system() == "Windows":
                self.proxy_process.terminate()
            else:
                os.kill(self.proxy_process.pid, signal.SIGINT)
            try:
                self.proxy_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proxy_process.kill()
            self._on_proxy_stopped()
        else:
            self._log("⚠️  Proxy is not running.")

    # ── System Proxy ──────────────────────────────────────────────────────
    def _toggle_system_proxy(self):
        if self.system_proxy_active:
            self._unset_system_proxy()
        else:
            self._set_system_proxy()

    def _set_system_proxy(self):
        self._collect_fields()
        host = self.config.get("listen_host", "127.0.0.1")
        if host == "0.0.0.0":
            host = "127.0.0.1"
        port = str(self.config.get("listen_port", 8085))
        syst = platform.system()
        try:
            if syst == "Darwin":
                services = subprocess.check_output(
                    ["networksetup", "-listallnetworkservices"], text=True
                ).strip().split("\n")[1:]
                for svc in services:
                    svc = svc.strip()
                    if svc.startswith("*"):
                        continue
                    subprocess.run(["networksetup", "-setwebproxy", svc, host, port], check=True)
                    subprocess.run(["networksetup", "-setsecurewebproxy", svc, host, port], check=True)
                    subprocess.run(["networksetup", "-setwebproxystate", svc, "on"], check=True)
                    subprocess.run(["networksetup", "-setsecurewebproxystate", svc, "on"], check=True)
                self._log(f"✅ macOS system proxy set to {host}:{port}")
            elif syst == "Windows":
                proxy_val = f"{host}:{port}"
                subprocess.run([
                    "reg", "add",
                    r"HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                    "/v", "ProxyEnable", "/t", "REG_DWORD", "/d", "1", "/f"
                ], check=True, capture_output=True)
                subprocess.run([
                    "reg", "add",
                    r"HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                    "/v", "ProxyServer", "/t", "REG_SZ", "/d", proxy_val, "/f"
                ], check=True, capture_output=True)
                self._log(f"✅ Windows system proxy set to {proxy_val}")
            else:
                self._log("⚠️  System proxy auto-set not supported on this OS. Set manually.")
                return
            self.system_proxy_active = True
            self.proxy_btn.configure(text="🌐 Unset System Proxy", fg_color=WARN)
        except Exception as e:
            self._log(f"❌ Failed to set proxy: {e}")

    def _unset_system_proxy(self):
        syst = platform.system()
        try:
            if syst == "Darwin":
                services = subprocess.check_output(
                    ["networksetup", "-listallnetworkservices"], text=True
                ).strip().split("\n")[1:]
                for svc in services:
                    svc = svc.strip()
                    if svc.startswith("*"):
                        continue
                    subprocess.run(["networksetup", "-setwebproxystate", svc, "off"], check=True)
                    subprocess.run(["networksetup", "-setsecurewebproxystate", svc, "off"], check=True)
                self._log("✅ macOS system proxy disabled")
            elif syst == "Windows":
                subprocess.run([
                    "reg", "add",
                    r"HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                    "/v", "ProxyEnable", "/t", "REG_DWORD", "/d", "0", "/f"
                ], check=True, capture_output=True)
                self._log("✅ Windows system proxy disabled")
            else:
                self._log("⚠️  Not supported on this OS.")
                return
            self.system_proxy_active = False
            self.proxy_btn.configure(text="🌐 Set System Proxy", fg_color=ACCENT)
        except Exception as e:
            self._log(f"❌ Failed to unset proxy: {e}")

    def destroy(self):
        if self.system_proxy_active:
            self._unset_system_proxy()
        if self.proxy_process and self.proxy_process.poll() is None:
            self.proxy_process.terminate()
        super().destroy()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    
    # Auto-install dependencies before GUI opens (only if not frozen)
    _auto_install_deps()
    app = ElpisGUI()
    app.mainloop()
