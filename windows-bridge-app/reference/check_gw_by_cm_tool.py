# Original gateway check script (reference)
# Source: check_gw_by_cm_tool.py from Infortab system
#
# This script discovers gateway devices on the network using
# ZMQ-based broadcast search. Our Windows bridge app replicates
# the device detection via ARP/MAC matching.

SETTING_MODE = False
SETTING_INFO = {
    'mac': '78:E9:80:FF:F0:27',
    'ip': '192.168.220.72',
    'defGw': '192.168.220.1',
    'netmask': '255.255.255.0',
    'storeCode': 'store-1',
    'svrIp': '192.168.240.101',
    'svrPort': '80',
    'dnsIp': '8.8.8.8'
}

import sys
sys.path.append("/ramdisk/infortab/infortab_server")
from service.manager.evt_mgr_client import get_event_mgr_client
from service_launcher.cm_tool_server import _GatewaySearchResultCollector
from threading import Thread
from zmq import ZMQError


def cm_tool_server():
    try:
        _GatewaySearchResultCollector().run()
    except ZMQError as e:
        pass  # not gw only mode


Thread(target=cm_tool_server, daemon=True).start()

if SETTING_MODE:
    get_event_mgr_client().send_gw_config(SETTING_INFO)
else:
    get_event_mgr_client().send_broadcast_gw_search()
    searched_gw_list = get_event_mgr_client().get_gw_search_result()
    for gw in searched_gw_list:
        print(gw)
