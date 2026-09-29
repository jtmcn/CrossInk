import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from personal import device
from personal.proc import PersonalError, Result
from personal.project import Project
from personal.tests.fakes import FakeRunner


class SelectPortTest(unittest.TestCase):
    def test_ignores_bluetooth_and_uses_single_match(self):
        ports = ['/dev/cu.Bluetooth-Incoming-Port', '/dev/cu.usbmodem1101']
        self.assertEqual(device.select_port(ports), '/dev/cu.usbmodem1101')

    def test_no_port_tells_user_to_wake_reader(self):
        with self.assertRaises(PersonalError) as ctx:
            device.select_port(['/dev/cu.Bluetooth-Incoming-Port'])
        self.assertIn('wake the reader', str(ctx.exception))

    def test_several_ports_prompt(self):
        ports = ['/dev/cu.usbmodem2', '/dev/cu.usbmodem1']
        self.assertEqual(device.select_port(ports, choose=lambda _: '2'), '/dev/cu.usbmodem2')

    def test_invalid_choice_refuses(self):
        with self.assertRaises(PersonalError):
            device.select_port(['/dev/cu.usbmodem2', '/dev/cu.usbmodem1'], choose=lambda _: '9')


class FlashTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / 'platformio.ini').write_text('[crossink]\nversion = 1.6.0\n')
        self.runner = FakeRunner({('git', 'tag', '--points-at', 'HEAD'): Result(0, 'v1.6.0.4\nv1.6.0.3\n')})
        self.p = Project(root, self.runner)

    def pio_call(self):
        return [c for c in self.runner.calls if c['argv'][0] == 'pio'][0]

    def test_tagged_head_flashes_release_version(self):
        device.flash(self.p, ports=['/dev/cu.usbmodem1'])
        call = self.pio_call()
        self.assertEqual(call['argv'], ['pio', 'run', '-e', 'x4-pro-personal', '-t', 'upload',
                                        '--upload-port', '/dev/cu.usbmodem1'])
        self.assertEqual(call['env'], {'CROSSINK_PERSONAL_VERSION': '1.6.0.4'})

    def test_untagged_head_flashes_build_zero(self):
        self.runner.responses[('git', 'tag', '--points-at', 'HEAD')] = Result(0, '')
        device.flash(self.p, ports=['/dev/cu.usbmodem1'])
        self.assertIsNone(self.pio_call()['env'])

    def test_debug_flashes_debug_env(self):
        device.flash(self.p, debug=True, ports=['/dev/cu.usbmodem1'])
        self.assertIn('x4-pro-debug', self.pio_call()['argv'])


class MonitorCommandTest(unittest.TestCase):
    def test_macos_uses_bsd_script(self):
        cmd = device.monitor_command('/dev/cu.usbmodem1', Path('/tmp/s.log'), 'Darwin')
        self.assertEqual(cmd[:3], ['script', '-q', '/tmp/s.log'])
        self.assertIn('/dev/cu.usbmodem1', cmd)

    def test_linux_uses_util_linux_script(self):
        cmd = device.monitor_command('/dev/ttyACM0', Path('/tmp/s.log'), 'Linux')
        self.assertEqual(cmd[:3], ['script', '-q', '-c'])
        self.assertEqual(cmd[-1], '/tmp/s.log')


class LogPullTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.volumes = self.base / 'Volumes'
        (self.volumes / 'Macintosh HD').mkdir(parents=True)

    def make_reader_volume(self, name='CROSSINK'):
        vol = self.volumes / name
        (vol / '.crosspoint' / 'logs').mkdir(parents=True)
        (vol / '.crosspoint' / 'logs' / 'log.txt').write_text('boot\n')
        (vol / '.crosspoint' / 'logs' / 'log.1.txt').write_text('older\n')
        (vol / 'crash_report.txt').write_text('panic\n')
        return vol

    def test_no_reader_volume(self):
        with self.assertRaises(PersonalError) as ctx:
            device.find_log_volume(self.volumes)
        self.assertIn('USB Drive', str(ctx.exception))

    def test_two_reader_volumes_refuse(self):
        self.make_reader_volume('A')
        self.make_reader_volume('B')
        with self.assertRaises(PersonalError):
            device.find_log_volume(self.volumes)

    def test_pull_copies_logs_and_crash_report(self):
        self.make_reader_volume()
        p = Project(self.base / 'repo', FakeRunner())
        dest = device.pull_logs(p, self.volumes, now=datetime(2026, 9, 28, 12, 0, 0))
        self.assertEqual(dest, self.base / 'repo' / 'device-logs' / '20260928-120000')
        self.assertEqual(sorted(f.name for f in dest.iterdir()), ['crash_report.txt', 'log.1.txt', 'log.txt'])


if __name__ == '__main__':
    unittest.main()
