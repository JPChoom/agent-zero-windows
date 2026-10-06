# Start at logon

Starts Agent Zero in the background when you sign in to Windows - useful on the dedicated PC Agent Zero is meant to run on.

- **Turn it on or off:** Settings > Developer > Start at logon. It is off by default.
- **What it adds:** one entry in *your* Startup list (`HKCU\...\CurrentVersion\Run`, named `AgentZeroForWindows`). No admin rights, no Scheduled Task, no service. You can also see it, and switch it off, in Task Manager > Startup apps.
- **No window:** Agent Zero runs hidden; its output goes to `logs/autostart.log`. Open the WebUI in your browser as usual.
- **Already running?** If Agent Zero already answers on its port at logon, nothing else is started.
- **Remote access** starts only if you have configured it to start with Agent Zero.
- **Stopping it:** use the WebUI's shutdown, or end the `python.exe` running `run_ui.py` in Task Manager.
- **Before moving or deleting the install,** turn it off here, so the Startup entry does not point at a missing launcher.

The agent cannot turn this on itself: the safety policy refuses any command that writes a Run key or the Startup folder.
