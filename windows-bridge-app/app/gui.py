import tkinter as tk
from tkinter import ttk, messagebox
import logging
import threading

logger = logging.getLogger(__name__)


class SettingsWindow:
    """Tkinter-based settings GUI for the Network Bridge app."""

    def __init__(self, config_manager, on_save_callback=None):
        self._config_mgr = config_manager
        self._on_save = on_save_callback
        self._root = None

    def run(self):
        self._root = tk.Tk()
        self._root.title("Network Bridge - Settings")
        self._root.geometry("520x480")
        self._root.resizable(False, False)

        config = self._config_mgr.load()

        notebook = ttk.Notebook(self._root)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        # -- Device Tab --
        device_frame = ttk.Frame(notebook, padding=10)
        notebook.add(device_frame, text="Device")

        ttk.Label(device_frame, text="Detection Method:").grid(row=0, column=0, sticky="w", pady=5)
        self._detection_method = tk.StringVar(value=config.target_device.detection_method)
        method_frame = ttk.Frame(device_frame)
        method_frame.grid(row=0, column=1, columnspan=2, sticky="w")
        ttk.Radiobutton(method_frame, text="Hardware ID", variable=self._detection_method, value="hardware_id").pack(side="left")
        ttk.Radiobutton(method_frame, text="Name", variable=self._detection_method, value="friendly_name").pack(side="left", padx=5)
        ttk.Radiobutton(method_frame, text="MAC", variable=self._detection_method, value="mac_address").pack(side="left", padx=5)
        ttk.Radiobutton(method_frame, text="Link", variable=self._detection_method, value="ethernet_link").pack(side="left", padx=5)

        ttk.Label(device_frame, text="Hardware ID:").grid(row=1, column=0, sticky="w", pady=5)
        self._hardware_id = tk.StringVar(value=config.target_device.hardware_id)
        ttk.Entry(device_frame, textvariable=self._hardware_id, width=40).grid(row=1, column=1, columnspan=2, sticky="w")

        ttk.Label(device_frame, text="Friendly Name:").grid(row=2, column=0, sticky="w", pady=5)
        self._friendly_name = tk.StringVar(value=config.target_device.friendly_name)
        ttk.Entry(device_frame, textvariable=self._friendly_name, width=40).grid(row=2, column=1, columnspan=2, sticky="w")

        ttk.Label(device_frame, text="MAC Prefix (OUI):").grid(row=3, column=0, sticky="w", pady=5)
        self._mac_prefix = tk.StringVar(value=config.target_device.mac_prefix)
        ttk.Entry(device_frame, textvariable=self._mac_prefix, width=20).grid(row=3, column=1, sticky="w")
        ttk.Label(device_frame, text="(예: 78:E9:80)").grid(row=3, column=2, sticky="w")

        ttk.Label(device_frame, text="Priority IP:").grid(row=4, column=0, sticky="w", pady=5)
        self._priority_ip = tk.StringVar(value=config.target_device.priority_ip)
        ttk.Entry(device_frame, textvariable=self._priority_ip, width=20).grid(row=4, column=1, sticky="w")
        ttk.Label(device_frame, text="(우선 확인할 IP)").grid(row=4, column=2, sticky="w")

        ttk.Button(device_frame, text="Scan USB Devices", command=self._scan_devices).grid(row=5, column=0, columnspan=3, pady=10)

        self._device_listbox = tk.Listbox(device_frame, height=6, width=60)
        self._device_listbox.grid(row=6, column=0, columnspan=3, sticky="we")
        self._device_listbox.bind("<<ListboxSelect>>", self._on_device_select)

        # -- Network Tab --
        net_frame = ttk.Frame(notebook, padding=10)
        notebook.add(net_frame, text="Network")

        fields = [
            ("Ethernet Adapter:", "ethernet_name", config.ethernet_adapter.name),
            ("Static IP:", "static_ip", config.ethernet_adapter.static_ip),
            ("Subnet Mask:", "subnet_mask", config.ethernet_adapter.subnet_mask),
            ("Gateway:", "gateway", config.ethernet_adapter.gateway),
            ("DNS Primary:", "dns_primary", config.ethernet_adapter.dns_primary),
            ("DNS Secondary:", "dns_secondary", config.ethernet_adapter.dns_secondary),
        ]
        self._net_vars = {}
        for i, (label, key, default) in enumerate(fields):
            ttk.Label(net_frame, text=label).grid(row=i, column=0, sticky="w", pady=4)
            var = tk.StringVar(value=default)
            self._net_vars[key] = var
            ttk.Entry(net_frame, textvariable=var, width=30).grid(row=i, column=1, sticky="w", padx=10)

        # -- Bridge Tab --
        bridge_frame = ttk.Frame(notebook, padding=10)
        notebook.add(bridge_frame, text="Bridge")

        ttk.Label(bridge_frame, text="WiFi Adapter:").grid(row=0, column=0, sticky="w", pady=5)
        self._wifi_name = tk.StringVar(value=config.wifi_adapter.name)
        ttk.Entry(bridge_frame, textvariable=self._wifi_name, width=30).grid(row=0, column=1, sticky="w")

        ttk.Label(bridge_frame, text="Bridge Name:").grid(row=1, column=0, sticky="w", pady=5)
        self._bridge_name = tk.StringVar(value=config.bridge.name)
        ttk.Entry(bridge_frame, textvariable=self._bridge_name, width=30).grid(row=1, column=1, sticky="w")

        self._auto_create = tk.BooleanVar(value=config.bridge.auto_create)
        ttk.Checkbutton(bridge_frame, text="Auto-create bridge on device connect", variable=self._auto_create).grid(row=2, column=0, columnspan=2, sticky="w", pady=10)

        # -- App Tab --
        app_frame = ttk.Frame(notebook, padding=10)
        notebook.add(app_frame, text="Application")

        ttk.Label(app_frame, text="Poll Interval (sec):").grid(row=0, column=0, sticky="w", pady=5)
        self._poll_interval = tk.IntVar(value=config.app.poll_interval_seconds)
        ttk.Spinbox(app_frame, from_=1, to=60, textvariable=self._poll_interval, width=10).grid(row=0, column=1, sticky="w")

        self._start_minimized = tk.BooleanVar(value=config.app.start_minimized)
        ttk.Checkbutton(app_frame, text="Start minimized", variable=self._start_minimized).grid(row=1, column=0, columnspan=2, sticky="w", pady=5)

        self._auto_start = tk.BooleanVar(value=config.app.auto_start_with_windows)
        ttk.Checkbutton(app_frame, text="Auto-start with Windows", variable=self._auto_start).grid(row=2, column=0, columnspan=2, sticky="w", pady=5)

        ttk.Label(app_frame, text="Log Level:").grid(row=3, column=0, sticky="w", pady=5)
        self._log_level = tk.StringVar(value=config.app.log_level)
        ttk.Combobox(app_frame, textvariable=self._log_level, values=["DEBUG", "INFO", "WARNING", "ERROR"], state="readonly", width=10).grid(row=3, column=1, sticky="w")

        # -- Buttons --
        btn_frame = ttk.Frame(self._root)
        btn_frame.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btn_frame, text="Save", command=self._save).pack(side="right")
        ttk.Button(btn_frame, text="Cancel", command=self._root.destroy).pack(side="right", padx=5)

        self._root.mainloop()

    def _save(self):
        from app.config_manager import (
            AppConfig, TargetDevice, EthernetConfig,
            WifiConfig, BridgeConfig, AppSettings,
        )

        config = AppConfig(
            target_device=TargetDevice(
                hardware_id=self._hardware_id.get(),
                friendly_name=self._friendly_name.get(),
                mac_prefix=self._mac_prefix.get(),
                priority_ip=self._priority_ip.get(),
                detection_method=self._detection_method.get(),
            ),
            ethernet_adapter=EthernetConfig(
                name=self._net_vars["ethernet_name"].get(),
                static_ip=self._net_vars["static_ip"].get(),
                subnet_mask=self._net_vars["subnet_mask"].get(),
                gateway=self._net_vars["gateway"].get(),
                dns_primary=self._net_vars["dns_primary"].get(),
                dns_secondary=self._net_vars["dns_secondary"].get(),
            ),
            wifi_adapter=WifiConfig(name=self._wifi_name.get()),
            bridge=BridgeConfig(
                name=self._bridge_name.get(),
                auto_create=self._auto_create.get(),
            ),
            app=AppSettings(
                poll_interval_seconds=self._poll_interval.get(),
                start_minimized=self._start_minimized.get(),
                auto_start_with_windows=self._auto_start.get(),
                log_file="bridge_app.log",
                log_level=self._log_level.get(),
            ),
        )

        self._config_mgr.save(config)
        messagebox.showinfo("Settings", "Settings saved successfully!")

        if self._on_save:
            self._on_save(config)

        self._root.destroy()

    def _scan_devices(self):
        self._device_listbox.delete(0, tk.END)
        self._device_listbox.insert(tk.END, "Scanning...")
        self._root.update()

        def do_scan():
            try:
                from app.device_monitor import DeviceMonitor
                devices = DeviceMonitor.list_usb_devices()
                self._root.after(0, lambda: self._populate_devices(devices))
            except Exception as e:
                self._root.after(0, lambda: self._populate_devices([{"name": f"Error: {e}", "hardware_id": ""}]))

        threading.Thread(target=do_scan, daemon=True).start()

    def _populate_devices(self, devices):
        self._device_listbox.delete(0, tk.END)
        self._scanned_devices = devices
        for d in devices:
            self._device_listbox.insert(tk.END, f"{d['name']}  |  {d['hardware_id']}")

    def _on_device_select(self, event):
        selection = self._device_listbox.curselection()
        if not selection or not hasattr(self, "_scanned_devices"):
            return
        device = self._scanned_devices[selection[0]]
        self._hardware_id.set(device["hardware_id"])
        self._friendly_name.set(device["name"])
