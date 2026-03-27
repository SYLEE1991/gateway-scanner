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

        Two-phase detection for speed:
          Phase 1: Ping priority_ip (e.g. 192.168.220.206) directly → check ARP
                   This completes in ~1 second if the device is at the expected IP.
          Phase 2: If not found, do a full /24 subnet scan → check ARP again
                   This handles devices at unexpected IPs.
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

        priority_ip = self._config.target_device.priority_ip
        ethernet_cfg = self._config.ethernet_adapter

        # --- Phase 1: Quick check at priority IP ---
        if priority_ip:
            logger.debug("Phase 1: checking priority IP %s", priority_ip)
            try:
                subprocess.run(
                    ["ping", "-n", "1", "-w", "500", priority_ip],
                    capture_output=True, timeout=5,
                )
            except Exception:
                pass

            result = self._find_mac_in_arp(prefix_dash, raw)
            if result:
                logger.info("Phase 1 hit: device found at priority IP")
                return result

        # --- Phase 2: Full subnet scan ---
        logger.debug("Phase 2: full subnet scan")
        self._populate_arp_table(ethernet_cfg.static_ip, ethernet_cfg.subnet_mask)

        result = self._find_mac_in_arp(prefix_dash, raw)
        if result:
            logger.info("Phase 2 hit: device found via subnet scan")
            return result

        return None

    def _find_mac_in_arp(self, prefix_dash: str, raw_prefix: str):
        """Search ARP/Neighbor table for a matching MAC prefix.

        Only searches entries on the configured ethernet adapter,
        ignoring WiFi, Bluetooth, and other interfaces.

        Returns DetectedDevice if found, None otherwise.
        """
        import subprocess

        ethernet_name = self._config.ethernet_adapter.name
        ethernet_ip = self._config.ethernet_adapter.static_ip

        # Method 1: Get-NetNeighbor filtered by ethernet adapter (most reliable)
        try:
            ps_cmd = (
                f"Get-NetNeighbor -InterfaceAlias '{ethernet_name}' -ErrorAction SilentlyContinue | "
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
                        logger.info("Found target device (Ethernet only): MAC=%s IP=%s", parts[1].upper(), parts[0])
                        return DetectedDevice(ip=parts[0], mac=parts[1].upper(), method="mac_address")
        except Exception:
            logger.exception("Get-NetNeighbor query failed")

        # Method 2: arp -a filtered by ethernet adapter's IP (fallback)
        try:
            result = subprocess.run(
                ["arp", "-a", "-N", ethernet_ip],
                capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.split("\n"):
                line = line.strip()
                parts = line.split()
                if len(parts) >= 2:
                    mac = parts[1].upper()
                    if mac.startswith(prefix_dash):
                        logger.info("Found target device (arp -N): MAC=%s IP=%s", mac, parts[0])
                        return DetectedDevice(ip=parts[0], mac=mac, method="mac_address")
        except Exception:
            logger.exception("ARP table query failed")

        return None

    @staticmethod
    def _populate_arp_table(local_ip: str, subnet_mask: str):
        """Scan the local subnet to populate the ARP table.

        Uses parallel ping across the full /24 subnet so that devices
        like the Infortab gateway (e.g. 192.168.220.72) are discovered
        regardless of their host address.
        """
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

            # Parallel ping sweep of the entire /24 subnet
            # This quickly populates the ARP table for all live hosts
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
            pass  # Best-effort; ARP table may already have entries

    def _check_ethernet_link(self, w) -> bool:
        """Check if the configured ethernet adapter has an active link."""
        ethernet_name = self._config.ethernet_adapter.name
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
