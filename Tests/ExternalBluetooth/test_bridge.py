"""Regression coverage for the real backend's GATT subscription and IPC contract."""
import asyncio
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from bumble.core import UUID
from bumble.gatt import Characteristic

spec = importlib.util.spec_from_file_location('external_bridge',
    Path(__file__).resolve().parents[2] / 'Resources/ExternalBluetooth/bridge.py')
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class Channel:
    def __init__(self, uuid, value=b'', report=None):
        self.uuid = UUID(uuid)
        self.value = value
        self.report = report
        self.subscriber = None
        self.properties = (Characteristic.Properties.WRITE_WITHOUT_RESPONSE |
                           Characteristic.Properties.NOTIFY)
    async def read_value(self):
        return self.value
    async def discover_descriptors(self):
        pass
    def get_descriptor(self, uuid):
        return Channel(0x2908, self.report) if self.report is not None else None
    async def subscribe(self, subscriber):
        self.subscriber = subscriber


class Peer:
    def __init__(self):
        self.tx = Channel(bridge.ATVV['tx'])
        self.audio = Channel(bridge.ATVV['audio'])
        self.control = Channel(bridge.ATVV['control'])
        self.hid = Channel(0x2A4D, report=b'\x01\x01')
        self.model = Channel(0x2A24, value=b'RC003')
        self.battery = Channel(0x2A19, value=b'\x64')
        self.services = [
            SimpleNamespace(uuid=UUID(bridge.ATVV['service']), characteristics=[self.tx, self.audio, self.control]),
            SimpleNamespace(uuid=UUID(0x1812), characteristics=[self.hid]),
            SimpleNamespace(uuid=UUID(0x180A), characteristics=[self.model]),
            SimpleNamespace(uuid=UUID(0x180F), characteristics=[self.battery])]
    async def discover_services(self):
        pass
    async def discover_characteristics(self, service):
        pass
    def get_services_by_uuid(self, uuid):
        return [s for s in self.services if s.uuid == uuid]


class BackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_required_channels_subscribe_before_ready_and_preserve_edges(self):
        protocol = bridge.Protocol()
        peer = Peer()
        tx = await bridge.discover(peer, protocol)
        self.assertIs(tx, peer.tx)
        self.assertTrue(all(c.subscriber for c in [peer.audio, peer.control, peer.hid]))
        self.assertFalse(protocol.ready.is_set())
        protocol.emit('ready')
        peer.hid.subscriber(bytes.fromhex('0000510000000000'))
        peer.hid.subscriber(bytes(8))
        peer.audio.subscriber(bytes(range(120)))
        packets = [json.loads(protocol.queue.get_nowait()) for _ in range(protocol.queue.qsize())]
        self.assertEqual([p['seq'] for p in packets], list(range(1, len(packets) + 1)))
        self.assertEqual([p['type'] for p in packets], ['model', 'battery', 'ready', 'hid', 'hid', 'audio'])
        self.assertEqual(packets[3]['report_id'], 1)
        import base64
        self.assertEqual(base64.b64decode(packets[4]['data']), bytes(8))
        self.assertEqual(base64.b64decode(packets[5]['data']), bytes(range(120)))

    async def test_missing_voice_or_hid_cannot_advertise_ready(self):
        for missing in ['audio', 'hid']:
            protocol = bridge.Protocol()
            peer = Peer()
            channel = getattr(peer, missing)
            for service in peer.services:
                service.characteristics[:] = [c for c in service.characteristics if c is not channel]
            with self.assertRaises(bridge.BridgeError):
                await bridge.discover(peer, protocol)
            self.assertFalse(protocol.ready.is_set())

    async def test_overflow_closes_session_instead_of_losing_silent_audio(self):
        protocol = bridge.Protocol()
        for _ in range(513):
            protocol.emit('audio', b'\x00')
        self.assertTrue(protocol.failed)
        self.assertTrue(protocol.stopped.is_set())

    async def test_report_reference_excludes_output_and_unknown_layouts(self):
        for reference in [b'\x01\x02', b'\x02\x01', b'\x01', None]:
            peer = Peer()
            peer.hid.report = reference
            with self.assertRaises(bridge.BridgeError):
                await bridge.discover(peer, bridge.Protocol())

    async def test_connection_uses_only_ub500_and_bonds_without_silent_repair(self):
        from bumble.hci import OwnAddressType
        for bonded, encryption_fails in [(False, False), (True, False), (True, True)]:
            protocol = bridge.Protocol()
            peer = Peer()
            peer.request_mtu = AsyncMock()
            connection = SimpleNamespace(peer_address='00:11:22:33:44:55/P',
                on=lambda *_: None, pair=AsyncMock(), encrypt=AsyncMock(), disconnect=AsyncMock())
            if encryption_fails:
                connection.encrypt.side_effect = RuntimeError('stale keys')
            device = SimpleNamespace(power_on=AsyncMock(), connect=AsyncMock(return_value=connection))
            keys = SimpleNamespace(get=AsyncMock(return_value=object() if bonded else None))
            class Transport:
                source = object()
                sink = object()
                async def __aenter__(self): return self
                async def __aexit__(self, *_): return False
            async def stop_commands(*_):
                protocol.stopped.set()
            args = SimpleNamespace(address='00:11:22:33:44:55', keys='private-bonds.json')
            with patch('bumble.transport.open_transport', AsyncMock(return_value=Transport())) as opened, \
                 patch('bumble.device.Device.from_config_with_hci', return_value=device), \
                 patch('bumble.device.Peer', return_value=peer), \
                 patch('bumble.keys.JsonKeyStore', return_value=keys) as store, \
                 patch.object(bridge, 'commands', stop_commands):
                if encryption_fails:
                    with self.assertRaises(RuntimeError):
                        await bridge.connect(args, protocol)
                    self.assertFalse(protocol.ready.is_set())
                else:
                    await bridge.connect(args, protocol)
                    self.assertTrue(protocol.ready.is_set())
                opened.assert_awaited_once_with('usb:2357:0604')
                store.assert_called_once_with(namespace='sayall-ub500', filename='private-bonds.json')
                self.assertEqual(device.connect.await_args.kwargs['own_address_type'], OwnAddressType.PUBLIC)
                self.assertEqual(connection.pair.await_count, 0 if bonded else 1)
                self.assertEqual(connection.encrypt.await_count, 1 if bonded else 0)
                connection.disconnect.assert_awaited_once()

    async def test_fixed_usb_and_private_firmware_directory(self):
        self.assertEqual(bridge.USB_TRANSPORT, 'usb:2357:0604')
        with tempfile.TemporaryDirectory() as folder:
            args = SimpleNamespace(address='00:11:22:33:44:55', firmware=folder,
                                   keys=str(Path(folder) / 'private/bonds.json'))
            with self.assertRaisesRegex(bridge.BridgeError, 'firmware_missing'):
                bridge.validate_arguments(args)
            for name in ['rtl8761bu_fw.bin', 'rtl8761bu_config.bin']:
                (Path(folder) / name).write_bytes(b'test')
            bridge.validate_arguments(args)
            args.address = 'invalid'
            with self.assertRaisesRegex(bridge.BridgeError, 'invalid_address'):
                bridge.validate_arguments(args)


if __name__ == '__main__':
    unittest.main()
