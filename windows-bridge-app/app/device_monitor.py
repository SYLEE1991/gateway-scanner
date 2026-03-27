import time
import threading
import logging

logger = logging.getLogger(__name__)


class DetectedDevice:
    """Info about a detected device."""

    def __init__(self, ip: str = "", mac: str = "", method: str = ""):
        self.ip = ip
        self.mac = mac
        self.method = method  # detection method that found it

    def __repr__(self):
        return f"DetectedDevice(ip={self.ip!r}, mac={self.mac!r}, method={self.method!r})"


class DeviceMonitor:
    """Polls WMI for target device presence and fires callbacks on state changes."""

    def __init__(self, config, on_device_connected, on_device_disconnected):
        self._config = config
        self._on_connected = on_device_connected
        self._on_disconnected = on_device_disconnected
        self._device_present = False
        self._detected_device = None  # DetectedDevice when connected
        self._running = False
        self._thread = None
        # Resolve actual adapter name once (handles "Ethernet" vs "이더넷" etc.)
        self._resolved_adapter_name = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info("Device monitor started (polling every %ds)", self._config.app.poll_interval_seconds)

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("Device monitor stopped")

    @property
    def is_device_present(self):
        return self._device_present

    @property
    def detected_device(self):
        """Returns DetectedDevice info (ip, mac) if device is present, else None."""
        return self._detected_device

    def _poll_loop(self):
        # WMI uses COM; must initialize COM on this thread
        import pythoncom
        pythoncom.CoInitialize()
        try:
            import wmi
            w = wmi.WMI()
            while self._running:
                try:
                    device_info = self._check_device(w)
                    found = device_info is not None
                    if found and not self._device_present:
                        self._device_present = True
                        self._detected_device = device_info
                        logger.info("Target device CONNECTED: %s", device_info)
                        self._on_connected(device_info)
                    elif not found and self._device_present:
                        self._device_present = False
                        self._detected_device = None
                        logger.info("Target device DISCONNECTED")
                        self._on_disconnected()
                except Exception:
                    logger.exception("Error during device polling")
                time.sleep(self._config.app.poll_interval_seconds)
        finally:
            pythoncom.CoUninitialize()

    def _check_device(self, w):
        """Check for target device. Returns DetectedDevice if found, None otherwise."""
        device_cfg = self._config.target_device

        if device_cfg.detection_method == "hardware_id":
            query = (
                f"SELECT * FROM Win32_PnPEntity "
                f"WHERE PNPDeviceID LIKE '%{device_cfg.hardware_id}%'"
            )
            results = w.query(query)
            if results:
                return DetectedDevice(method="hardware_id")
            return None

        elif device_cfg.detection_method == "friendly_name":
            query = (
                f"SELECT * FROM Win32_PnPEntity "
                f"WHERE Name LIKE '%{device_cfg.friendly_name}%'"
            )
            results = w.query(query)
            if results:
                return DetectedDevice(method="friendly_name")
            return None

        elif device_cfg.detection_method == "mac_address":
            return self._check_mac_address(w, device_cfg.mac_prefix)

        elif device_cfg.detection_method == "ethernet_link":
            if self._check_ethernet_link(w):
                return DetectedDevice(method="ethernet_link")
            return None

        return None

    def _check_mac_address(self, w, mac_prefix: str):
        """Check if a device with matching MAC prefix is on the ethernet link.

        Returns DetectedDevice(ip, mac) if found, None otherwise.

        Detection strategy:
          1. Check if the adapter already has an IP → scan that subnet first
          2. Try priority_ip (factory default) with a quick ping
          3. Cycle through scan_subnets from config: set PC IP on each subnet,
             ping sweep, and check ARP for the target MAC.
             Stops as soon as the device is found.
        """
        import subprocess

        if not self._check_ethernet_link(w):
            return None

        # Normalize MAC prefix
        raw = mac_prefix.upper().replace(":", "").replace("-", "")
        if len(raw) < 6:
            logger.warning("MAC prefix too short: %s", mac_prefix)
            return None
        prefix_dash = f"{raw[0:2]}-{raw[2:4]}-{raw[4:6]}"

        adapter_name = self._get_adapter_name(w)
        ethernet_cfg = self._config.ethernet_adapter
        device_cfg = self._config.target_device

        # --- Phase 1: Check current adapter IP (already on a subnet?) ---
        current_ip = self._get_adapter_current_ip(adapter_name)
        if current_ip:
            logger.debug("Phase 1: adapter already has IP %s, scanning that subnet", current_ip)
            self._populate_arp_table(current_ip, ethernet_cfg.subnet_mask)
            result = self._find_mac_in_arp(prefix_dash, raw, adapter_name, current_ip)
            if result:
                return result

        # --- Phase 2: Quick check priority_ip ---
        priority_ip = device_cfg.priority_ip
        if priority_ip:
            logger.debug("Phase 2: quick ping to priority IP %s", priority_ip)
            try:
                subprocess.run(
                    ["ping", "-n", "1", "-w", "500", priority_ip],
                    capture_output=True, timeout=5,
                )
            except Exception:
                pass
            result = self._find_mac_in_arp(prefix_dash, raw, adapter_name, current_ip)
            if result:
                return result

        # --- Phase 3: Cycle through scan_subnets ---
        scan_subnets = device_cfg.scan_subnets
        if not scan_subnets:
            return None

        tried_subnets = set()
        if current_ip:
            # Don't re-scan the subnet we already tried
            parts = [int(x) for x in current_ip.split(".")]
            mask = [int(x) for x in ethernet_cfg.subnet_mask.split(".")]
            tried_subnets.add(tuple(parts[i] & mask[i] for i in range(4)))

        for subnet in scan_subnets:
            # Calculate subnet base to avoid duplicates
            s_parts = [int(x) for x in subnet.ip.split(".")]
            mask = [int(x) for x in ethernet_cfg.subnet_mask.split(".")]
            s_base = tuple(s_parts[i] & mask[i] for i in range(4))

            if s_base in tried_subnets:
                continue
            tried_subnets.add(s_base)

            logger.info("Phase 3: trying subnet %s (PC IP: %s)", s_base, subnet.ip)

            # Set PC IP to this subnet
            ok = self._set_static_ip(adapter_name, subnet.ip, ethernet_cfg.subnet_mask, subnet.gateway)
            if not ok:
                continue

            time.sleep(2)  # Wait for IP to become effective

            # Quick scan: priority IP first, then sweep
            if priority_ip:
                try:
                    subprocess.run(
                        ["ping", "-n", "1", "-w", "500", priority_ip],
                        capture_output=True, timeout=5,
                    )
                except Exception:
                    pass
                result = self._find_mac_in_arp(prefix_dash, raw, adapter_name, subnet.ip)
                if result:
                    return result

            # Full subnet sweep
            self._populate_arp_table(subnet.ip, ethernet_cfg.subnet_mask)
            result = self._find_mac_in_arp(prefix_dash, raw, adapter_name, subnet.ip)
            if result:
                return result

        logger.debug("Device not found on any scan subnet")
        return None

    def _get_adapter_current_ip(self, adapter_name: str):
        """Get the actual current IPv4 address of the adapter.

        Returns the IP string, or None if no valid IP.
        Skips APIPA addresses (169.254.x.x).
        """
        import subprocess

        try:
            ps_cmd = (
                f"Get-NetIPAddress -InterfaceAlias '{adapter_name}' -AddressFamily IPv4 -ErrorAction SilentlyContinue | "
                f"Select-Object -Property IPAddress | Format-Table -HideTableHeaders"
            )
            result = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.split("\n"):
                ip = line.strip()
                if ip and not ip.startswith("169.254."):
                    return ip
        except Exception:
            pass
        return None

    @staticmethod
    def _set_static_ip(adapter_name: str, ip: str, mask: str, gateway: str) -> bool:
        """Set static IP on the adapter via netsh."""
        import subprocess

        try:
            cmd = [
                "netsh", "interface", "ip", "set", "address",
                f"name={adapter_name}",
                "source=static",
                f"addr={ip}",
                f"mask={mask}",
                f"gateway={gateway}",
                "gwmetric=1",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode == 0:
                logger.info("Static IP %s set on '%s'", ip, adapter_name)
                return True
            else:
                logger.error("Failed to set static IP %s: %s", ip, result.stderr.strip())
                return False
        except Exception:
            logger.exception("Exception setting static IP %s", ip)
            return False

    def _find_mac_in_arp(self, prefix_dash: str, raw_prefix: str,
                         adapter_name: str, adapter_ip: str):
        """Search ARP/Neighbor table for a matching MAC prefix.

        Only searches entries on the specified ethernet adapter.
        Returns DetectedDevice if found, None otherwise.
        """
        import subprocess

        # Method 1: Get-NetNeighbor filtered by ethernet adapter (most reliable)
        try:
            ps_cmd = (
                f"Get-NetNeighbor -InterfaceAlias '{adapter_name}' -ErrorAction SilentlyContinue | "
                f"Where-Object {{ $_.State -ne 'Unreachable' }} | "
                f"Select-Object -Property IPAddress,LinkLayerAddress | "
                f"Format-Table -HideTableHeaders"
            )
            result = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=15,
            )
            for line in result.stdout.split("\n"):
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    mac_clean = parts[1].upper().replace("-", "").replace(":", "")
                    if mac_clean.startswith(raw_prefix[:6]):
                        logger.info("Found target device: MAC=%s IP=%s", parts[1].upper(), parts[0])
                        return DetectedDevice(ip=parts[0], mac=parts[1].upper(), method="mac_address")
        except Exception:
            logger.exception("Get-NetNeighbor query failed")

        # Method 2: arp -a filtered by adapter IP (fallback)
        if adapter_ip:
            try:
                result = subprocess.run(
                    ["arp", "-a", "-N", adapter_ip],
                    capture_output=True, text=True, timeout=10,
                )
                for line in result.stdout.split("\n"):
                    line = line.strip()
                    parts = line.split()
                    if len(parts) >= 2:
                        mac = parts[1].upper()
                        if mac.startswith(prefix_dash):
                            logger.info("Found target device (arp): MAC=%s IP=%s", mac, parts[0])
                            return DetectedDevice(ip=parts[0], mac=mac, method="mac_address")
            except Exception:
                logger.exception("ARP table query failed")

        return None

    @staticmethod
    def _populate_arp_table(local_ip: str, subnet_mask: str):
        """Scan the local subnet to populate the ARP table."""
        import subprocess
        import concurrent.futures

        try:
            ip_parts = [int(x) for x in local_ip.split(".")]
            mask_parts = [int(x) for x in subnet_mask.split(".")]
            base = [ip_parts[i] & mask_parts[i] for i in range(4)]

            # Broadcast ping first
            broadcast_parts = [(ip_parts[i] | (~mask_parts[i] & 0xFF)) for i in range(4)]
            broadcast = ".".join(str(x) for x in broadcast_parts)
            subprocess.run(
                ["ping", "-n", "1", "-w", "500", broadcast],
                capture_output=True, timeout=5,
            )

            def ping_host(host_id):
                target = base.copy()
                target[3] = host_id
                target_ip = ".".join(str(x) for x in target)
                if target_ip != local_ip:
                    subprocess.run(
                        ["ping", "-n", "1", "-w", "200", target_ip],
                        capture_output=True, timeout=3,
                    )

            with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
                pool.map(ping_host, range(1, 255))

        except Exception:
            pass  # Best-effort

    def _get_adapter_name(self, w) -> str:
        """Get the resolved adapter name, detecting it once on first call.

        Handles locale differences: config may say "Ethernet" but the actual
        adapter could be "이더넷" (Korean), "이더넷 2", "Ethernet 2", etc.
        """
        if self._resolved_adapter_name:
            return self._resolved_adapter_name

        config_name = self._config.ethernet_adapter.name

        # Check if config name works
        adapters = w.Win32_NetworkAdapter(NetConnectionID=config_name)
        if adapters:
            self._resolved_adapter_name = config_name
            return config_name

        # Config name not found - search for a wired ethernet adapter
        logger.info("Adapter '%s' not found via WMI, searching for wired ethernet adapter...", config_name)
        all_adapters = w.Win32_NetworkAdapter()
        for adapter in all_adapters:
            # PhysicalAdapter=True, AdapterTypeId=0 (Ethernet 802.3)
            if (adapter.PhysicalAdapter and
                    adapter.AdapterTypeId == 0 and
                    adapter.NetConnectionID):
                actual_name = adapter.NetConnectionID
                logger.info("Found wired ethernet adapter: '%s' (replacing config '%s')", actual_name, config_name)
                self._resolved_adapter_name = actual_name
                return actual_name

        # Fallback
        logger.warning("No wired ethernet adapter found, using config name '%s'", config_name)
        self._resolved_adapter_name = config_name
        return config_name

    def _check_ethernet_link(self, w) -> bool:
        """Check if the configured ethernet adapter has an active link."""
        ethernet_name = self._get_adapter_name(w)
        adapters = w.Win32_NetworkAdapter(NetConnectionID=ethernet_name)
        for adapter in adapters:
            # NetConnectionStatus: 2 = Connected
            if adapter.NetConnectionStatus == 2:
                return True
        return False

    @staticmethod
    def list_usb_devices():
        """Utility: list all USB PnP devices (for settings GUI)."""
        import pythoncom
        pythoncom.CoInitialize()
        try:
            import wmi
            w = wmi.WMI()
            devices = w.Win32_PnPEntity()
            result = []
            for d in devices:
                if d.PNPDeviceID and "USB" in d.PNPDeviceID:
                    result.append({
                        "name": d.Name or "(unknown)",
                        "hardware_id": d.PNPDeviceID,
                        "status": d.Status,
                    })
            return result
        finally:
            pythoncom.CoUninitialize()
