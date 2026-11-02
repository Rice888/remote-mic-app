#!/usr/bin/env python3
"""SayAll UB500 transport. Private stdio IPC; stdout is never a diagnostic log."""
import argparse
import asyncio
import base64
import json
import logging
import os
from pathlib import Path
import re
import signal
import sys

PROTOCOL_VERSION = 1
USB_TRANSPORT = 'usb:2357:0604'
ATVV = {name: f'AB5E000{index}-5A21-4F05-BC7D-AF01F617B664'
        for name, index in [('service', 1), ('tx', 2), ('audio', 3), ('control', 4)]}


class BridgeError(Exception):
    def __init__(self, code):
        self.code = code


def validate_arguments(args):
    if not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', args.address):
        raise BridgeError('invalid_address')
    for name in ('rtl8761bu_fw.bin', 'rtl8761bu_config.bin'):
        path = Path(args.firmware) / name
        if not path.is_file() or path.stat().st_size == 0:
            raise BridgeError('firmware_missing')
    os.environ['BUMBLE_RTK_FIRMWARE_DIR'] = str(Path(args.firmware).resolve())
    Path(args.keys).parent.mkdir(parents=True, exist_ok=True, mode=0o700)


class Protocol:
    def __init__(self):
        self.sequence = 0
        self.queue = asyncio.Queue(maxsize=512)
        self.stopped = asyncio.Event()
        self.ready = asyncio.Event()
        self.failed = False

    def emit(self, kind, data=None, **fields):
        if self.failed:
            return
        if kind == 'ready':
            self.ready.set()
        self.sequence += 1
        packet = dict(v=PROTOCOL_VERSION, seq=self.sequence, type=kind, **fields)
        if data is not None:
            packet['data'] = base64.b64encode(data).decode('ascii')
        try:
            self.queue.put_nowait(json.dumps(packet, separators=(',', ':')) + '\n')
        except asyncio.QueueFull:
            # Never silently discard audio or key-up. Close the connection instead.
            self.failed = True
            self.stopped.set()

    async def output(self):
        def write(line):
            sys.stdout.write(line)
            sys.stdout.flush()
        while True:
            line = await self.queue.get()
            try:
                await asyncio.to_thread(write, line)
            finally:
                self.queue.task_done()


async def discover(peer, protocol):
    from bumble.core import UUID
    from bumble.gatt import Characteristic
    await peer.discover_services()
    for service in peer.services:
        await peer.discover_characteristics(service=service)

    def characteristic(uuid, service_uuid):
        services = peer.get_services_by_uuid(UUID(service_uuid))
        matches = [c for s in services for c in s.characteristics if c.uuid == UUID(uuid)]
        if len(matches) != 1:
            raise BridgeError('required_characteristic_missing')
        return matches[0]

    tx = characteristic(ATVV['tx'], ATVV['service'])
    audio = characteristic(ATVV['audio'], ATVV['service'])
    control = characteristic(ATVV['control'], ATVV['service'])
    if not tx.properties & (Characteristic.Properties.WRITE | Characteristic.Properties.WRITE_WITHOUT_RESPONSE):
        raise BridgeError('tx_not_writable')
    for name, channel in [('control', control), ('audio', audio)]:
        await channel.subscribe(lambda value, kind=name: protocol.emit(kind, bytes(value)))

    reports = 0
    for service in peer.get_services_by_uuid(UUID(0x1812)):
        for channel in service.characteristics:
            if channel.uuid != UUID(0x2A4D):
                continue
            await channel.discover_descriptors()
            reference = channel.get_descriptor(UUID(0x2908))
            if reference is None:
                continue
            value = await reference.read_value()
            if len(value) != 2 or value[1] != 1:
                continue
            report_id = value[0]
            # The host parser knows Xiaomi report 1 layouts only.
            if report_id != 1:
                continue
            await channel.subscribe(
                lambda value, rid=report_id: protocol.emit('hid', bytes(value), report_id=rid))
            reports += 1
    if not reports:
        raise BridgeError('hid_input_missing')

    # Identity is obtained from DIS, never guessed from the selected transport.
    model = characteristic(0x2A24, 0x180A)
    value = await model.read_value()
    protocol.emit('model', bytes(value))
    try:
        battery = characteristic(0x2A19, 0x180F)
        value = await battery.read_value()
        if len(value) == 1 and value[0] <= 100:
            protocol.emit('battery', bytes(value))
        if battery.properties & (Characteristic.Properties.NOTIFY | Characteristic.Properties.INDICATE):
            await battery.subscribe(lambda value: protocol.emit('battery', bytes(value)))
    except Exception:
        pass  # Optional telemetry cannot invalidate verified voice + HID channels.
    return tx


async def commands(peer, tx, protocol):
    from bumble.gatt import Characteristic
    reader = asyncio.StreamReader(limit=4096)
    await asyncio.get_running_loop().connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer)
    while not protocol.stopped.is_set():
        line = await reader.readline()
        if not line:
            protocol.stopped.set()
            return
        try:
            packet = json.loads(line)
            if packet.get('v') != PROTOCOL_VERSION:
                raise ValueError()
            if packet.get('type') == 'stop':
                protocol.stopped.set()
                return
            if packet.get('type') != 'tx':
                raise ValueError()
            value = base64.b64decode(packet['data'], validate=True)
            if not 1 <= len(value) <= 256:
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise BridgeError('invalid_command') from None
        await peer.write_value(tx, value, with_response=not bool(
            tx.properties & Characteristic.Properties.WRITE_WITHOUT_RESPONSE))


async def connect(args, protocol):
    from bumble.device import Device, DeviceConfiguration, Peer
    from bumble.hci import Address, OwnAddressType
    from bumble.keys import JsonKeyStore
    from bumble.pairing import PairingConfig, PairingDelegate
    from bumble.transport import open_transport
    async with await open_transport(USB_TRANSPORT) as transport:
        device = Device.from_config_with_hci(DeviceConfiguration.from_dict({
            'name': 'SayAll UB500', 'classic_enabled': False, 'le_enabled': True,
        }), transport.source, transport.sink)
        device.keystore = JsonKeyStore(namespace='sayall-ub500', filename=args.keys)
        device.pairing_config_factory = lambda _: PairingConfig(
            sc=True, mitm=False, bonding=True,
            delegate=PairingDelegate(io_capability=PairingDelegate.NO_OUTPUT_NO_INPUT))
        # Driver selection and firmware upload are handled by pinned Bumble RTK driver.
        await device.power_on()
        connection = await device.connect(
            Address(args.address, Address.PUBLIC_DEVICE_ADDRESS), own_address_type=OwnAddressType.PUBLIC)
        connection.on('disconnection', lambda *_: protocol.stopped.set())
        try:
            keys = await device.keystore.get(str(connection.peer_address))
            if keys:
                await connection.encrypt()
            else:
                await connection.pair()
            peer = Peer(connection)
            await peer.request_mtu(185)
            tx = await discover(peer, protocol)
            protocol.emit('ready')
            command_task = asyncio.create_task(commands(peer, tx, protocol))
            stop_task = asyncio.create_task(protocol.stopped.wait())
            try:
                done, _ = await asyncio.wait([command_task, stop_task], return_when=asyncio.FIRST_COMPLETED)
                if command_task in done:
                    await command_task
            finally:
                command_task.cancel()
                stop_task.cancel()
                await asyncio.gather(command_task, stop_task, return_exceptions=True)
        finally:
            try:
                await asyncio.wait_for(connection.disconnect(), timeout=2)
            except Exception:
                pass


async def main(args):
    protocol = Protocol()
    output = asyncio.create_task(protocol.output())
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, protocol.stopped.set)
    task = None
    try:
        validate_arguments(args)
        # Bounds firmware, pairing, discovery and IPC initialization as one attempt.
        task = asyncio.create_task(connect(args, protocol))
        ready_task = asyncio.create_task(protocol.ready.wait())
        stop_task = asyncio.create_task(protocol.stopped.wait())
        try:
            done, _ = await asyncio.wait(
                [task, ready_task, stop_task], timeout=60,
                return_when=asyncio.FIRST_COMPLETED)
            if not done:
                raise BridgeError('initialization_timeout')
            if task in done:
                await task
            elif stop_task in done:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            else:
                await task
        finally:
            ready_task.cancel()
            stop_task.cancel()
            await asyncio.gather(ready_task, stop_task, return_exceptions=True)
        if protocol.failed:
            raise BridgeError('transport_overflow')
        protocol.emit('disconnected')
    except Exception as error:
        protocol.emit('error', code=error.code if isinstance(error, BridgeError) else 'transport_failed')
    finally:
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        try:
            await asyncio.wait_for(protocol.queue.join(), timeout=2)
        except asyncio.TimeoutError:
            pass
        output.cancel()
        await asyncio.gather(output, return_exceptions=True)


if __name__ == '__main__':
    os.umask(0o077)
    logging.disable(logging.CRITICAL)  # Third-party diagnostics must not leak into IPC/logs.
    parser = argparse.ArgumentParser()
    parser.add_argument('--address', required=True)
    parser.add_argument('--firmware', required=True)
    parser.add_argument('--keys', required=True)
    args = parser.parse_args()
    asyncio.run(main(args))
