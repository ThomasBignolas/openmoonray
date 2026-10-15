"""Run an isolated Windows scene test with inherited CPU and memory limits."""
import argparse
import ctypes as c
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import subprocess
import time


class BasicLimits(c.Structure):
    _fields_ = [('ProcessUserTime', c.c_int64), ('JobUserTime', c.c_int64),
                ('Flags', w.DWORD), ('MinWorkingSet', c.c_size_t), ('MaxWorkingSet', c.c_size_t),
                ('ActiveProcesses', w.DWORD), ('Affinity', c.c_size_t),
                ('PriorityClass', w.DWORD), ('SchedulingClass', w.DWORD)]


class IoCounters(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in
                ('ReadOperations', 'WriteOperations', 'OtherOperations', 'ReadBytes', 'WriteBytes', 'OtherBytes')]


class ExtendedLimits(c.Structure):
    _fields_ = [('Basic', BasicLimits), ('Io', IoCounters), ('ProcessMemory', c.c_size_t),
                ('JobMemory', c.c_size_t), ('PeakProcessMemory', c.c_size_t), ('PeakJobMemory', c.c_size_t)]


class MemoryStatus(c.Structure):
    _fields_ = [('Length', w.DWORD), ('Load', w.DWORD)] + [(name, c.c_uint64) for name in
                ('TotalPhysical', 'AvailablePhysical', 'TotalPageFile', 'AvailablePageFile',
                 'TotalVirtual', 'AvailableVirtual', 'AvailableExtendedVirtual')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--threads', type=int, default=max(1, (os.cpu_count() or 2) - 1))
    parser.add_argument('--memory-gb', type=float, default=16)
    parser.add_argument('--min-free-gb', type=float, default=6)
    parser.add_argument('--timeout', type=float, default=900)
    parser.add_argument('--log', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if os.name != 'nt' or not command or args.threads < 1:
        parser.error('Requires Windows, a command and a positive thread count')
    kernel = c.WinDLL('kernel32', use_last_error=True)
    signatures = {
        'CreateJobObjectW': ([c.c_void_p, w.LPCWSTR], w.HANDLE),
        'SetInformationJobObject': ([w.HANDLE, c.c_int, c.c_void_p, w.DWORD], w.BOOL),
        'QueryInformationJobObject': ([w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.c_void_p], w.BOOL),
        'AssignProcessToJobObject': ([w.HANDLE, w.HANDLE], w.BOOL),
        'TerminateJobObject': ([w.HANDLE, w.UINT], w.BOOL),
        'CloseHandle': ([w.HANDLE], w.BOOL),
        'GlobalMemoryStatusEx': ([c.POINTER(MemoryStatus)], w.BOOL),
        'GetCurrentProcess': ([], w.HANDLE),
        'GetProcessAffinityMask': ([w.HANDLE, c.POINTER(c.c_size_t), c.POINTER(c.c_size_t)], w.BOOL),
    }
    for name, (arguments, result) in signatures.items():
        getattr(kernel, name).argtypes, getattr(kernel, name).restype = arguments, result

    def check(result):
        if not result:
            raise c.WinError(c.get_last_error())
        return result

    available = MemoryStatus()
    available.Length = c.sizeof(available)
    check(kernel.GlobalMemoryStatusEx(c.byref(available)))
    if available.AvailablePhysical < args.min_free_gb * 2**30:
        raise RuntimeError('Insufficient free physical memory to start the scene test')
    process_mask, system_mask = c.c_size_t(), c.c_size_t()
    check(kernel.GetProcessAffinityMask(kernel.GetCurrentProcess(), c.byref(process_mask), c.byref(system_mask)))
    cpus = [bit for bit in range(64) if process_mask.value & (1 << bit)]
    count = min(args.threads, max(1, len(cpus) - 1))
    mask = sum(1 << bit for bit in cpus[:count])
    job = check(kernel.CreateJobObjectW(None, None))
    limits = ExtendedLimits()
    # Kill only this test's descendants on close; bound aggregate committed
    # memory and CPU affinity, including worker libraries' auxiliary threads.
    limits.Basic.Flags = 0x2000 | 0x200 | 0x10
    limits.Basic.Affinity = mask
    limits.JobMemory = int(args.memory_gb * 2**30)
    process = None
    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    report = {'command': command, 'logical_cpus_used': count, 'affinity_mask': hex(mask),
              'memory_limit_gb': args.memory_gb, 'minimum_free_gb': args.min_free_gb,
              'status': 'starting', 'peak_commit_gb': 0.0}

    def save():
        report['seconds'] = round(time.monotonic() - started, 2)
        temporary = args.report.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, indent=2) + '\n')
        temporary.replace(args.report)

    try:
        check(kernel.SetInformationJobObject(job, 9, c.byref(limits), c.sizeof(limits)))
        with args.log.open('w') as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            check(kernel.AssignProcessToJobObject(job, int(process._handle)))
            report.update(pid=process.pid, status='running')
            while process.poll() is None:
                check(kernel.GlobalMemoryStatusEx(c.byref(available)))
                check(kernel.QueryInformationJobObject(job, 9, c.byref(limits), c.sizeof(limits), None))
                report['free_physical_gb'] = round(available.AvailablePhysical / 2**30, 3)
                report['peak_commit_gb'] = round(limits.PeakJobMemory / 2**30, 3)
                reason = None
                if available.AvailablePhysical < args.min_free_gb * 2**30:
                    reason = 'stopped_low_system_memory'
                elif time.monotonic() - started > args.timeout:
                    reason = 'stopped_timeout'
                if reason:
                    report['status'] = reason
                    check(kernel.TerminateJobObject(job, 124))
                    break
                save()
                time.sleep(1)
            report['returncode'] = process.wait(timeout=15)
            if report['status'] == 'running':
                report['status'] = 'complete' if process.returncode == 0 else 'failed'
            save()
    except Exception as error:
        report.update(status='guard_error', error=str(error))
        kernel.TerminateJobObject(job, 125)
        if process and process.poll() is None:
            process.kill()
            process.wait(timeout=15)
        save()
        raise
    finally:
        kernel.CloseHandle(job)
    print(json.dumps(report), flush=True)
    return 0 if report['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
