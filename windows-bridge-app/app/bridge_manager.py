import subprocess
import logging

logger = logging.getLogger(__name__)

# PowerShell script to create a network bridge between two adapters.
# Uses the INetCfg COM approach via the Network Connections shell folder.
# This works on Windows 10/11 consumer editions.
PS_CREATE_BRIDGE = r'''
param(
    [string]$Adapter1,
    [string]$Adapter2,
    [string]$BridgeName
)

$ErrorActionPreference = "Stop"

# Check if bridge already exists
$existingBridge = Get-NetAdapter | Where-Object { $_.Name -eq $BridgeName }
if ($existingBridge) {
    Write-Output "Bridge '$BridgeName' already exists."
    exit 0
}

# Get the adapter objects
$adapters = Get-NetAdapter | Where-Object {
    $_.Name -eq $Adapter1 -or $_.Name -eq $Adapter2
}

if ($adapters.Count -lt 2) {
    Write-Error "Could not find both adapters: '$Adapter1' and '$Adapter2'"
    exit 1
}

# Method: Use the legacy bridge via registry + netsh
# First, ensure both adapters are enabled
foreach ($adapter in $adapters) {
    if ($adapter.Status -ne "Up") {
        Enable-NetAdapter -Name $adapter.Name -Confirm:$false
        Start-Sleep -Seconds 2
    }
}

# Create bridge using the Network Bridge COM object
$networkConnections = (New-Object -ComObject Shell.Application).Namespace(0x31)
$items = $networkConnections.Items()

$selectedItems = @()
foreach ($item in $items) {
    if ($item.Name -eq $Adapter1 -or $item.Name -eq $Adapter2) {
        $selectedItems += $item
    }
}

if ($selectedItems.Count -lt 2) {
    Write-Error "Could not find both adapters in Network Connections folder."
    exit 1
}

# Select all target adapters and invoke "Bridge Connections"
$shell = New-Object -ComObject Shell.Application
$folder = $shell.Namespace(0x31)  # Network Connections

# Use verb "Bridge Connections" on the selected adapters
# This requires selecting both items and using the context menu verb
foreach ($item in $selectedItems) {
    $verbs = $item.Verbs()
    foreach ($verb in $verbs) {
        if ($verb.Name -like "*Bridge*" -or $verb.Name -like "*브릿지*") {
            Write-Output "Invoking bridge verb on $($item.Name)..."
            $verb.DoIt()
            Start-Sleep -Seconds 5
        }
    }
}

# Verify bridge was created
Start-Sleep -Seconds 3
$bridge = Get-NetAdapter | Where-Object { $_.InterfaceDescription -like "*Bridge*" }
if ($bridge) {
    # Rename to desired name
    if ($bridge.Name -ne $BridgeName) {
        Rename-NetAdapter -Name $bridge.Name -NewName $BridgeName
    }
    Write-Output "Bridge '$BridgeName' created successfully."
    exit 0
} else {
    Write-Error "Bridge creation verification failed."
    exit 1
}
'''

PS_REMOVE_BRIDGE = r'''
param(
    [string]$BridgeName
)

$ErrorActionPreference = "Stop"

$bridge = Get-NetAdapter | Where-Object {
    $_.Name -eq $BridgeName -or $_.InterfaceDescription -like "*Bridge*"
}

if (-not $bridge) {
    Write-Output "No bridge found to remove."
    exit 0
}

# Remove bridge via Network Connections shell
$networkConnections = (New-Object -ComObject Shell.Application).Namespace(0x31)
$items = $networkConnections.Items()

foreach ($item in $items) {
    if ($item.Name -eq $bridge.Name -or $item.Name -like "*Bridge*") {
        $verbs = $item.Verbs()
        foreach ($verb in $verbs) {
            if ($verb.Name -like "*Remove*" -or $verb.Name -like "*Delete*" -or $verb.Name -like "*삭제*") {
                Write-Output "Removing bridge $($item.Name)..."
                $verb.DoIt()
                Start-Sleep -Seconds 3
            }
        }
    }
}

# Fallback: disable and remove via netsh
try {
    Disable-NetAdapter -Name $bridge.Name -Confirm:$false 2>$null
} catch {}

Write-Output "Bridge removal complete."
'''

PS_CHECK_BRIDGE = r'''
param(
    [string]$BridgeName
)

$bridge = Get-NetAdapter | Where-Object {
    $_.Name -eq $BridgeName -or $_.InterfaceDescription -like "*Bridge*"
}

if ($bridge) {
    Write-Output "EXISTS"
    exit 0
} else {
    Write-Output "NOT_FOUND"
    exit 0
}
'''

# Alternative: Internet Connection Sharing (simpler, often sufficient)
PS_ENABLE_ICS = r'''
param(
    [string]$SharedAdapter,
    [string]$HomeAdapter
)

$ErrorActionPreference = "Stop"

# Register the HNetCfg library
regsvr32 /s hnetcfg.dll

$netShare = New-Object -ComObject HNetCfg.HNetShare

$connections = $netShare.EnumEveryConnection
foreach ($conn in $connections) {
    $props = $netShare.NetConnectionProps($conn)
    $config = $netShare.INetSharingConfigurationForINetConnection($conn)

    if ($props.Name -eq $SharedAdapter) {
        # This is the internet-facing adapter (WiFi) - enable sharing
        $config.EnableSharing(0)  # 0 = public (shared)
        Write-Output "Enabled sharing on $($props.Name)"
    }
    elseif ($props.Name -eq $HomeAdapter) {
        # This is the home/private adapter (Ethernet) - set as private
        $config.EnableSharing(1)  # 1 = private (home)
        Write-Output "Set $($props.Name) as home network"
    }
}

Write-Output "ICS enabled: $SharedAdapter -> $HomeAdapter"
'''

PS_DISABLE_ICS = r'''
$netShare = New-Object -ComObject HNetCfg.HNetShare
$connections = $netShare.EnumEveryConnection
foreach ($conn in $connections) {
    $config = $netShare.INetSharingConfigurationForINetConnection($conn)
    if ($config.SharingEnabled) {
        $config.DisableSharing()
    }
}
Write-Output "ICS disabled on all adapters."
'''


class BridgeManager:
    """Creates and removes a network bridge between two adapters."""

    def __init__(self, use_ics_fallback: bool = True):
        self._use_ics_fallback = use_ics_fallback

    def create_bridge(self, bridge_name: str, adapter1: str, adapter2: str) -> bool:
        logger.info("Creating bridge '%s' between '%s' and '%s'", bridge_name, adapter1, adapter2)

        ok = self._run_ps(
            PS_CREATE_BRIDGE,
            ["-Adapter1", adapter1, "-Adapter2", adapter2, "-BridgeName", bridge_name],
            "Create network bridge",
        )

        if not ok and self._use_ics_fallback:
            logger.warning("Bridge creation failed, falling back to ICS")
            ok = self.enable_ics(adapter2, adapter1)  # WiFi shares to Ethernet

        return ok

    def remove_bridge(self, bridge_name: str) -> bool:
        logger.info("Removing bridge '%s'", bridge_name)

        ok = self._run_ps(
            PS_REMOVE_BRIDGE,
            ["-BridgeName", bridge_name],
            "Remove network bridge",
        )

        # Also disable ICS in case it was used as fallback
        self.disable_ics()

        return ok

    def bridge_exists(self, bridge_name: str) -> bool:
        result = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-Command", PS_CHECK_BRIDGE, "-BridgeName", bridge_name],
            capture_output=True, text=True,
        )
        return "EXISTS" in result.stdout

    def enable_ics(self, shared_adapter: str, home_adapter: str) -> bool:
        logger.info("Enabling ICS: %s -> %s", shared_adapter, home_adapter)
        return self._run_ps(
            PS_ENABLE_ICS,
            ["-SharedAdapter", shared_adapter, "-HomeAdapter", home_adapter],
            "Enable Internet Connection Sharing",
        )

    def disable_ics(self) -> bool:
        return self._run_ps(PS_DISABLE_ICS, [], "Disable ICS")

    def _run_ps(self, script: str, args: list, description: str) -> bool:
        cmd = [
            "powershell",
            "-ExecutionPolicy", "Bypass",
            "-Command", script,
        ] + args

        logger.debug("PowerShell: %s", description)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.stdout.strip():
            logger.info("PS stdout: %s", result.stdout.strip())
        if result.stderr.strip():
            logger.error("PS stderr: %s", result.stderr.strip())

        if result.returncode != 0:
            logger.error("%s FAILED (rc=%d)", description, result.returncode)
            return False

        logger.info("%s OK", description)
        return True
