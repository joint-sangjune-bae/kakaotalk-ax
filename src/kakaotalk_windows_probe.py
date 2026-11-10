"""Experimental Windows accessibility structure probe; does not read message text."""

import argparse
import contextlib
import ctypes
import io
import json
import multiprocessing
import ntpath
import platform
import sys
from collections import deque
from ctypes import wintypes


CONTROL_TYPES = frozenset({
    "Button", "Calendar", "CheckBox", "ComboBox", "Custom", "DataGrid", "DataItem",
    "Document", "Edit", "Group", "Header", "HeaderItem", "Hyperlink", "Image", "List",
    "ListBox", "ListItem", "ListView", "Menu", "MenuBar", "MenuItem", "Pane", "ProgressBar",
    "RadioButton", "ScrollBar", "Separator", "Slider", "Spinner", "SplitButton", "Static",
    "StatusBar", "Tab", "TabItem", "Table", "Text", "Thumb", "TitleBar", "ToolBar",
    "ToolTip", "Tree", "TreeItem", "TreeView", "Window", "Dialog",
})
PATTERNS = {"text": "iface_text", "value": "iface_value", "scroll": "iface_scroll",
            "selection": "iface_selection", "invoke": "iface_invoke"}


def result(status, reason, **details):
    return {"status": status, "reason": reason, "messageTextRead": False,
            "bodyReadVerified": False, "uiActions": 0, **details}


def collect_structure(root, backend, max_nodes=200, max_depth=6):
    """Read only fixed metadata; never request names, values, titles or text ranges."""
    pending = deque([(root, "0", 0)])
    nodes, errors, skipped = [], 0, 0
    truncated = False
    while pending and len(nodes) < max_nodes:
        wrapper, path, depth = pending.popleft()
        try:
            control_type = (wrapper.element_info.control_type if backend == "uia"
                            else wrapper.friendly_class_name())
        except Exception:
            errors += 1
            nodes.append({"path": path, "controlType": "Unknown", "reason": "metadata_unavailable"})
            continue
        editable = control_type in {"Edit", "ComboBox"} or "richedit" in control_type.casefold()
        node = {"path": path, "controlType": control_type if control_type in CONTROL_TYPES else "Other"}
        nodes.append(node)
        if editable:
            node["subtreeSkipped"] = "editable_control"
            skipped += 1
            continue
        if backend == "uia":
            from pywinauto.uia_defines import NoPatternInterfaceError
            supported = {}
            for name, attribute in PATTERNS.items():
                try:
                    getattr(wrapper, attribute)
                    supported[name] = "available"
                except NoPatternInterfaceError:
                    supported[name] = "unsupported"
                except Exception:
                    supported[name] = "unavailable"
                    errors += 1
            node["patterns"] = supported
        if depth >= max_depth:
            node["childrenNotInspected"] = "depth_limit"
            truncated = True
            continue
        try:
            children = wrapper.children()
        except Exception:
            node["childrenNotInspected"] = "provider_error"
            errors += 1
            continue
        # Keep the queue bounded even when a provider returns a very large child list.
        capacity = max_nodes - len(nodes) - len(pending)
        if len(children) > capacity:
            truncated = True
        pending.extend((child, f"{path}/{index}", depth + 1)
                       for index, child in enumerate(children[:capacity]))
    return result("partial" if truncated or errors else "ok", "structure_collected",
                  backend=backend, nodes=nodes, providerErrorCount=errors,
                  coverage={"scope": "selected_window_structure", "maxNodes": max_nodes,
                            "maxDepth": max_depth, "returnedNodeCount": len(nodes),
                            "truncated": truncated, "skippedEditableSubtrees": skipped,
                            "historyComplete": False})


def window_identity(window_handle):
    """Return process identity locally; the executable path never enters the report."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.IsWindow.argtypes, user32.IsWindow.restype = [wintypes.HWND], wintypes.BOOL
    user32.GetAncestor.argtypes, user32.GetAncestor.restype = [wintypes.HWND, wintypes.UINT], wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes, kernel32.CloseHandle.restype = [wintypes.HANDLE], wintypes.BOOL
    if not user32.IsWindow(window_handle):
        return None
    if user32.GetAncestor(window_handle, 2) != window_handle:  # GA_ROOT
        return None
    process_id = wintypes.DWORD()
    if not user32.GetWindowThreadProcessId(window_handle, ctypes.byref(process_id)):
        return None
    process = kernel32.OpenProcess(0x1000, False, process_id.value)  # QUERY_LIMITED_INFORMATION
    if not process:
        return None
    try:
        length = wintypes.DWORD(32768)
        executable = ctypes.create_unicode_buffer(length.value)
        if not kernel32.QueryFullProcessImageNameW(process, 0, executable, ctypes.byref(length)):
            return None
        return process_id.value, executable.value
    finally:
        kernel32.CloseHandle(process)


def probe_window(window_handle, backend, max_nodes, max_depth):
    identity = window_identity(window_handle)
    if identity is None:
        return result("blocked", "top_level_window_or_process_unavailable")
    process_id, executable = identity
    if ntpath.basename(executable).casefold() != "kakaotalk.exe":
        return result("blocked", "target_process_mismatch")
    from pywinauto import Desktop
    root = Desktop(backend=backend).window(handle=window_handle).wrapper_object()
    if root.element_info.process_id != process_id:
        return result("blocked", "target_process_changed")
    if window_identity(window_handle) != identity:
        return result("blocked", "target_process_changed")
    report = collect_structure(root, backend, max_nodes, max_depth)
    if window_identity(window_handle) != identity:
        return result("blocked", "target_process_changed")
    return report


def probe_worker(connection, request):
    try:
        # Providers and optional imports must not leak incidental console output.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                report = probe_window(**request)
            except ImportError:
                report = result("blocked", "windows_probe_dependencies_required")
            except Exception:
                report = result("failed", "accessibility_probe_failed")
        connection.send(report)
    finally:
        connection.close()


def run_bounded(request, timeout):
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    worker = context.Process(target=probe_worker, args=(sender, request), daemon=True)
    started = False
    try:
        worker.start()
        started = True
        sender.close()
        if not receiver.poll(timeout):
            return result("timeout", "probe_time_limit")
        try:
            return receiver.recv()
        except EOFError:
            return result("failed", "probe_worker_exited")
    finally:
        sender.close()
        receiver.close()
        if started:
            worker.join(timeout=0.2)
            if worker.is_alive():
                worker.terminate()  # Only our probe worker, never the KakaoTalk process.
                worker.join(timeout=1)
            worker.close()


def bounded_integer(label, minimum, maximum, base=10):
    def parse(value):
        try:
            number = int(value, base)
        except ValueError:
            raise argparse.ArgumentTypeError(f"{label} must be an integer") from None
        if not minimum <= number <= maximum:
            raise argparse.ArgumentTypeError(f"{label} must be {minimum}..{maximum}")
        return number
    return parse


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window-handle", required=True,
                        type=bounded_integer("window handle", 1, 2**64 - 1, base=0))
    parser.add_argument("--backend", choices=("uia", "win32"), default="uia")
    parser.add_argument("--max-nodes", type=bounded_integer("max nodes", 1, 1000), default=200)
    parser.add_argument("--max-depth", type=bounded_integer("max depth", 1, 20), default=6)
    parser.add_argument("--timeout", type=bounded_integer("timeout", 1, 60), default=15)
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        report = result("blocked", "windows_required")
    else:
        request = {name: getattr(args, name) for name in ("window_handle", "backend", "max_nodes", "max_depth")}
        try:
            report = run_bounded(request, args.timeout)
        except Exception:
            report = result("failed", "probe_worker_failed")
    report["environment"] = {"os": sys.platform, "release": platform.release(),
                             "version": platform.version(), "python": platform.python_version()}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] in ("ok", "partial") else 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
