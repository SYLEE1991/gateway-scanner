import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).parent.parent / "assets"


def _create_icon_image(color):
    """Create a simple colored circle icon using Pillow."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, 60, 60], fill=color, outline=(50, 50, 50))
    return img


STATE_COLORS = {
    "idle": (100, 100, 100),      # gray
    "monitoring": (30, 144, 255),  # blue
    "active": (0, 200, 0),        # green
    "error": (220, 50, 50),       # red
}

STATE_LABELS = {
    "idle": "Idle",
    "monitoring": "Monitoring",
    "active": "Bridge Active",
    "error": "Error",
}


class TrayApp:
    """System tray application that ties all components together."""

    def __init__(self, config_manager, device_monitor, network_config, bridge_manager):
        self._config_mgr = config_manager
        self._monitor = device_monitor
        self._net_config = network_config
        self._bridge_mgr = bridge_manager
        self._state = "monitoring"
        self._device_info = None  # DetectedDevice when active
        self._icon = None

    def run(self):
        import pystray

        menu = pystray.Menu(
            pystray.MenuItem(lambda _: f"Status: {STATE_LABELS.get(self._state, self._state)}", None, enabled=False),
            pystray.MenuItem(lambda _: f"Device IP: {self._device_info.ip}" if self._device_info and self._device_info.ip else "Device IP: -", None, enabled=False),
            pystray.MenuItem(lambda _: f"Device MAC: {self._device_info.mac}" if self._device_info and self._device_info.mac else "Device MAC: -", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Device Manager", self._open_device_popup),
            pystray.MenuItem("Open Settings", self._open_settings),
            pystray.MenuItem("Force Bridge Now", self._force_bridge),
            pystray.MenuItem("Remove Bridge", self._remove_bridge),
            pystray.MenuItem("Revert to DHCP", self._revert_dhcp),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self._exit),
        )

        self._icon = pystray.Icon(
            "NetworkBridge",
            icon=_create_icon_image(STATE_COLORS["monitoring"]),
            title="Network Bridge - Monitoring",
            menu=menu,
        )

        self._monitor.start()
        logger.info("Tray application started")
        self._icon.run()  # Blocks

    def update_state(self, new_state: str, device_info=None):
        self._state = new_state
        self._device_info = device_info
        if self._icon:
            self._icon.icon = _create_icon_image(STATE_COLORS.get(new_state, (100, 100, 100)))
            title = f"Network Bridge - {STATE_LABELS.get(new_state, new_state)}"
            if device_info and device_info.ip:
                title += f" ({device_info.ip})"
            self._icon.title = title

    def _open_device_popup(self, icon, item):
        threading.Thread(target=self._show_device_popup, daemon=True).start()

    def _show_device_popup(self):
        from app.device_popup import DevicePopup
        DevicePopup(self._monitor, self._config_mgr).run()

    def _open_settings(self, icon, item):
        threading.Thread(target=self._show_gui, daemon=True).start()

    def _show_gui(self):
        from app.gui import SettingsWindow
        SettingsWindow(self._config_mgr).run()

    def _force_bridge(self, icon, item):
        def do_bridge():
            config = self._config_mgr.load()
            logger.info("Forcing bridge creation...")

            self._net_config.set_static_ip(
                config.ethernet_adapter.name,
                config.ethernet_adapter.static_ip,
                config.ethernet_adapter.subnet_mask,
                config.ethernet_adapter.gateway,
            )
            self._net_config.set_dns(
                config.ethernet_adapter.name,
                config.ethernet_adapter.dns_primary,
                config.ethernet_adapter.dns_secondary,
            )

            ok = self._bridge_mgr.create_bridge(
                config.bridge.name,
                config.ethernet_adapter.name,
                config.wifi_adapter.name,
            )
            self.update_state("active" if ok else "error")

        threading.Thread(target=do_bridge, daemon=True).start()

    def _remove_bridge(self, icon, item):
        def do_remove():
            config = self._config_mgr.load()
            self._bridge_mgr.remove_bridge(config.bridge.name)
            self.update_state("monitoring")

        threading.Thread(target=do_remove, daemon=True).start()

    def _revert_dhcp(self, icon, item):
        def do_revert():
            config = self._config_mgr.load()
            self._net_config.set_dhcp(config.ethernet_adapter.name)
            logger.info("Reverted to DHCP")

        threading.Thread(target=do_revert, daemon=True).start()

    def _exit(self, icon, item):
        logger.info("Exiting application...")
        self._monitor.stop()

        config = self._config_mgr.load()
        self._bridge_mgr.remove_bridge(config.bridge.name)
        self._net_config.set_dhcp(config.ethernet_adapter.name)

        icon.stop()
