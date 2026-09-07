"""
Rewind Universal CLI - Multi-Mode Execution Tracer & Web Scrubber with Universal Hot-Code Sandbox
"""

import argparse
import http.client
import http.server
import io
import json
import os
import re
import socket
import socketserver
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import webbrowser
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

# Allow direct execution from ANY directory
parent_dir = str(Path(__file__).resolve().parent.parent)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from .diff import compute_state_diff, serialize_state
    from .tracer import Tracer, TraceStep, get_global_tracer
except (ImportError, ValueError):
    from rewind.diff import compute_state_diff, serialize_state
    from rewind.tracer import Tracer, TraceStep, get_global_tracer


REWIND_INTERNAL_DIR = os.path.dirname(os.path.abspath(__file__))


# --------------------------------------------------------------------------
# Stream Interceptor (Prints live to terminal + captures into trace)
# --------------------------------------------------------------------------
class LiveTeeStream:
    def __init__(self, original_stream):
        self.orig = original_stream
        self.buf = io.StringIO()

    def write(self, s):
        self.orig.write(s)
        self.buf.write(s)

    def flush(self):
        self.orig.flush()
        self.buf.flush()

    def getvalue(self):
        return self.buf.getvalue()


# --------------------------------------------------------------------------
# Server Management Utilities
# --------------------------------------------------------------------------
def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def find_free_port(start_port: int = 8765, max_attempts: int = 20) -> int:
    for p in range(start_port, start_port + max_attempts):
        if not is_port_in_use(p):
            return p
    return start_port


def stop_running_server(port: int = 8765):
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
        conn.request("POST", "/api/shutdown")
        res = conn.getresponse()
        if res.status == 200:
            print(f"[Rewind] Server on port {port} shut down cleanly.")
            return True
    except Exception:
        pass

    try:
        out = subprocess.check_output(["lsof", "-ti", f":{port}"], text=True).strip()
        if out:
            pids = out.split("\n")
            for pid in pids:
                if pid:
                    subprocess.run(["kill", "-9", pid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"[Rewind] Stopped server processes on port {port} (PIDs: {', '.join(pids)}).")
            return True
    except Exception:
        pass

    print(f"[Rewind] No server was running on port {port}.")
    return False


def check_server_status(port: int = 8765):
    if is_port_in_use(port):
        print(f"[Rewind] Web Viewer is RUNNING at: http://localhost:{port}")
    else:
        print(f"[Rewind] Web Viewer is STOPPED.")


# --------------------------------------------------------------------------
# Universal Hot-Code Sandbox Replay Engine & Disk Patcher
# --------------------------------------------------------------------------
def execute_hot_replay(payload: dict) -> dict:
    code_str = payload.get("code", "")
    filepath = payload.get("filepath", "")

    out_buf = io.StringIO()
    err_buf = io.StringIO()

    start_t = time.perf_counter()
    try:
        compiled = compile(code_str, filepath or "<sandbox>", "exec")
        sandbox_globals = {"__name__": "__main__", "__builtins__": __builtins__, "state": {}}
        
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            exec(compiled, sandbox_globals)

        elapsed = round((time.perf_counter() - start_t) * 1000, 2)
        std_out = out_buf.getvalue()
        std_err = err_buf.getvalue()

        return {
            "success": True,
            "has_crash": False,
            "stdout": std_out,
            "stderr": std_err,
            "timing_ms": elapsed,
            "message": f"Script executed cleanly with zero errors! Output:\n{std_out.strip() or '(none)'}",
        }
    except Exception as e:
        elapsed = round((time.perf_counter() - start_t) * 1000, 2)
        return {
            "success": False,
            "has_crash": True,
            "error": f"{type(e).__name__}: {str(e)}",
            "traceback": traceback.format_exc(),
            "timing_ms": elapsed,
        }


def find_file_in_project(filename: str) -> str:
    if not filename:
        return ""
    if os.path.isabs(filename) and os.path.exists(filename):
        return filename

    base_name = os.path.basename(filename)
    search_dirs = [os.getcwd(), parent_dir, os.path.join(parent_dir, "tests")]

    for d in search_dirs:
        candidate = os.path.join(d, filename)
        if os.path.exists(candidate) and os.path.isfile(candidate):
            return os.path.abspath(candidate)
        candidate_base = os.path.join(d, base_name)
        if os.path.exists(candidate_base) and os.path.isfile(candidate_base):
            return os.path.abspath(candidate_base)

    for root, _, files in os.walk(parent_dir):
        if base_name in files:
            return os.path.abspath(os.path.join(root, base_name))

    return ""


def apply_patch_to_disk(payload: dict) -> dict:
    raw_filepath = payload.get("filepath", "")
    new_code = payload.get("new_code", "")

    target_path = find_file_in_project(raw_filepath)

    if not target_path or not os.path.exists(target_path):
        return {"success": False, "error": f"File not found on disk: '{raw_filepath}'."}

    backup_path = f"{target_path}.bak"
    try:
        with open(target_path, "r", encoding="utf-8") as src, open(backup_path, "w", encoding="utf-8") as dst:
            dst.write(src.read())

        with open(target_path, "w", encoding="utf-8") as f:
            f.write(new_code)

        return {
            "success": True,
            "filepath": target_path,
            "backup": backup_path,
            "message": f"Successfully saved fix to {os.path.basename(target_path)}! (Backup saved at {os.path.basename(backup_path)})",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# --------------------------------------------------------------------------
# Mode 1: Auto Python Script Tracer (Multi-Step Callstack Frame Tracker)
# --------------------------------------------------------------------------
def auto_trace_hook(tracer: Tracer):
    last_state = {}
    frame_steps = {}

    def trace_calls(frame, event, arg):
        nonlocal last_state
        filename = frame.f_code.co_filename
        
        # Only ignore Rewind internal files or stdlib
        if filename.startswith(REWIND_INTERNAL_DIR) or filename.startswith("<") or "/lib/python" in filename or "site-packages" in filename:
            return trace_calls

        func_name = frame.f_code.co_name
        line_no = frame.f_lineno
        frame_id = id(frame)

        if event == "call":
            if func_name in ("<module>", "main"):
                return trace_calls
            tracer._step_counter += 1
            curr_id = tracer._step_counter
            step_inputs = dict(frame.f_locals)
            if tracer.source_code:
                step_inputs["source_code"] = tracer.source_code
            if tracer.source_filepath:
                step_inputs["filepath"] = tracer.source_filepath

            step = TraceStep(
                step_id=curr_id,
                name=f"{func_name}()",
                caller_file=os.path.basename(filename),
                caller_line=line_no,
                inputs=serialize_state(step_inputs),
            )
            step.state_before = serialize_state(last_state)
            frame_steps[frame_id] = step

        elif event == "return":
            step = frame_steps.pop(frame_id, None)
            if step:
                step.output = serialize_state(arg)
                state_now = dict(last_state)
                state_now.update(dict(frame.f_locals))
                if isinstance(arg, dict):
                    state_now.update(arg)
                elif arg is not None:
                    state_now[f"{func_name}_result"] = arg
                step.state_after = serialize_state(state_now)
                step.diff = compute_state_diff(step.state_before, step.state_after)
                step.status = "SUCCESS"
                last_state = dict(state_now)
                tracer.steps.append(step)

        elif event == "exception":
            step = frame_steps.get(frame_id)
            if step:
                exc_type, exc_value, _ = arg
                step.status = "FAILED"
                step.error = {
                    "type": exc_type.__name__,
                    "message": str(exc_value),
                    "source_code": tracer.source_code,
                    "filepath": tracer.source_filepath,
                }

        return trace_calls

    return trace_calls


def run_python_command(args):
    script_path = os.path.abspath(args.script)
    if not os.path.exists(script_path):
        print(f"[Error] File '{args.script}' not found.")
        sys.exit(1)

    script_dir = os.path.dirname(script_path)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)

    raw_source = ""
    with open(script_path, "r", encoding="utf-8") as f:
        raw_source = f.read()

    tracer = get_global_tracer()
    tracer.title = f"Auto-Trace: {os.path.basename(script_path)}"
    tracer.source_code = raw_source
    tracer.source_filepath = script_path
    print(f"[Rewind] Auto-tracing Python script: {script_path}")

    tee_out = LiveTeeStream(sys.stdout)
    tee_err = LiveTeeStream(sys.stderr)

    sys.settrace(auto_trace_hook(tracer))
    start_time = time.time()
    has_error = False
    try:
        code = compile(raw_source, script_path, "exec")
        with redirect_stdout(tee_out), redirect_stderr(tee_err):
            exec(code, {"__name__": "__main__", "__file__": script_path, "__builtins__": __builtins__})
    except SystemExit as se:
        sys.settrace(None)
        if se.code != 0 and se.code is not None:
            has_error = True
            print(f"\n[Rewind] Process exited with error code: {se.code}")
            step_obj = tracer.record_step_data(
                name=f"SystemExit: {se.code}",
                inputs={"exit_code": se.code, "source_code": raw_source, "filepath": script_path, "stdout": tee_out.getvalue(), "stderr": tee_err.getvalue()},
                state_updates={"crashed": True, "error_type": "SystemExit", "error_msg": f"Exited with code {se.code}", "stdout": tee_out.getvalue()},
            )
            step_obj.caller_file = os.path.basename(script_path)
            step_obj.status = "FAILED"
            step_obj.error = {"type": "SystemExit", "message": f"Exit code {se.code}", "source_code": raw_source, "filepath": script_path}
    except Exception as e:
        sys.settrace(None)
        has_error = True
        tb_str = traceback.format_exc()
        print(f"\n[Rewind] Caught Fatal Execution Exception: {type(e).__name__}: {e}")
        
        step_obj = tracer.record_step_data(
            name=f"Fatal Crash: {type(e).__name__}",
            inputs={"error": str(e), "source_code": raw_source, "filepath": script_path, "stdout": tee_out.getvalue(), "stderr": tee_err.getvalue()},
            state_updates={"crashed": True, "error_type": type(e).__name__, "error_msg": str(e), "stdout": tee_out.getvalue()},
        )
        step_obj.caller_file = os.path.basename(script_path)
        step_obj.status = "FAILED"
        step_obj.error = {
            "type": type(e).__name__,
            "message": str(e),
            "traceback": tb_str,
            "source_code": raw_source,
            "filepath": script_path,
        }
    finally:
        sys.settrace(None)
        captured_stdout = tee_out.getvalue()
        captured_stderr = tee_err.getvalue()

        if not has_error and len(tracer.steps) == 0:
            step_obj = tracer.record_step_data(
                name=f"exec: {os.path.basename(script_path)}",
                inputs={"stdout": captured_stdout, "stderr": captured_stderr, "source_code": raw_source, "filepath": script_path},
                state_updates={"stdout": captured_stdout, "status": "COMPLETED"},
            )
            step_obj.caller_file = os.path.basename(script_path)
            step_obj.status = "SUCCESS"

        elapsed = round((time.time() - start_time) * 1000, 2)
        out = args.output or "rewind_trace.json"
        tracer.export(out)

        is_ci = getattr(args, "ci", False) or getattr(args, "headless", False)
        no_open = args.no_open or is_ci

        if is_ci:
            print("\n" + "=" * 60)
            print(" REWIND CI EXECUTION REPORT")
            print("=" * 60)
            print(f" Target Script : {os.path.basename(script_path)}")
            print(f" Total Steps   : {len(tracer.steps)}")
            print(f" Total Time    : {elapsed} ms")
            print(f" Trace Output  : {out}")
            print("-" * 60)
            for idx, st in enumerate(tracer.steps, start=1):
                status_str = f"[{st.status}]" if st.status else "[SUCCESS]"
                dur_str = f"{st.duration_us} us" if hasattr(st, "duration_us") and st.duration_us else "<1 us"
                loc_str = f"{st.caller_file}:L{st.caller_line}" if st.caller_file else ""
                print(f" #{idx:02d} {status_str:<10} {dur_str:>10} | {st.name:<30} {loc_str}")
            print("-" * 60)

            if has_error:
                print(f" RESULT: CRASH DETECTED (Exiting with code 1)")
                print("=" * 60 + "\n")
                sys.exit(1)
            else:
                print(f" RESULT: ALL STEPS PASSED CLEANLY (Exiting with code 0)")
                print("=" * 60 + "\n")
                sys.exit(0)
        else:
            print(f"\n[Rewind] Trace saved: {out} ({len(tracer.steps)} steps, {elapsed} ms)")
            if not no_open:
                view_trace(out, port=args.port)


# --------------------------------------------------------------------------
# Mode 2: Universal Process Wrapper (with Graceful Ctrl+C Handling)
# --------------------------------------------------------------------------
def exec_process_command(args):
    cmd = args.command
    if not cmd:
        print("[Error] No command provided to execute.")
        sys.exit(1)

    tracer = get_global_tracer()
    tracer.title = f"Process Trace: {' '.join(cmd)}"
    print(f"[Rewind] Monitoring process: {' '.join(cmd)}")

    start_time = time.time()
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        print(f"[Rewind] Error: Command '{cmd[0]}' not found on your system.")
        return

    step_id = 0
    full_stdout = []
    return_code = 0
    stderr_out = ""

    try:
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                step_id += 1
                full_stdout.append(line)
                sys.stdout.write(line)
                tracer.record_step_data(
                    name=f"stdout: {line.strip()[:40]}",
                    inputs={"raw": line.strip(), "stdout": "".join(full_stdout)},
                    state_updates={"last_log": line.strip(), "step_count": step_id, "stdout": "".join(full_stdout)},
                )

        stderr_out = process.stderr.read()
        return_code = process.poll()
    except KeyboardInterrupt:
        print("\n[Rewind] Process stopped by user (SIGINT).")
        process.terminate()
        return_code = 130

    if stderr_out or return_code != 0:
        if stderr_out:
            sys.stderr.write(stderr_out)
        
        err_type = "ProcessError"
        err_msg = stderr_out.strip() if stderr_out else f"Process exited with code {return_code}"
        
        if "ModuleNotFoundError" in stderr_out:
            err_type = "ModuleNotFoundError"
        elif "ImportError" in stderr_out:
            err_type = "ImportError"
        elif "TypeError" in stderr_out:
            err_type = "TypeError"
        elif "SyntaxError" in stderr_out:
            err_type = "SyntaxError"
        elif "npm error" in stderr_out:
            err_type = "NpmScriptError"
        elif return_code == 130:
            err_type = "InterruptedByUser"

        step_id += 1
        step_obj = tracer.record_step_data(
            name=f"Crash: {err_type}",
            inputs={"stderr": stderr_out.strip(), "exit_code": return_code, "stdout": "".join(full_stdout)},
            state_updates={"has_error": True, "error_type": err_type, "error_output": stderr_out.strip()},
        )
        step_obj.status = "FAILED"
        step_obj.error = {
            "type": err_type,
            "message": err_msg,
            "traceback": stderr_out.strip(),
        }

    out = args.output or "rewind_trace.json"
    tracer.export(out)

    is_ci = getattr(args, "ci", False) or getattr(args, "headless", False)
    no_open = args.no_open or is_ci

    if is_ci:
        elapsed = round((time.time() - start_time) * 1000, 2)
        print("\n" + "=" * 60)
        print(" REWIND CI PROCESS EXECUTION REPORT")
        print("=" * 60)
        print(f" Command       : {' '.join(cmd)}")
        print(f" Exit Code     : {return_code}")
        print(f" Total Steps   : {len(tracer.steps)}")
        print(f" Total Time    : {elapsed} ms")
        print(f" Trace Output  : {out}")
        print("-" * 60)
        for idx, st in enumerate(tracer.steps, start=1):
            status_str = f"[{st.status}]" if st.status else "[SUCCESS]"
            print(f" #{idx:02d} {status_str:<10} | {st.name:<40}")
        print("-" * 60)

        if return_code != 0 or stderr_out:
            print(f" RESULT: PROCESS FAILURE DETECTED (Exiting with code {return_code or 1})")
            print("=" * 60 + "\n")
            sys.exit(return_code or 1)
        else:
            print(" RESULT: PROCESS COMPLETED CLEANLY (Exiting with code 0)")
            print("=" * 60 + "\n")
            sys.exit(0)
    else:
        print(f"\n[Rewind] Process exited with code {return_code}. Trace saved to: {out}")
        if not no_open:
            view_trace(out, port=args.port)


# --------------------------------------------------------------------------
# Mode 3: Robust Web Viewer Server with Hot-Code Sandbox Endpoints
# --------------------------------------------------------------------------
def view_trace(trace_path: str = "rewind_trace.json", port: int = 8765):
    viewer_dir = Path(__file__).resolve().parent.parent / "viewer"
    if not viewer_dir.exists():
        viewer_dir = Path("viewer").resolve()

    if os.path.exists(trace_path):
        dest_path = viewer_dir / "rewind_trace.json"
        with open(trace_path, "r", encoding="utf-8") as src, open(dest_path, "w", encoding="utf-8") as dst:
            dst.write(src.read())

    active_port = find_free_port(port)
    if active_port != port:
        print(f"[Rewind] Port {port} was busy. Using available port {active_port} instead.")

    class ManagedHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(viewer_dir), **kwargs)

        def log_message(self, format, *args): pass

        def do_POST(self):
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
            try:
                payload = json.loads(body)
            except Exception:
                payload = {}

            if self.path == "/api/shutdown":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(b'{"status":"shutting_down"}')
                print("\n[Rewind] Received shutdown command from browser.")
                threading.Thread(target=lambda: (time.sleep(0.3), server.shutdown())).start()
                return

            elif self.path == "/api/replay":
                result = execute_hot_replay(payload)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode("utf-8"))
                return

            elif self.path == "/api/patch":
                result = apply_patch_to_disk(payload)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode("utf-8"))
                return

            self.send_error(404, "Not Found")

    socketserver.TCPServer.allow_reuse_address = True
    server = socketserver.TCPServer(("", active_port), ManagedHandler)
    url = f"http://localhost:{active_port}"

    print("=" * 55)
    print(f"[Rewind] Web Scrubber active at: {url}")
    print(f"Press Ctrl+C in terminal or click 'Stop Server' in UI to turn off.")
    print("=" * 55)

    threading.Thread(target=lambda: (time.sleep(0.4), webbrowser.open(url)), daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("\n[Rewind] Web server closed successfully.")


# --------------------------------------------------------------------------
# Main Entry Point
# --------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(prog="rewind", description="Rewind - Universal Time-Travel Debugger")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_p = subparsers.add_parser("run", help="Auto-trace a Python script with zero code changes")
    run_p.add_argument("-o", "--output", default="rewind_trace.json")
    run_p.add_argument("-p", "--port", type=int, default=8765)
    run_p.add_argument("--no-open", action="store_true", help="Do not automatically launch the browser")
    run_p.add_argument("--ci", "--headless", dest="ci", action="store_true", help="Run headlessly for CI/CD test automation and return exit code")
    run_p.add_argument("script", help="Target Python script")
    run_p.set_defaults(func=run_python_command)

    exec_p = subparsers.add_parser("exec", help="Trace ANY command/server (Node.js, Go, Docker, etc.)")
    exec_p.add_argument("-o", "--output", default="rewind_trace.json")
    exec_p.add_argument("-p", "--port", type=int, default=8765)
    exec_p.add_argument("--no-open", action="store_true", help="Do not automatically launch the browser")
    exec_p.add_argument("--ci", "--headless", dest="ci", action="store_true", help="Run headlessly for CI/CD test automation and return exit code")
    exec_p.add_argument("command", nargs=argparse.REMAINDER, help="Command and args to execute")
    exec_p.set_defaults(func=exec_process_command)

    view_p = subparsers.add_parser("view", help="Launch the interactive web viewer")
    view_p.add_argument("-p", "--port", type=int, default=8765)
    view_p.add_argument("trace_file", nargs="?", default="rewind_trace.json")
    view_p.set_defaults(func=lambda a: view_trace(a.trace_file, a.port))

    stop_p = subparsers.add_parser("stop", help="Stop any running Rewind web viewer server")
    stop_p.add_argument("-p", "--port", type=int, default=8765)
    stop_p.set_defaults(func=lambda a: stop_running_server(a.port))

    status_p = subparsers.add_parser("status", help="Check status of Rewind web viewer")
    status_p.add_argument("-p", "--port", type=int, default=8765)
    status_p.set_defaults(func=lambda a: check_server_status(a.port))

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
