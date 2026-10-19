"""Native network configuration regression; DDS is restricted to loopback.

Each case runs in a fresh process because the SDK owns a global singleton.
No robot discovery request, RPC, or motion command is issued.
"""
import subprocess
import sys
import unittest

PROBE = r"""
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
import robot_motion_sdk as sdk

case = sys.argv[1]
service = sdk.service
assert service.set_network_config({"iface": "lo", "dont_route": False, "peers": []})
if case == "peers":
    assert service.set_network_config({"peers": ["127.0.0.1:17910"]})
    assert service.set_network_config({})
elif case == "clear":
    assert service.set_network_config({"peers": ["127.0.0.1:17910"], "dont_route": True})
    assert service.set_network_config({"peers": [], "dont_route": False})
elif case == "invalid_atomic":
    assert service.set_network_config({"peers": ["127.0.0.1:17910"]})
    for bad in ({"iface": "missing_iface", "peers": [""]},
                {"dont_route": True, "peers": [42]},
                {"peers": "127.0.0.1"}, {"dont_route": "false"},
                {"iface": 42}):
        assert not service.set_network_config(bad), bad
elif case == "json":
    assert service.set_network_config('{"peers":["127.0.0.1:17910"]}')

assert service.initial(None, "networkConfigRegression", 1000)
try:
    profile = Path(f"/tmp/motion_sdk_host_{os.getpid()}.xml")
    root = ET.parse(profile).getroot()
    ns = {"d": "https://cdds.io/config"}
    assert root.findtext(".//d:AllowMulticast", namespaces=ns) == "true"
    assert root.findtext(".//d:DontRoute", default="false", namespaces=ns) == "false"
    assert root.find(".//d:NetworkInterface", ns).attrib["name"] == "lo"
    peers = [node.attrib["Address"] for node in root.findall(".//d:Peer", ns)]
    expected = [] if case in ("default", "clear") else ["127.0.0.1:17910"]
    assert peers == expected, (peers, expected)
    if peers:
        assert root.findtext(".//d:ParticipantIndex", namespaces=ns) == "auto"
    assert not service.set_network_config({"peers": []})
finally:
    service.shutdown()
assert not profile.exists()
"""


class NetworkConfigTest(unittest.TestCase):
    def test_native_configuration_and_generated_xml(self):
        for case in ("default", "peers", "clear", "invalid_atomic", "json"):
            with self.subTest(case=case):
                result = subprocess.run([sys.executable, "-c", PROBE, case],
                                        capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
