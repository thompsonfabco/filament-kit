import os
import platform
import socket

from filament_kit import config, pairing, setup_page


def test_every_host_name_lookup_answers_the_made_up_name():
    assert socket.gethostname() == "workshop-hub"
    assert socket.getfqdn() == "workshop-hub"
    assert platform.node() == "workshop-hub"
    if hasattr(os, "uname"):
        assert os.uname().nodename == "workshop-hub"


def test_server_code_sees_the_made_up_name():
    assert config.load()["server_name"] == "workshop-hub"
    assert config.DEFAULTS["server_name"] == "workshop-hub"
    assert pairing.short_hostname() == "workshop-hub"
    assert "workshop-hub" in setup_page.allowed_hosts()
