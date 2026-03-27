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

        Uses ARP packet sniffing (Layer 2) to discover the device's MAC and IP
        without requiring the PC to be on the same subnet. This works because
        devices send ARP packets (gratuitous ARP, ARP requests for gateway)
        regardless of the PC's IP configuration.

        Detection phases:
          Phase 1: Sniff ARP packets on the ethernet interface for the target MAC.
                   This is subnet-agnostic and catches devices on any IP range.
          Phase 2: If ARP sniffing found the device, set PC IP to the same subnet
                   and verify connectivity.
          Fallback: If scapy is unavailable, fall back to the legacy ping/ARP method
                   using the configured static IP.
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

        ethernet_cfg = self._config.ethernet_adapter

        # --- Phase 1: ARP sniffing (subnet-agnostic) ---
        result = self._sniff_arp_for_device(raw, ethernet_cfg.name)
        if result:
            logger.info("ARP sniff hit: device found at %s (MAC %s)", result.ip, result.mac)
            return result

        # --- Phase 2: Legacy ping/ARP fallback ---
        # If ARP sniffing didn't find the device (no ARP traffic yet),
        # try the ping-based approach with the configured static IP.
        logger.debug("ARP sniff found nothing, falling back to ping/ARP scan")
        self._ensure_subnet_ip(ethernet_cfg)

        priority_ip = self._config.target_device.priority_ip
        if priority_ip:
            logger.debug("Fallback Phase 1: checking priority IP %s", priority_ip)
            try:
                subprocess.run(
                    ["ping", "-n", "1", "-w", "500", priority_ip],
                    capture_output=True, timeout=5,
                )
            except Exception:
                pass

            result = self._find_mac_in_arp(prefix_dash, raw)
            if result:
                return result

        logger.debug("Fallback Phase 2: full subnet scan")
        self._populate_arp_table(ethernet_cfg.static_ip, ethernet_cfg.subnet_mask)

        return self._find_mac_in_arp(prefix_dash, raw)

    def _sniff_arp_for_device(self, raw_prefix: str, adapter_name: str):
        """Capture ARP packets using Windows built-in pktmon (no install required).

        pktmon captures at the NDIS level, so ARP packets are visible regardless
        of the PC's IP configuration. The captured ETL file contains raw packet
        data which we parse directly for the ARP signature + target MAC prefix.

        Available on Windows 10 1809+ and Windows 11. Requires admin (already have).
        Returns DetectedDevice if found within timeout, None otherwise.
        """
        import subprocess
        import tempfile
        import os

        mac_bytes = bytes.fromhex(raw_prefix[:6])
        etl_file = os.path.join(tempfile.gettempdir(), "gw_scanner_arp.etl")

        try:
            # Stop any leftover capture and clean filters
            subprocess.run(["pktmon", "stop"], capture_output=True, timeout=5)
            subprocess.run(["pktmon", "filter", "remove"], capture_output=True, timeout=5)
            try:
                os.remove(etl_file)
            except OSError:
                pass

            # Start packet capture (all packets, short timeout keeps file small)
            logger.debug("pktmon: starting ARP capture on '%s' (timeout=5s)", adapter_name)
            r = subprocess.run(
                ["pktmon", "start", "-c", "--pkt-size", "128", "-f", etl_file],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode != 0:
                # Try older pktmon syntax (Windows 10 1809-1903)
                r = subprocess.run(
                    ["pktmon", "start", "--capture", "--pkt-size", "128", "--log-file", etl_file],
                    capture_output=True, text=True, timeout=5,
                )
            if r.returncode != 0:
                logger.warning("pktmon start failed: %s", r.stderr.strip())
                return None

            # Wait for device ARP traffic
            time.sleep(5)

            # Stop capture
            subprocess.run(["pktmon", "stop"], capture_output=True, timeout=5)

            if not os.path.exists(etl_file):
                logger.debug("pktmon: no ETL file produced")
                return None

            # Parse raw ETL binary for ARP packets matching our MAC prefix
            return self._parse_etl_for_arp(etl_file, mac_bytes)

        except FileNotFoundError:
            logger.debug("pktmon not available on this system")
            return None
        except Exception:
            logger.exception("pktmon ARP capture failed")
            return None
        finally:
            subprocess.run(["pktmon", "stop"], capture_output=True, timeout=5)
            subprocess.run(["pktmon", "filter", "remove"], capture_output=True, timeout=5)
            try:
                os.remove(etl_file)
            except OSError:
                pass

    @staticmethod
    def _parse_etl_for_arp(etl_file: str, mac_prefix_bytes: bytes):
        """Parse raw ETL file binary for ARP packets with a matching MAC prefix.

        ARP over Ethernet frame layout (after Ethernet header):
          EtherType  : 08 06               (ARP)
          HW Type    : 00 01               (Ethernet)
          Proto Type : 08 00               (IPv4)
          HW Size    : 06
          Proto Size : 04
          Opcode     : 00 01/02            (Request/Reply)
          Sender MAC : 6 bytes             ← we match this
          Sender IP  : 4 bytes             ← we extract this

        The 8-byte ARP signature (EtherType + header) is highly specific,
        making false positives in ETL metadata extremely unlikely.
        """
        # ARP signature: EtherType(0806) + HWType(0001) + ProtoType(0800) + HWSize(06) + ProtoSize(04)
        arp_sig = b'\x08\x06\x00\x01\x08\x00\x06\x04'

        with open(etl_file, "rb") as f:
            data = f.read()

        pos = 0
        while True:
            idx = data.find(arp_sig, pos)
            if idx == -1:
                break

            # After arp_sig(8 bytes): Opcode(2 bytes) + Sender MAC(6 bytes) + Sender IP(4 bytes)
            sender_mac_offset = idx + 8 + 2  # skip sig + opcode
            sender_ip_offset = sender_mac_offset + 6

            if sender_ip_offset + 4 <= len(data):
                sender_mac_3 = data[sender_mac_offset:sender_mac_offset + 3]
                if sender_mac_3 == mac_prefix_bytes:
                    full_mac = data[sender_mac_offset:sender_mac_offset + 6]
                    sender_ip = data[sender_ip_offset:sender_ip_offset + 4]

                    ip_str = ".".join(str(b) for b in sender_ip)
                    mac_str = "-".join(f"{b:02X}" for b in full_mac)

                    # Sanity check: IP should be a valid private/routable address
                    if sender_ip[0] not in (0, 127, 255):
                        logger.info("pktmon: found device MAC=%s IP=%s", mac_str, ip_str)
                        return DetectedDevice(ip=ip_str, mac=mac_str, method="mac_address")

            pos = idx + 1

        logger.debug("pktmon: no matching ARP packets found in capture")
        return None

    def _ensure_subnet_ip(self, ethernet_cfg):
        """Set static IP on ethernet adapter if it doesn't already have one on the device's subnet.

        Called as a fallback when ARP sniffing didn't find the device.
        Uses the configured static IP to enable ping/ARP-based detection.
        """
        import subprocess

        adapter_name = self._resolved_adapter_name or ethernet_cfg.name
        target_ip = ethernet_cfg.static_ip
        target_mask = ethernet_cfg.subnet_mask

        # Calculate target subnet
        target_parts = [int(x) for x in target_ip.split(".")]
        mask_parts = [int(x) for x in target_mask.split(".")]
        target_subnet = tuple(target_parts[i] & mask_parts[i] for i in range(4))

        # Check if already on the target subnet
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
                if not ip:
                    continue
                try:
                    ip_parts = [int(x) for x in ip.split(".")]
                    ip_subnet = tuple(ip_parts[i] & mask_parts[i] for i in range(4))
                    if ip_subnet == target_subnet:
                        logger.debug("Adapter '%s' already has IP %s on target subnet", adapter_name, ip)
                        return
                except ValueError:
                    continue

            logger.info("Setting static IP %s on '%s' for fallback detection", target_ip, adapter_name)
        except Exception:
            logger.warning("Could not check adapter IP, will attempt to set static IP")

        # Set static IP
        try:
            cmd = [
                "netsh", "interface", "ip", "set", "address",
                f"name={adapter_name}",
                "source=static",
                f"addr={target_ip}",
                f"mask={target_mask}",
                f"gateway={ethernet_cfg.gateway}",
                "gwmetric=1",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode == 0:
                logger.info("Static IP %s set on '%s'", target_ip, adapter_name)
                time.sleep(2)
            else:
                logger.error("Failed to set static IP: %s", result.stderr)
        except Exception:
            logger.exception("Exception setting static IP")

    def _find_mac_in_arp(self, prefix_dash: str, raw_prefix: str):
        """Search ARP/Neighbor table for a matching MAC prefix.

        Only searches entries on the configured ethernet adapter,
        ignoring WiFi, Bluetooth, and other interfaces.

        Returns DetectedDevice if found, None otherwise.
        """
        import subprocess

        ethernet_name = self._resolved_adapter_name or self._config.ethernet_adapter.name
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
