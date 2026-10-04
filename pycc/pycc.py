#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys

# 检查是否在 Termux 环境
if not os.path.exists('/data/data/com.termux'):
    print("pycc: error: Only Termux", file=sys.stderr)
    sys.exit(1)

import shutil
import subprocess
import re
import tempfile

VERSION = "1.5.2"
DESCRIPTION = "Compile python to ELF (Only Termux)"

RED = '\033[91m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
NC = '\033[0m'

VERBOSE = False
QUIET = False

def print_error(msg):
    print(f"pycc: {RED}error:{NC} {msg}", file=sys.stderr)

def print_warning(msg):
    if not QUIET:
        print(f"pycc: {YELLOW}warning:{NC} {msg}", file=sys.stderr)

def print_info(msg):
    if VERBOSE and not QUIET:
        print(f"pycc: {msg}", file=sys.stderr)

def print_debug(msg):
    if VERBOSE:
        print(msg, file=sys.stderr)

def print_cmd(cmd):
    if VERBOSE:
        print(' '.join(cmd), file=sys.stderr)

PY_VERSION_OVERRIDE = None

def get_python_version():
    global PY_VERSION_OVERRIDE
    if PY_VERSION_OVERRIDE:
        return PY_VERSION_OVERRIDE
    env_version = os.environ.get('PYCC_PY_VERSION')
    if env_version:
        return env_version
    try:
        result = subprocess.run(
            [sys.executable, '-c', 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except:
        pass
    return "3.13"

def find_compiler():
    for name in ['clang', 'clang-18', 'clang-17', 'clang-16']:
        if shutil.which(name):
            return ('clang', name)
    for name in ['gcc', 'gcc-13', 'gcc-12']:
        if shutil.which(name):
            return ('gcc', name)
    return (None, None)

def get_best_flags(compiler_type):
    if compiler_type == 'clang':
        return ['-O3', '-march=native', '-ftree-vectorize', '-funroll-loops', '-fopenmp']
    else:
        return ['-O3', '-march=native', '-funroll-loops', '-fopenmp']

def find_python_dev():
    py_version = get_python_version()
    paths = [
        f"/data/data/com.termux/files/usr/include/python{py_version}",
        f"/usr/include/python{py_version}",
        f"/usr/local/include/python{py_version}",
        f"{sys.prefix}/include/python{py_version}",
    ]
    for path in paths:
        if os.path.exists(path) and os.path.exists(os.path.join(path, "Python.h")):
            return path
    return None

def get_python_lib():
    py_version = get_python_version()
    paths = [
        "/data/data/com.termux/files/usr/lib",
        "/usr/lib",
        "/usr/local/lib",
        f"{sys.prefix}/lib",
    ]
    lib_name = f"python{py_version}"
    for path in paths:
        if os.path.exists(os.path.join(path, f"lib{lib_name}.so")):
            return path, lib_name
    return "/data/data/com.termux/files/usr/lib", lib_name

def get_temp_dir():
    paths = [
        os.path.expanduser('~/tmp/pycc_build'),
        os.path.join(tempfile.gettempdir(), 'pycc_build'),
        '/tmp/pycc_build',
    ]
    for path in paths:
        try:
            os.makedirs(path, exist_ok=True)
            test_file = os.path.join(path, 'test_write')
            with open(test_file, 'w') as f:
                f.write('test')
            os.unlink(test_file)
            return path
        except:
            continue
    return os.path.join(tempfile.gettempdir(), 'pycc_build')

def is_valid_module_name(name):
    return re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name) is not None

def fix_module_name(input_file):
    base_name = os.path.splitext(os.path.basename(input_file))[0]
    if is_valid_module_name(base_name):
        return input_file, None
    new_base_name = f"pycc_v{VERSION}_{base_name}"
    new_base_name = re.sub(r'[^a-zA-Z0-9_]', '_', new_base_name)
    if not re.match(r'^[a-zA-Z_]', new_base_name):
        new_base_name = '_' + new_base_name
    new_file = os.path.join(os.path.dirname(input_file), f"{new_base_name}.py")
    print_warning(f"Invalid module name '{base_name}', renamed to '{new_base_name}'")
    shutil.copy2(input_file, new_file)
    return new_file, new_base_name

def add_compile_marker(output_file):
    try:
        with open(output_file, 'ab') as f:
            f.write(f"\nCompiled by pycc {VERSION}\0".encode())
    except:
        pass

def get_optimization_flags(opt_level, compiler_type):
    if opt_level == 'best':
        return get_best_flags(compiler_type)
    elif opt_level == 'fast':
        return ['-O2', '-march=native']
    elif opt_level == 'size':
        return ['-Os']
    elif opt_level == 'none':
        return ['-O0']
    else:
        return ['-O2']

def compile_to_so(input_file, output, opt_level, other_flags, site_install, clang_extra):
    file_ext = os.path.splitext(input_file)[1].lower()
    
    py_version = get_python_version()
    py_include = find_python_dev()
    py_lib_path, py_lib_name = get_python_lib()
    if not py_include:
        py_include = f"/data/data/com.termux/files/usr/include/python{py_version}"
    
    compiler_type, compiler = find_compiler()
    if not compiler:
        print_error("No compiler found")
        sys.exit(1)
    
    work_dir = get_temp_dir()
    os.makedirs(work_dir, exist_ok=True)
    
    try:
        if output:
            so_output = output
        else:
            base_name = os.path.splitext(os.path.basename(input_file))[0]
            so_output = f"{base_name}.so"
        
        if file_ext in ['.py', '.pyx']:
            module_name = os.path.splitext(os.path.basename(so_output))[0]
            if not is_valid_module_name(module_name):
                module_name = os.path.splitext(os.path.basename(input_file))[0]
            
            module_pyx = os.path.join(work_dir, f"{module_name}.pyx")
            shutil.copy2(input_file, module_pyx)
            
            out_file = os.path.join(work_dir, f"{module_name}.c")
            cmd = ['cython', '--embed', '-3', module_pyx, '-o', out_file]
            print_cmd(cmd)
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print_error("Cython error:")
                print(result.stderr, file=sys.stderr)
                sys.exit(1)
            source_file = out_file
        else:
            source_file = input_file
        
        opt_flags = get_optimization_flags(opt_level, compiler_type)
        
        cmd = [compiler, '-shared', '-fPIC'] + opt_flags + ['-o', so_output, source_file,
               f'-I{py_include}', f'-L{py_lib_path}', f'-l{py_lib_name}',
               '-lpthread', '-lm', '-lutil', '-ldl']
        
        cmd += other_flags
        cmd += clang_extra
        
        print_cmd(cmd)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print_error("Compilation error:")
            print(result.stderr, file=sys.stderr)
            sys.exit(1)
        
        os.chmod(so_output, 0o755)
        add_compile_marker(so_output)
        
        if site_install:
            site_dir = f"{py_lib_path}/python{py_version}/site-packages"
            if not os.path.exists(site_dir):
                site_dir = os.path.join(sys.prefix, 'lib', f'python{py_version}', 'site-packages')
            target = os.path.join(site_dir, os.path.basename(so_output))
            shutil.copy2(so_output, target)
            os.chmod(target, 0o755)
            if VERBOSE and not QUIET:
                print_info(f"Installed to: {target}")
        elif VERBOSE and not QUIET:
            print_info(f"Shared library: {so_output}")
            
    finally:
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir)

def compile_executable(input_file, output, opt_level, other_flags, run, script_args, clang_extra):
    file_ext = os.path.splitext(input_file)[1].lower()
    
    py_version = get_python_version()
    py_include = find_python_dev()
    py_lib_path, py_lib_name = get_python_lib()
    if not py_include:
        py_include = f"/data/data/com.termux/files/usr/include/python{py_version}"
    
    compiler_type, compiler = find_compiler()
    if not compiler:
        print_error("No compiler found")
        sys.exit(1)
    
    work_dir = get_temp_dir()
    os.makedirs(work_dir, exist_ok=True)
    
    try:
        if file_ext in ['.py', '.pyx']:
            base_name = os.path.splitext(os.path.basename(input_file))[0]
            pyx_file = os.path.join(work_dir, f"{base_name}.pyx")
            shutil.copy2(input_file, pyx_file)
            
            out_file = os.path.join(work_dir, f"{base_name}.c")
            cmd = ['cython', '--embed', '-3', pyx_file, '-o', out_file]
            print_cmd(cmd)
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print_error("Cython error:")
                print(result.stderr, file=sys.stderr)
                sys.exit(1)
            source_file = out_file
        else:
            base_name = os.path.splitext(os.path.basename(input_file))[0]
            source_file = input_file
        
        if run:
            final_output = os.path.join(work_dir, f"{base_name}.out")
        else:
            final_output = output if output else f"./{base_name}.out"
        
        opt_flags = get_optimization_flags(opt_level, compiler_type)
        
        compile_cmd = [compiler] + opt_flags + ['-o', final_output, source_file,
                      f'-I{py_include}', f'-L{py_lib_path}', f'-l{py_lib_name}',
                      '-lpthread', '-lm', '-lutil', '-ldl']
        
        compile_cmd += other_flags
        compile_cmd += clang_extra
        
        print_cmd(compile_cmd)
        result = subprocess.run(compile_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print_error("Compilation error:")
            print(result.stderr, file=sys.stderr)
            sys.exit(1)
        
        os.chmod(final_output, 0o755)
        add_compile_marker(final_output)
        
        if not run and not QUIET:
            print_info(f"Executable: {final_output}")
        if run:
            subprocess.run([final_output] + script_args)
            
    finally:
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir)

def generate_cpp(input_file, output, is_cpp, dry_run):
    original_input = input_file
    input_file, new_name = fix_module_name(input_file)
    should_cleanup = new_name is not None
    
    work_dir = get_temp_dir()
    os.makedirs(work_dir, exist_ok=True)
    
    try:
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        pyx_file = os.path.join(work_dir, f"{base_name}.pyx")
        shutil.copy2(input_file, pyx_file)
        
        if is_cpp:
            out_file = os.path.join(work_dir, f"{base_name}.cpp")
            cython_cmd = ['cython', '--embed', '-3', '--cplus', pyx_file, '-o', out_file]
        else:
            out_file = os.path.join(work_dir, f"{base_name}.c")
            cython_cmd = ['cython', '--embed', '-3', pyx_file, '-o', out_file]
        
        if dry_run:
            print(' '.join(cython_cmd))
            return
        
        result = subprocess.run(cython_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print_error("Cython error:")
            print(result.stderr, file=sys.stderr)
            sys.exit(1)
        
        if output and os.path.abspath(output) != os.path.abspath(out_file):
            shutil.copy2(out_file, output)
            if VERBOSE and not QUIET:
                print_info(f"Generated: {output}")
        else:
            default_output = f"{base_name}.{'cpp' if is_cpp else 'c'}"
            shutil.copy2(out_file, default_output)
            if VERBOSE and not QUIET:
                print_info(f"Generated: {default_output}")
            
    finally:
        if os.path.exists(work_dir) and not dry_run:
            shutil.rmtree(work_dir)
        if should_cleanup and os.path.exists(input_file):
            os.remove(input_file)

def parse_clang_extra(args):
    clang_extra = []
    new_args = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ['-clg', '--clang']:
            i += 1
            while i < len(args):
                clang_extra.append(args[i])
                i += 1
        else:
            new_args.append(arg)
            i += 1
    return new_args, clang_extra

def main():
    global VERBOSE, QUIET, PY_VERSION_OVERRIDE
    
    sys_argv, clang_extra = parse_clang_extra(sys.argv)
    sys.argv = sys_argv
    
    # 处理 --python
    if '--python' in sys.argv:
        idx = sys.argv.index('--python')
        if idx + 1 < len(sys.argv):
            PY_VERSION_OVERRIDE = sys.argv[idx + 1]
            sys.argv = sys.argv[:idx] + sys.argv[idx+2:]
        else:
            print_error("--python requires a version argument")
            sys.exit(1)
    
    if '--version' in sys.argv:
        print(f"pycc {VERSION}")
        print(DESCRIPTION)
        return
    
    if '--help' in sys.argv or '-h' in sys.argv:
        print(f"pycc {VERSION} - {DESCRIPTION}")
        print("\nUsage: pycc [options] <input.py/.pyx/.c/.cpp>")
        print("\nOptions:")
        print("  -O, --option        Pass extra args to clang (any position)")
        print("  -B, --best          Best optimization")
        print("  --python <ver>      Specify Python version (default: PYCC_PY_VERSION)")
        print("  -o, --output        Output file")
        print("  -run                Compile and run")
        print("  -c                  Generate C file (.c)")
        print("  -cpp                Generate C++ file (.cpp)")
        print("  -so                 Generate shared library (.so)")
        print("  --site, -s          Install to site-packages (with -so)")
        print("  -v                  Verbose mode")
        print("  -q                  Quiet mode")
        print("  -###                Show commands only")
        print("  --version           Version info")
        print("  --help, -h          This help")
        print("\nEnvironment:")
        print("  PYCC_PY_VERSION     Python version")
        return
    
    if len(sys.argv) < 2:
        print_error("Missing input file")
        sys.exit(1)
    
    input_file = None
    other_args = []
    script_args = []
    opt_level = 'default'
    clang_option_args = []
    
    args_iter = iter(sys.argv[1:])
    for arg in args_iter:
        if not arg.startswith('-') and input_file is None:
            input_file = arg
        elif arg.startswith('-'):
            if arg == '-v':
                VERBOSE = True
            elif arg == '-q':
                QUIET = True
            elif arg in ['-B', '--best']:
                opt_level = 'best'
            elif arg in ['-O', '--option']:
                for a in args_iter:
                    clang_option_args.append(a)
            else:
                other_args.append(arg)
                if arg in ['-o', '--output']:
                    try:
                        other_args.append(next(args_iter))
                    except StopIteration:
                        pass
        else:
            (script_args if input_file is not None else other_args).append(arg)
    
    if not input_file or not os.path.exists(input_file):
        print_error(f"File not found: {input_file}")
        sys.exit(1)
    
    all_clang_extra = clang_option_args + clang_extra
    
    file_ext = os.path.splitext(input_file)[1].lower()
    is_python = file_ext == '.py'
    is_pyx = file_ext == '.pyx'
    is_c = file_ext in ['.c', '.cpp', '.cc', '.cxx']
    
    output_c = '-c' in other_args
    output_cpp = '-cpp' in other_args
    output_so = '-so' in other_args
    run = '-run' in other_args
    dry_run = '-###' in other_args
    site_install = '--site' in other_args or '-s' in other_args
    
    if sum([output_c, output_cpp, output_so]) > 1:
        print_error("Only one of -c, -cpp, -so allowed")
        sys.exit(1)
    
    if is_c and not (output_c or output_cpp or output_so):
        compiler_type, compiler = find_compiler()
        if not compiler:
            print_error("No compiler found")
            sys.exit(1)
        
        cmd = [compiler]
        if opt_level == 'best':
            cmd.extend(get_best_flags(compiler_type))
        else:
            cmd.append('-O2')
        cmd.append(input_file)
        
        has_output = any(a in ['-o', '--output'] for a in other_args)
        if not has_output:
            base_name = os.path.splitext(os.path.basename(input_file))[0]
            cmd.extend(['-o', f"{base_name}.out"])
        
        for a in other_args:
            if a not in ['-o', '--output']:
                cmd.append(a)
        
        cmd += all_clang_extra
        
        print_cmd(cmd)
        sys.exit(subprocess.run(cmd).returncode)
    
    if run:
        other_args = [a for a in other_args if a != '-run']
    if dry_run:
        other_args = [a for a in other_args if a != '-###']
    
    for flag in ['-c', '-cpp', '-so', '--site', '-s']:
        if flag in other_args:
            other_args = [a for a in other_args if a != flag]
    
    other_flags = [a for a in other_args if a.startswith('-') and a not in ['-o', '--output']]
    output = None
    for i, a in enumerate(other_args):
        if a in ['-o', '--output'] and i + 1 < len(other_args):
            output = other_args[i + 1]
            break
    
    if not (is_python or is_pyx or is_c):
        print_error(f"Unsupported file type: {input_file}")
        sys.exit(1)
    
    if output_c or output_cpp:
        generate_cpp(input_file, output, output_cpp, dry_run)
        return
    
    if output_so:
        compile_to_so(input_file, output, opt_level, other_flags, site_install, all_clang_extra)
        return
    
    compile_executable(input_file, output, opt_level, other_flags, run, script_args, all_clang_extra)

if __name__ == '__main__':
    main()
