import tkinter as tk
from tkinter import ttk, messagebox
import threading
import subprocess
import logging

logger = logging.getLogger(__name__)


class ScanWindow:
    """Startup window with scan mode selection and device results."""

    def __init__(self, config):
        self._config = config
        self._root = None
        self._found_devices = []
        self._scanning = False
        self._scan_mode = None  # "all" or "direct"

    def run(self):
        """Show scan window. Blocks until closed. Returns list of found devices."""
        self._root = tk.Tk()
        self._root.title("Gateway Device Scanner")
        self._root.geometry("620x520")
        self._root.resizable(False, False)
        self._center_window()

        # --- Header ---
        header = ttk.Frame(self._root)
        header.pack(fill="x", padx=15, pady=(15, 5))
        ttk.Label(header, text="Gateway Device Scanner", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        info_text = f"MAC Filter: {self._config.target_device.mac_prefix}"
        ttk.Label(header, text=info_text, foreground="gray").pack(anchor="w", pady=(2, 0))

        # --- Scan Mode Selection ---
        mode_frame = ttk.LabelFrame(self._root, text="Scan Mode", padding=10)
        mode_frame.pack(fill="x", padx=15, pady=10)

        ttk.Button(
            mode_frame,
            text="Network Scan\n(All interfaces)",
            command=lambda: self._start_scan("all"),
        ).pack(side="left", expand=True, fill="both", padx=(0, 5), ipady=15)

        ttk.Button(
            mode_frame,
            text="Direct Connection Scan\n(Ethernet only)",
            command=lambda: self._start_scan("direct"),
        ).pack(side="left", expand=True, fill="both", padx=(5, 0), ipady=15)

        # --- Status ---
        status_frame = ttk.Frame(self._root)
        status_frame.pack(fill="x", padx=15, pady=(5, 3))

        self._status_label = ttk.Label(status_frame, text="Select scan mode to start.", font=("Segoe UI", 10))
        self._status_label.pack(side="left")

        self._count_label = ttk.Label(status_frame, text="", font=("Segoe UI", 10, "bold"))
        self._count_label.pack(side="right")

        # --- Progress Bar ---
        self._progress = ttk.Progressbar(self._root, mode="determinate", length=590, value=0)
        self._progress.pack(padx=15, pady=(0, 5))

        # --- Device List ---
        list_frame = ttk.Frame(self._root)
        list_frame.pack(fill="both", expand=True, padx=15, pady=(0, 5))

        columns = ("ip", "mac", "interface")
        self._tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=8)
        self._tree.heading("ip", text="IP Address")
        self._tree.heading("mac", text="MAC Address")
        self._tree.heading("interface", text="Interface")
        self._tree.column("ip", width=150, anchor="center")
        self._tree.column("mac", width=200, anchor="center")
        self._tree.column("interface", width=200, anchor="center")

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=scrollbar.set)
        self._tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # --- Bottom Buttons ---
        btn_frame = ttk.Frame(self._root)
        btn_frame.pack(fill="x", padx=15, pady=(5, 15))

        self._rescan_btn = ttk.Button(btn_frame, text="Re-Scan", command=self._rescan, state="disabled")
        self._rescan_btn.pack(side="left")

        self._connect_btn = ttk.Button(btn_frame, text="Connect to Device", command=self._connect_to_device, state="disabled")
        self._connect_btn.pack(side="left", padx=10)

        ttk.Button(btn_frame, text="Close", command=self._root.destroy).pack(side="right")

        self._mode_label = ttk.Label(btn_frame, text="", foreground="gray")
        self._mode_label.pack(side="right", padx=10)

        self._tree.bind("<<TreeviewSelect>>", self._on_device_select)

        self._root.mainloop()
        return self._found_devices

    # ---- Device Selection & Connect ----

    def _on_device_select(self, event):
        selection = self._tree.selection()
        if selection:
            self._connect_btn.config(state="normal")
        else:
            self._connect_btn.config(state="disabled")

    def _connect_to_device(self):
        """Change PC ethernet IP to communicate with the selected device.

        Sets PC IP to device_ip - 1, copies the device's subnet/gateway.
        """
        selection = self._tree.selection()
        if not selection:
            return

        values = self._tree.item(selection[0])["values"]
        device_ip = values[0]
        device_mac = values[1]
        device_iface = values[2]

        # Calculate PC IP = device IP - 1
        try:
            parts = device_ip.split(".")
            ip_parts = [int(x) for x in parts]
            # PC IP is device IP - 1
            pc_parts = ip_parts.copy()
            pc_parts[3] = pc_parts[3] - 1
            if pc_parts[3] < 1:
                pc_parts[3] = pc_parts[3] + 2  # if device is .1, PC becomes .2
            pc_ip = ".".join(str(x) for x in pc_parts)

            # Use same subnet mask and gateway from device's subnet
            subnet_mask = self._config.ethernet_adapter.subnet_mask
            # Gateway = subnet base + .1
            base = [ip_parts[i] & int(x) for i, x in enumerate(subnet_mask.split("."))]
            base[3] = 1
            gateway = ".".join(str(x) for x in base)

        except Exception as e:
            messagebox.showerror("Error", f"Failed to calculate IP: {e}")
            return

        ethernet_name = self._config.ethernet_adapter.name

        msg = (
            f"Change PC ethernet settings to connect to this device?\n\n"
            f"  Device:     {device_ip} ({device_mac})\n"
            f"  Interface:  {device_iface}\n\n"
            f"  PC Ethernet IP:  {pc_ip}\n"
            f"  Subnet Mask:     {subnet_mask}\n"
            f"  Gateway:         {gateway}\n"
            f"  Adapter:         {ethernet_name}"
        )

        if not messagebox.askyesno("Confirm IP Change", msg):
            return

        self._status_label.config(text=f"Setting ethernet IP to {pc_ip}...")

        def do_set_ip():
            from app.network_config import NetworkConfigurator
            net = NetworkConfigurator()

            ok = net.set_static_ip(ethernet_name, pc_ip, subnet_mask, gateway)
            if ok:
                net.set_dns(
                    ethernet_name,
                    self._config.ethernet_adapter.dns_primary,
                    self._config.ethernet_adapter.dns_secondary,
                )

            self._root.after(0, lambda: self._on_ip_set_complete(ok, pc_ip, device_ip))

        threading.Thread(target=do_set_ip, daemon=True).start()

    def _on_ip_set_complete(self, success, pc_ip, device_ip):
        if success:
            self._status_label.config(text=f"PC IP set to {pc_ip} - Ready to communicate with {device_ip}")
            messagebox.showinfo("Success", f"PC ethernet IP changed to {pc_ip}\nYou can now communicate with {device_ip}")
        else:
            self._status_label.config(text="Failed to set IP")
            messagebox.showerror("Error", "Failed to change ethernet IP. Check administrator privileges.")

    # ---- Scan Control ----

    def _start_scan(self, mode: str):
        if self._scanning:
            return

        self._scan_mode = mode
        self._scanning = True
        self._tree.delete(*self._tree.get_children())
        self._found_devices = []
        self._rescan_btn.config(state="disabled")
        self._connect_btn.config(state="disabled")
        self._count_label.config(text="")
        self._progress.config(mode="indeterminate")
        self._progress.start(15)

        if mode == "all":
            self._status_label.config(text="Scanning all networks...")
            self._mode_label.config(text="Mode: Network Scan")
        else:
            self._status_label.config(text="Scanning ethernet direct connection...")
            self._mode_label.config(text="Mode: Direct Connection")

        threading.Thread(target=self._do_scan, args=(mode,), daemon=True).start()

    def _rescan(self):
        if self._scan_mode:
            self._start_scan(self._scan_mode)

    # ---- Scan Logic ----

    def _do_scan(self, mode: str):
        import concurrent.futures

        ethernet_cfg = self._config.ethernet_adapter
        mac_prefix = self._config.target_device.mac_prefix.upper().replace(":", "").replace("-", "")
        prefix_dash = f"{mac_prefix[0:2]}-{mac_prefix[2:4]}-{mac_prefix[4:6]}"

        local_ip = ethernet_cfg.static_ip
        ethernet_name = ethernet_cfg.name

        if mode == "direct":
            # Direct Connection: neighbor table에서 이더넷 장비만 MAC으로 찾음
            self._update_status("Checking ethernet adapter neighbors...")
            self._collect_devices(prefix_dash, mac_prefix, mode, ethernet_name, local_ip)

            if not self._found_devices:
                self._update_status("Sending broadcast to discover devices...")
                try:
                    subprocess.run(
                        ["ping", "-n", "2", "-w", "1000", "255.255.255.255"],
                        capture_output=True, timeout=5,
                    )
                except Exception:
                    pass

                priority_ip = self._config.target_device.priority_ip
                if priority_ip:
                    self._update_status(f"Pinging {priority_ip}...")
                    try:
                        subprocess.run(
                            ["ping", "-n", "2", "-w", "1000", priority_ip],
                            capture_output=True, timeout=5,
                        )
                    except Exception:
                        pass

                self._update_status("Re-checking neighbors...")
                self._collect_devices(prefix_dash, mac_prefix, mode, ethernet_name, local_ip)

        else:
            # Network Scan: 모든 인터페이스에서 전체 검색
            ip_parts = [int(x) for x in local_ip.split(".")]
            mask_parts = [int(x) for x in ethernet_cfg.subnet_mask.split(".")]
            base = [ip_parts[i] & mask_parts[i] for i in range(4)]

            priority_ip = self._config.target_device.priority_ip
            if priority_ip:
                self._update_status(f"Checking priority IP: {priority_ip}...")
                try:
                    subprocess.run(
                        ["ping", "-n", "1", "-w", "500", priority_ip],
                        capture_output=True, timeout=5,
                    )
                except Exception:
                    pass
                self._collect_devices(prefix_dash, mac_prefix, mode, ethernet_name, local_ip)

            total = 254
            scanned = [0]
            self._update_status("Scanning full subnet...")

            def ping_host(host_id):
                target = base.copy()
                target[3] = host_id
                target_ip = ".".join(str(x) for x in target)
                if target_ip != local_ip:
                    try:
                        subprocess.run(
                            ["ping", "-n", "1", "-w", "200", target_ip],
                            capture_output=True, timeout=3,
                        )
                    except Exception:
                        pass
                scanned[0] += 1
                if scanned[0] % 25 == 0:
                    pct = int(scanned[0] / total * 100)
                    self._update_status(f"Scanning... {pct}% ({scanned[0]}/{total})")

            with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
                pool.map(ping_host, range(1, 255))

            self._collect_devices(prefix_dash, mac_prefix, mode, ethernet_name, local_ip)

        self._update_status("Scan complete")
        self._root.after(0, self._scan_complete)

    def _collect_devices(self, prefix_dash, raw_prefix, mode, ethernet_name, ethernet_ip):
        """Collect matching devices with interface info from neighbor table."""
        seen_ips = {d["ip"] for d in self._found_devices}

        # Get-NetNeighbor with InterfaceAlias
        try:
            if mode == "direct":
                ps_cmd = (
                    f"Get-NetNeighbor -InterfaceAlias '{ethernet_name}' -ErrorAction SilentlyContinue | "
                    f"Where-Object {{ $_.State -ne 'Unreachable' }} | "
                    f"Select-Object -Property IPAddress,LinkLayerAddress,InterfaceAlias | "
                    f"Format-Table -HideTableHeaders"
                )
            else:
                ps_cmd = (
                    "Get-NetNeighbor | Where-Object { $_.State -ne 'Unreachable' } | "
                    "Select-Object -Property IPAddress,LinkLayerAddress,InterfaceAlias | "
                    "Format-Table -HideTableHeaders"
                )

            result = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=15,
            )
            for line in result.stdout.split("\n"):
                line = line.strip()
                if not line:
                    continue
                # Format: IPAddress  LinkLayerAddress  InterfaceAlias
                # InterfaceAlias may contain spaces, so split carefully
                parts = line.split(None, 2)  # split into max 3 parts
                if len(parts) >= 2:
                    ip_addr = parts[0]
                    mac_raw = parts[1].upper().replace("-", "").replace(":", "")
                    iface = parts[2].strip() if len(parts) >= 3 else "Unknown"

                    if mac_raw.startswith(raw_prefix[:6]) and ip_addr not in seen_ips:
                        mac_display = parts[1].upper()
                        device = {"ip": ip_addr, "mac": mac_display, "interface": iface}
                        self._found_devices.append(device)
                        seen_ips.add(ip_addr)
                        self._root.after(0, lambda d=device: self._add_device_to_tree(d))
        except Exception:
            logger.exception("Get-NetNeighbor failed")

        # arp fallback (no interface info available)
        try:
            if mode == "direct":
                cmd = ["arp", "-a", "-N", ethernet_ip]
                fallback_iface = ethernet_name
            else:
                cmd = ["arp", "-a"]
                fallback_iface = "-"

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            for line in result.stdout.split("\n"):
                line = line.strip()
                parts = line.split()
                if len(parts) >= 2:
                    mac = parts[1].upper()
                    if mac.startswith(prefix_dash) and parts[0] not in seen_ips:
                        device = {"ip": parts[0], "mac": mac, "interface": fallback_iface}
                        self._found_devices.append(device)
                        seen_ips.add(parts[0])
                        self._root.after(0, lambda d=device: self._add_device_to_tree(d))
        except Exception:
            logger.exception("ARP check failed")

    # ---- UI Helpers ----

    def _add_device_to_tree(self, device):
        self._tree.insert("", "end", values=(device["ip"], device["mac"], device["interface"]))
        self._count_label.config(text=f"{len(self._found_devices)} device(s)")

    def _update_status(self, text: str):
        self._root.after(0, lambda: self._status_label.config(text=text))

    def _scan_complete(self):
        self._scanning = False
        self._progress.stop()
        self._progress.config(mode="determinate", value=100 if self._found_devices else 0)
        self._rescan_btn.config(state="normal")

        count = len(self._found_devices)
        mode_str = "Network" if self._scan_mode == "all" else "Direct Connection"
        if count == 0:
            self._status_label.config(text=f"{mode_str} scan complete - No devices found")
        else:
            self._status_label.config(text=f"{mode_str} scan complete")
        self._count_label.config(text=f"{count} device(s) found")

    def _center_window(self):
        self._root.update_idletasks()
        w = self._root.winfo_width()
        h = self._root.winfo_height()
        x = (self._root.winfo_screenwidth() // 2) - (w // 2)
        y = (self._root.winfo_screenheight() // 2) - (h // 2)
        self._root.geometry(f"+{x}+{y}")
