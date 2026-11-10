import contextlib
import io
import json
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import kakaotalk_windows_probe as probe


class FixtureControl:
    def __init__(self, role="Window", children=(), broken=False):
        self.element_info = SimpleNamespace(control_type=role)
        self.role, self.controls, self.broken = role, children, broken

    def friendly_class_name(self):
        return self.role

    def children(self):
        if self.broken:
            raise RuntimeError("PRIVATE fixture title and body")
        return list(self.controls)

    def window_text(self):
        raise AssertionError("Message text must never be requested")


class WindowsProbeTests(unittest.TestCase):
    def test_import_is_independent_of_mac_and_windows_runtime_dependencies(self):
        code = '''
import importlib.abc, sys
class BlockRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'fcntl', 'pywinauto', 'kakaotalk_automation'}:
            raise AssertionError('Runtime dependency imported')
sys.meta_path.insert(0, BlockRuntime())
import kakaotalk_windows_probe
'''
        completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=5)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_non_windows_cli_never_starts_a_probe(self):
        with patch.object(sys, "platform", "darwin"), patch.object(probe, "run_bounded") as run:
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(probe.main(["--window-handle", "0x1234"]), 1)
        report = json.loads(output.getvalue())
        self.assertEqual(report["reason"], "windows_required")
        run.assert_not_called()

    def test_wrong_process_is_blocked_before_loading_an_accessibility_backend(self):
        with patch.object(probe, "window_identity", return_value=(42, r"C:\private\Other.exe")):
            report = probe.probe_window(123, "uia", 200, 6)
        self.assertEqual(report["reason"], "target_process_mismatch")
        self.assertNotIn("private", json.dumps(report))

    def test_structure_does_not_read_or_emit_titles_values_or_arbitrary_role_strings(self):
        root = FixtureControl(children=[FixtureControl("Text"), FixtureControl("PRIVATE body")])
        report = probe.collect_structure(root, "win32")
        self.assertEqual([node["controlType"] for node in report["nodes"]], ["Window", "Text", "Other"])
        self.assertFalse(report["messageTextRead"])
        self.assertFalse(report["bodyReadVerified"])
        self.assertNotIn("PRIVATE", json.dumps(report))

    def test_editable_subtree_is_preserved_without_traversal(self):
        root = FixtureControl(children=[FixtureControl("Edit", broken=True), FixtureControl("RichEdit20W", broken=True)])
        report = probe.collect_structure(root, "win32")
        self.assertEqual(report["coverage"]["skippedEditableSubtrees"], 2)
        self.assertEqual(report["providerErrorCount"], 0)

    def test_large_trees_and_depth_limits_return_explicit_partial_coverage(self):
        root = FixtureControl(children=[FixtureControl("Text") for _ in range(20)])
        limited = probe.collect_structure(root, "win32", max_nodes=3)
        self.assertEqual(limited["status"], "partial")
        self.assertEqual(len(limited["nodes"]), 3)
        deep = FixtureControl(children=[FixtureControl(children=[FixtureControl("Text")])])
        limited = probe.collect_structure(deep, "win32", max_depth=1)
        self.assertTrue(limited["coverage"]["truncated"])
        self.assertEqual(limited["nodes"][1]["childrenNotInspected"], "depth_limit")

    def test_provider_failures_keep_partial_structure_without_exception_text(self):
        report = probe.collect_structure(FixtureControl(broken=True), "win32")
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["providerErrorCount"], 1)
        self.assertNotIn("PRIVATE", json.dumps(report))

    def test_uia_pattern_availability_does_not_invoke_controls_or_read_text(self):
        class NoPatternInterfaceError(Exception):
            pass
        class PatternFixture(FixtureControl):
            iface_text = object()
            def __getattr__(self, name):
                raise NoPatternInterfaceError()
        fake_module = SimpleNamespace(NoPatternInterfaceError=NoPatternInterfaceError)
        with patch.dict(sys.modules, {"pywinauto": SimpleNamespace(), "pywinauto.uia_defines": fake_module}):
            report = probe.collect_structure(PatternFixture("Document"), "uia")
        self.assertEqual(report["nodes"][0]["patterns"]["text"], "available")
        self.assertEqual(report["nodes"][0]["patterns"]["invoke"], "unsupported")
        self.assertEqual(report["uiActions"], 0)

    def test_worker_discards_provider_console_output_and_exception_details(self):
        connection = Mock()
        def fail(**request):
            print("PRIVATE provider body")
            raise RuntimeError("PRIVATE exception body")
        with patch.object(probe, "probe_window", side_effect=fail):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                probe.probe_worker(connection, {})
        self.assertEqual(output.getvalue(), "")
        report = connection.send.call_args.args[0]
        self.assertEqual(report["reason"], "accessibility_probe_failed")
        self.assertNotIn("PRIVATE", json.dumps(report))
        connection.close.assert_called_once()

    def test_timeout_terminates_only_the_created_probe_worker(self):
        receiver, sender, worker = Mock(), Mock(), Mock()
        receiver.poll.return_value = False
        worker.is_alive.return_value = True
        context = Mock()
        context.Pipe.return_value = (receiver, sender)
        context.Process.return_value = worker
        with patch.object(probe.multiprocessing, "get_context", return_value=context):
            report = probe.run_bounded({}, 1)
        self.assertEqual(report["reason"], "probe_time_limit")
        worker.terminate.assert_called_once()
        receiver.close.assert_called_once()
        sender.close.assert_called()


if __name__ == "__main__":
    unittest.main()
