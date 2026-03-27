import subprocess
import logging

logger = logging.getLogger(__name__)


class NetworkConfigurator:
    """Manages ethernet adapter IP configuration via netsh."""

    def set_static_ip(self, adapter_name: str, ip: str, mask: str, gateway: str) -> bool:
        cmd = [
            "netsh", "interface", "ip", "set", "address",
            f"name={adapter_name}",
            "source=static",
            f"addr={ip}",
            f"mask={mask}",
            f"gateway={gateway}",
            "gwmetric=1",
        ]
        return self._run(cmd, f"Set static IP {ip} on {adapter_name}")

    def set_dns(self, adapter_name: str, primary: str, secondary: str) -> bool:
        cmd1 = [
            "netsh", "interface", "ip", "set", "dns",
            f"name={adapter_name}",
            "source=static",
            f"addr={primary}",
            "register=primary",
        ]
        ok1 = self._run(cmd1, f"Set primary DNS {primary}")

        cmd2 = [
            "netsh", "interface", "ip", "add", "dns",
            f"name={adapter_name}",
            f"addr={secondary}",
            "index=2",
        ]
        ok2 = self._run(cmd2, f"Set secondary DNS {secondary}")

        return ok1 and ok2

    def set_dhcp(self, adapter_name: str) -> bool:
        cmd_ip = [
            "netsh", "interface", "ip", "set", "address",
            f"name={adapter_name}",
            "source=dhcp",
        ]
        cmd_dns = [
            "netsh", "interface", "ip", "set", "dns",
            f"name={adapter_name}",
            "source=dhcp",
        ]
        ok1 = self._run(cmd_ip, f"Revert {adapter_name} to DHCP (IP)")
        ok2 = self._run(cmd_dns, f"Revert {adapter_name} to DHCP (DNS)")
        return ok1 and ok2

    def get_adapter_names(self) -> list:
        cmd = ["netsh", "interface", "show", "interface"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error("Failed to list adapters: %s", result.stderr)
            return []

        adapters = []
        for line in result.stdout.strip().split("\n")[3:]:  # skip header lines
            parts = line.split()
            if len(parts) >= 4:
                # Format: Admin State  State  Type  Interface Name
                name = " ".join(parts[3:])
                adapters.append(name)
        return adapters

    def _run(self, cmd: list, description: str) -> bool:
        logger.info("Running: %s", description)
        logger.debug("Command: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error("%s FAILED (rc=%d): %s", description, result.returncode, result.stderr)
            return False
        logger.info("%s OK", description)
        return True
