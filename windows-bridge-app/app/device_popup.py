import tkinter as tk
from tkinter import ttk, messagebox
import threading
import logging

logger = logging.getLogger(__name__)


class DevicePopup:
    """Simple popup window showing detected devices and gateway config."""

    def __init__(self, monitor, config_manager):
        self._monitor = monitor
        self._config_mgr = config_manager
        self._root = None
        self._devices = []  # list of DetectedDevice

    def run(self):
        self._root = tk.Tk()
        self._root.title("Gateway Device Manager")
        self._root.geometry("480x520")
        self._root.resizable(False, False)
        self._root.attributes("-topmost", True)

        # --- Device List Section ---
        list_frame = ttk.LabelFrame(self._root, text="Detected Devices", padding=10)
        list_frame.pack(fill="x", padx=10, pady=(10, 5))

        columns = ("ip", "mac", "status")
        self._tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=5)
        self._tree.heading("ip", text="IP Address")
        self._tree.heading("mac", text="MAC Address")
        self._tree.heading("status", text="Status")
        self._tree.column("ip", width=130)
        self._tree.column("mac", width=180)
        self._tree.column("status", width=100)
        self._tree.pack(fill="x")
        self._tree.bind("<<TreeviewSelect>>", self._on_device_select)

        btn_frame = ttk.Frame(list_frame)
        btn_frame.pack(fill="x", pady=(5, 0))
        ttk.Button(btn_frame, text="Scan", command=self._scan_devices).pack(side="left")
        self._scan_status = ttk.Label(btn_frame, text="")
        self._scan_status.pack(side="left", padx=10)

        # --- Gateway Config Section ---
        config_frame = ttk.LabelFrame(self._root, text="Gateway Settings", padding=10)
        config_frame.pack(fill="x", padx=10, pady=5)

        fields = [
            ("Device IP:", "ip", "192.168.220.206"),
            ("Default Gateway:", "defGw", "192.168.220.1"),
            ("Subnet Mask:", "netmask", "255.255.255.0"),
            ("Store Code:", "storeCode", "store-1"),
            ("Server IP:", "svrIp", "192.168.240.101"),
            ("Server Port:", "svrPort", "80"),
            ("DNS:", "dnsIp", "8.8.8.8"),
        ]

        self._config_vars = {}
        for i, (label, key, default) in enumerate(fields):
            ttk.Label(config_frame, text=label).grid(row=i, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=default)
            self._config_vars[key] = var
            ttk.Entry(config_frame, textvariable=var, width=25).grid(row=i, column=1, sticky="w", padx=(10, 0))

        # MAC is read-only (auto-filled from selected device)
        ttk.Label(config_frame, text="MAC:").grid(row=len(fields), column=0, sticky="w", pady=2)
        self._mac_var = tk.StringVar(value="")
        mac_entry = ttk.Entry(config_frame, textvariable=self._mac_var, width=25, state="readonly")
        mac_entry.grid(row=len(fields), column=1, sticky="w", padx=(10, 0))

        # --- Action Buttons ---
        action_frame = ttk.Frame(self._root)
        action_frame.pack(fill="x", padx=10, pady=10)

        ttk.Button(action_frame, text="Apply Settings", command=self._apply_settings).pack(side="right")
        ttk.Button(action_frame, text="Ping Test", command=self._ping_test).pack(side="right", padx=5)
        ttk.Button(action_frame, text="Close", command=self._root.destroy).pack(side="left")

        # --- Status Bar ---
        self._statusbar = ttk.Label(self._root, text="Ready", relief="sunken", anchor="w")
        self._statusbar.pack(fill="x", side="bottom", padx=10, pady=(0, 5))

        # Auto-populate with currently detected device
        self._load_current_device()

        # Auto-scan on open
        self._scan_devices()

        self._root.mainloop()

    def _load_current_device(self):
        """If a device is already detected, pre-fill the form."""
        device = self._monitor.detected_device
        if device and device.ip:
            self._config_vars["ip"].set(device.ip)
            self._mac_var.set(device.mac)

    def _scan_devices(self):
        """Scan the subnet for devices matching the MAC prefix."""
        self._scan_status.config(text="Scanning...")
        self._tree.delete(*self._tree.get_children())

        def do_scan():
            import subprocess

            config = self._config_mgr.load()
            mac_prefix = config.target_device.mac_prefix.upper().replace(":", "").replace("-", "")
            prefix_dash = f"{mac_prefix[0:2]}-{mac_prefix[2:4]}-{mac_prefix[4:6]}"
            ethernet_cfg = config.ethernet_adapter

            # Populate ARP table
            from app.device_monitor import DeviceMonitor
            DeviceMonitor._populate_arp_table(ethernet_cfg.static_ip, ethernet_cfg.subnet_mask)

            # Collect all matching devices from ARP
            found = []
            try:
                result = subprocess.run(
                    ["arp", "-a"], capture_output=True, text=True, timeout=10,
                )
                for line in result.stdout.split("\n"):
                    line = line.strip()
                    parts = line.split()
                    if len(parts) >= 2:
                        mac = parts[1].upper()
                        if mac.startswith(prefix_dash):
                            found.append({"ip": parts[0], "mac": mac})
            except Exception as e:
                logger.exception("Scan failed")

            # Also check Get-NetNeighbor
            try:
                ps_cmd = "Get-NetNeighbor | Where-Object { $_.State -ne 'Unreachable' } | Select-Object -Property IPAddress,LinkLayerAddress | Format-Table -HideTableHeaders"
                result = subprocess.run(
                    ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
                    capture_output=True, text=True, timeout=15,
                )
                seen_ips = {d["ip"] for d in found}
                for line in result.stdout.split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split()
                    if len(parts) >= 2:
                        mac_clean = parts[1].upper().replace("-", "").replace(":", "")
                        if mac_clean.startswith(mac_prefix[:6]) and parts[0] not in seen_ips:
                            found.append({"ip": parts[0], "mac": parts[1].upper()})
            except Exception:
                pass

            self._root.after(0, lambda: self._show_scan_results(found))

        threading.Thread(target=do_scan, daemon=True).start()

    def _show_scan_results(self, devices):
        self._tree.delete(*self._tree.get_children())
        self._devices = devices

        if not devices:
            self._scan_status.config(text="No devices found")
            return

        for d in devices:
            self._tree.insert("", "end", values=(d["ip"], d["mac"], "Online"))

        self._scan_status.config(text=f"{len(devices)} device(s) found")

        # Auto-select the first device
        first = self._tree.get_children()[0]
        self._tree.selection_set(first)
        self._tree.focus(first)

    def _on_device_select(self, event):
        """Fill config form with selected device info."""
        selection = self._tree.selection()
        if not selection:
            return
        values = self._tree.item(selection[0])["values"]
        if values:
            self._config_vars["ip"].set(values[0])
            self._mac_var.set(values[1])

    def _ping_test(self):
        """Ping the selected device IP."""
        ip = self._config_vars["ip"].get()
        if not ip:
            return

        self._set_status(f"Pinging {ip}...")

        def do_ping():
            import subprocess
            try:
                result = subprocess.run(
                    ["ping", "-n", "3", "-w", "1000", ip],
                    capture_output=True, text=True, timeout=15,
                )
                success = result.returncode == 0
                output = result.stdout.strip().split("\n")
                # Get the summary line
                summary = output[-1] if output else ""
                self._root.after(0, lambda: self._set_status(
                    f"Ping {'OK' if success else 'FAILED'}: {summary}"
                ))
            except Exception as e:
                self._root.after(0, lambda: self._set_status(f"Ping error: {e}"))

        threading.Thread(target=do_ping, daemon=True).start()

    def _apply_settings(self):
        """Show confirmation and log the settings to apply."""
        ip = self._config_vars["ip"].get()
        mac = self._mac_var.get()

        if not ip or not mac:
            messagebox.showwarning("Warning", "Select a device first.")
            return

        settings = {
            "mac": mac.replace("-", ":"),
            "ip": self._config_vars["ip"].get(),
            "defGw": self._config_vars["defGw"].get(),
            "netmask": self._config_vars["netmask"].get(),
            "storeCode": self._config_vars["storeCode"].get(),
            "svrIp": self._config_vars["svrIp"].get(),
            "svrPort": self._config_vars["svrPort"].get(),
            "dnsIp": self._config_vars["dnsIp"].get(),
        }

        msg = (
            f"Apply settings to device?\n\n"
            f"  MAC: {settings['mac']}\n"
            f"  IP: {settings['ip']}\n"
            f"  Gateway: {settings['defGw']}\n"
            f"  Mask: {settings['netmask']}\n"
            f"  Store: {settings['storeCode']}\n"
            f"  Server: {settings['svrIp']}:{settings['svrPort']}\n"
            f"  DNS: {settings['dnsIp']}"
        )

        if messagebox.askyesno("Confirm", msg):
            logger.info("Applying gateway settings: %s", settings)
            self._set_status(f"Settings applied to {settings['ip']}")
            messagebox.showinfo("Success", f"Settings applied to {settings['ip']}")

    def _set_status(self, text: str):
        if self._root and self._statusbar:
            self._statusbar.config(text=text)
