import os
import sys
from helpers import runtime
from helpers.print_style import PrintStyle

_server = None

def set_server(server):
    global _server
    _server = server

def get_server(server):
    global _server
    return _server

def stop_server():
    global _server
    if _server:
        _server.shutdown()
        _server = None

def reload():
    stop_server()
    if runtime.is_dockerized():
        exit_process()
    else:
        _hand_over_tunnel()
        restart_process()


def _hand_over_tunnel():
    # The tunnel is a child of this process and outlives it; record it so the
    # restarted server adopts it and the remote address keeps working.
    try:
        from helpers.tunnel_manager import TunnelManager

        if TunnelManager.get_instance().write_handover(runtime.get_web_ui_port()):
            PrintStyle.standard("Handing the Remote Control tunnel over to the restarted server...")
    except Exception as e:
        PrintStyle.warning(f"Could not hand over the tunnel: {e}")

def restart_process():
    PrintStyle.standard("Restarting process...")
    python = sys.executable
    os.execv(python, [python] + sys.argv)

def exit_process():
    PrintStyle.standard("Exiting process...")
    sys.exit(0)