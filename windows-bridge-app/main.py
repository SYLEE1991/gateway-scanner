"""
Windows Network Bridge Application

Monitors for a specific device connection, automatically configures
ethernet IP settings, and creates a network bridge with WiFi.

Requires: Windows 10/11, Python 3.10+, Administrator privileges.
"""

import sys
import logging
from pathlib import Path


def is_admin() -> bool:
    """Check if running with administrator privileges."""
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def request_elevation():
    """Re-launch as administrator via UAC prompt."""
    import ctypes
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, " ".join(sys.argv), None, 1
    )
    sys.exit(0)


def setup_logging(log_file: str, log_level: str):
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def main():
    # Require admin on Windows
    if sys.platform == "win32" and not is_admin():
        request_elevation()
        return

    config_path = Path(__file__).parent / "config.json"

    from app.config_manager import ConfigManager
    from app.device_monitor import DeviceMonitor
    from app.network_config import NetworkConfigurator
    from app.bridge_manager import BridgeManager
    from app.tray import TrayApp
    from app.scan_window import ScanWindow

    config_mgr = ConfigManager(config_path)
    config = config_mgr.load()

    setup_logging(config.app.log_file, config.app.log_level)
    logger = logging.getLogger("main")
    logger.info("Network Bridge App starting...")

    # --- Show scan window on startup ---
    logger.info("Opening startup scan window...")
    scan = ScanWindow(config)
    found_devices = scan.run()
    logger.info("Scan complete. Found %d device(s)", len(found_devices))
    for d in found_devices:
        logger.info("  -> IP=%s  MAC=%s", d["ip"], d["mac"])

    # --- Continue to tray app for background monitoring ---
    net_config = NetworkConfigurator()
    bridge_mgr = BridgeManager()

    # Will be set after tray is created
    tray = None

    def on_device_connected(device_info):
        logger.info("=== Device Connected - Configuring Network ===")
        logger.info("Detected device IP: %s, MAC: %s", device_info.ip, device_info.mac)

        ok = net_config.set_static_ip(
            config.ethernet_adapter.name,
            config.ethernet_adapter.static_ip,
            config.ethernet_adapter.subnet_mask,
            config.ethernet_adapter.gateway,
        )
        if not ok:
            logger.error("Failed to set static IP")
            if tray:
                tray.update_state("error")
            return

        net_config.set_dns(
            config.ethernet_adapter.name,
            config.ethernet_adapter.dns_primary,
            config.ethernet_adapter.dns_secondary,
        )

        if config.bridge.auto_create:
            bridge_ok = bridge_mgr.create_bridge(
                config.bridge.name,
                config.ethernet_adapter.name,
                config.wifi_adapter.name,
            )
            if tray:
                tray.update_state("active", device_info)
        else:
            if tray:
                tray.update_state("active", device_info)

        logger.info("=== Network configuration complete ===")

    def on_device_disconnected():
        logger.info("=== Device Disconnected - Reverting Network ===")

        bridge_mgr.remove_bridge(config.bridge.name)
        net_config.set_dhcp(config.ethernet_adapter.name)

        if tray:
            tray.update_state("monitoring")

        logger.info("=== Network reverted to DHCP ===")

    monitor = DeviceMonitor(config, on_device_connected, on_device_disconnected)
    tray = TrayApp(config_mgr, monitor, net_config, bridge_mgr)

    logger.info("Monitoring for device: %s (%s)",
                config.target_device.friendly_name,
                config.target_device.hardware_id)

    tray.run()  # Blocks until exit


if __name__ == "__main__":
    main()
