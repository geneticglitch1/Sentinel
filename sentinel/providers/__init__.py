"""Infrastructure providers: Proxmox, OPNsense, Docker host.

Each provider is a thin, testable wrapper around an external system. They do *not*
enforce safety or write audit rows — that is the job of ``sentinel.tools``. Keeping
providers side-effect-honest (a method that mutates, mutates) lets the tool layer
own the dry-run / confirm / audit policy in one place.
"""
