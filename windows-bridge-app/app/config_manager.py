import json
import dataclasses
from pathlib import Path


@dataclasses.dataclass
class TargetDevice:
    hardware_id: str
    friendly_name: str
    mac_prefix: str  # OUI prefix, e.g. "78:E9:80" (first 3 bytes of MAC)
    priority_ip: str  # Most common device IP, checked first for fast detection
    detection_method: str  # "hardware_id", "friendly_name", "mac_address", or "ethernet_link"


@dataclasses.dataclass
class EthernetConfig:
    name: str
    static_ip: str
    subnet_mask: str
    gateway: str
    dns_primary: str
    dns_secondary: str


@dataclasses.dataclass
class WifiConfig:
    name: str


@dataclasses.dataclass
class BridgeConfig:
    name: str
    auto_create: bool


@dataclasses.dataclass
class AppSettings:
    poll_interval_seconds: int
    start_minimized: bool
    auto_start_with_windows: bool
    log_file: str
    log_level: str


@dataclasses.dataclass
class AppConfig:
    target_device: TargetDevice
    ethernet_adapter: EthernetConfig
    wifi_adapter: WifiConfig
    bridge: BridgeConfig
    app: AppSettings


DEFAULT_CONFIG = {
    "target_device": {
        "hardware_id": "USB\\VID_XXXX&PID_XXXX",
        "friendly_name": "Infortab Gateway",
        "mac_prefix": "78:E9:80",
        "priority_ip": "192.168.220.206",
        "detection_method": "mac_address",
    },
    "ethernet_adapter": {
        "name": "Ethernet",
        "static_ip": "192.168.220.100",
        "subnet_mask": "255.255.255.0",
        "gateway": "192.168.220.1",
        "dns_primary": "8.8.8.8",
        "dns_secondary": "8.8.4.4",
    },
    "wifi_adapter": {"name": "Wi-Fi"},
    "bridge": {"name": "NetworkBridge", "auto_create": True},
    "app": {
        "poll_interval_seconds": 3,
        "start_minimized": True,
        "auto_start_with_windows": False,
        "log_file": "bridge_app.log",
        "log_level": "INFO",
    },
}


class ConfigManager:
    def __init__(self, config_path: Path):
        self._path = config_path

    def load(self) -> AppConfig:
        if not self._path.exists():
            self._path.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")

        data = json.loads(self._path.read_text(encoding="utf-8"))

        return AppConfig(
            target_device=TargetDevice(**data["target_device"]),
            ethernet_adapter=EthernetConfig(**data["ethernet_adapter"]),
            wifi_adapter=WifiConfig(**data["wifi_adapter"]),
            bridge=BridgeConfig(**data["bridge"]),
            app=AppSettings(**data["app"]),
        )

    def save(self, config: AppConfig) -> None:
        data = {
            "target_device": dataclasses.asdict(config.target_device),
            "ethernet_adapter": dataclasses.asdict(config.ethernet_adapter),
            "wifi_adapter": dataclasses.asdict(config.wifi_adapter),
            "bridge": dataclasses.asdict(config.bridge),
            "app": dataclasses.asdict(config.app),
        }
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
