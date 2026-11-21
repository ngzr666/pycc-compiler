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
import tokenize
import sysconfig

VERSION = "1.6.0"
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

def get_ext_suffix():
    """Python C extension suffix, e.g. .cpython-313-aarch64-linux-android.so"""
    env_suffix = os.environ.get('PYCC_EXT_SUFFIX')
    if env_suffix:
        return env_suffix if env_suffix.startswith('.') else '.' + env_suffix
    cur_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    if get_python_version() == cur_version:
        suffix = sysconfig.get_config_var('EXT_SUFFIX')
        if suffix:
            return suffix
    return f".cpython-{get_python_version().replace('.', '')}-aarch64-linux-android.so"

PY_SOURCE_EXTS = ('.py', '.pyx')
C_SOURCE_EXTS = ('.c', '.cpp', '.cc', '.cxx')

def is_valid_module_name(name):
    return re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name) is not None

def sanitize_module_name(name):
    name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    if not re.match(r'^[a-zA-Z_]', name):
        name = '_' + name
    return name

def collect_directory_files(input_dir, include_c=True):
    """Source files directly inside input_dir (no recursion)."""
    exts = PY_SOURCE_EXTS + (C_SOURCE_EXTS if include_c else ())
    try:
        entries = sorted(os.listdir(input_dir))
    except OSError as e:
        print_error(f"Cannot read directory '{input_dir}': {e}")
        sys.exit(1)
    files = []
    for name in entries:
        path = os.path.join(input_dir, name)
        if os.path.isfile(path) and name.lower().endswith(exts):
            files.append(path)
    return files

def choose_entry_file(files, as_so, entry_name=None):
    """Pick the module that becomes the program / package entry point."""
    if entry_name:
        target = os.path.splitext(os.path.basename(entry_name))[0]
        for f in files:
            if os.path.splitext(os.path.basename(f))[0] == target:
                return f
        print_error(f"Entry module not found in directory: {entry_name}")
        sys.exit(1)

    by_name = {os.path.splitext(os.path.basename(f))[0]: f for f in files}
    if as_so:
        order = ['__init__', '__main__', 'main']
    else:
        order = ['__main__', 'main', '__init__']
    for name in order:
        if name in by_name:
            return by_name[name]

    dir_name = os.path.basename(os.path.dirname(os.path.abspath(files[0])))
    if dir_name in by_name:
        return by_name[dir_name]

    if len(files) == 1:
        return files[0]
    return None

def read_python_source(path):
    try:
        with tokenize.open(path) as f:
            return f.read()
    except (OSError, SyntaxError, UnicodeDecodeError) as e:
        print_error(f"Cannot read '{path}': {e}")
        sys.exit(1)

def inject_bootstrap(source, bootstrap):
    """Insert bootstrap code after the module docstring / __future__ imports."""
    import ast
    try:
        tree = ast.parse(source)
    except SyntaxError:
        tree = None

    lines = source.splitlines(keepends=True)

    if tree is not None:
        insert_after = 0
        body = tree.body
        idx = 0
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(getattr(body[0], 'value', None), ast.Constant)
                and isinstance(body[0].value.value, str)):
            insert_after = body[0].end_lineno
            idx = 1
        while (idx < len(body) and isinstance(body[idx], ast.ImportFrom)
               and body[idx].module == '__future__'):
            insert_after = body[idx].end_lineno
            idx += 1
    else:
        # Cython-only syntax: keep leading comments/blanks (coding cookie,
        # "cython:" directives) at the very top.
        insert_after = 0
        while (insert_after < len(lines)
               and (not lines[insert_after].strip()
                    or lines[insert_after].lstrip().startswith('#'))):
            insert_after += 1

    head = ''.join(lines[:insert_after])
    if head and not head.endswith('\n'):
        head += '\n'
    return head + bootstrap + ''.join(lines[insert_after:])


def build_so_bootstrap(sibling_names, entry_basename):
    """Code prepended to the embedded entry module of a bundled .so.

    All the compiled modules live in the same .so, so sibling imports are
    resolved by loading the same file with ExtensionFileLoader (which calls
    PyInit_<name> for the requested module).
    """
    names = sorted(sibling_names)
    lines = [
        "import sys as _pycc_sys",
        "import importlib.machinery as _pycc_machinery",
        "import importlib.util as _pycc_util",
        "",
        "__package__ = __name__",
        "__path__ = []",
        "_PYCC_SIBLINGS = {" + ", ".join(repr(n) for n in names) + "}",
        "",
        "class _PyccFinder:",
        "    def find_spec(self, fullname, path=None, target=None):",
        "        if fullname.rsplit('.', 1)[-1] not in _PYCC_SIBLINGS:",
        "            return None",
        "        loader = _pycc_machinery.ExtensionFileLoader(fullname, __file__)",
        "        return _pycc_util.spec_from_file_location(fullname, __file__, loader=loader)",
        "",
        "_pycc_sys.meta_path.insert(0, _PyccFinder())",
    ]
    if entry_basename and entry_basename != '__init__':
        lines += [
            "",
            "_pycc_sys.modules.setdefault(" + repr(entry_basename) +
            ", _pycc_sys.modules[__name__])",
        ]
    return '\n'.join(lines) + '\n'


def build_registry_source(sibling_names):
    """C file that registers sibling modules before Py_Initialize.

    Cython's --embed main calls PyImport_AppendInittab() for the entry
    module before initializing Python.  A constructor does the same for
    every sibling, so ordinary "import name" statements work at runtime.
    """
    lines = ['#include <Python.h>', '']
    for name in sibling_names:
        lines.append(f'extern PyObject *PyInit_{name}(void);')
    lines.append('')
    lines.append('static void pycc_append_inittab(void) {')
    for name in sibling_names:
        lines.append(f'    PyImport_AppendInittab("{name}", PyInit_{name});')
    lines.append('}')
    lines.append('')
    lines.append('#if defined(__GNUC__) || defined(__clang__)')
    lines.append('__attribute__((constructor))')
    lines.append('static void pycc_init_modules(void) {')
    lines.append('    pycc_append_inittab();')
    lines.append('}')
    lines.append('#endif')
    return '\n'.join(lines) + '\n'


def prepare_bundle_modules(files, entry_file, entry_module_name, work_dir, as_so):
    """Copy sources into work_dir and return (module_name, pyx_path, is_entry)."""
    modules = []
    seen = set()
    entry_abs = os.path.abspath(entry_file)

    entry_basename = os.path.splitext(os.path.basename(entry_file))[0]
    siblings = set()
    for path in files:
        if os.path.abspath(path) != entry_abs:
            siblings.add(sanitize_module_name(
                os.path.splitext(os.path.basename(path))[0]))

    for path in files:
        is_entry = os.path.abspath(path) == entry_abs
        base = os.path.splitext(os.path.basename(path))[0]
        module_name = entry_module_name if is_entry else sanitize_module_name(base)
        if module_name in seen:
            print_error(f"Duplicate module name after sanitizing: {module_name}")
            sys.exit(1)
        seen.add(module_name)

        source = read_python_source(path)
        if is_entry and as_so:
            source = inject_bootstrap(
                source, build_so_bootstrap(siblings, entry_basename))

        pyx_path = os.path.join(work_dir, f"{module_name}.pyx")
        with open(pyx_path, 'w', encoding='utf-8') as f:
            f.write(source)
        modules.append((module_name, pyx_path, is_entry))

    return modules


def cython_generate(pyx_path, c_path, embed):
    cmd = ['cython']
    if embed:
        cmd.append('--embed')
    cmd += ['-3', pyx_path, '-o', c_path]
    print_cmd(cmd)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print_error("Cython error:")
        print(result.stderr, file=sys.stderr)
        sys.exit(1)


def compile_object(c_path, o_path, compiler, opt_flags, py_include,
                   other_flags, clang_extra):
    cmd = [compiler, '-c', '-fPIC'] + opt_flags
    cmd += ['-o', o_path, c_path, f'-I{py_include}']
    cmd += other_flags
    cmd += clang_extra
    print_cmd(cmd)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print_error("Compilation error:")
        print(result.stderr, file=sys.stderr)
        sys.exit(1)


def link_bundle(objects, output, as_so, compiler, opt_flags,
                py_lib_path, py_lib_name, other_flags, clang_extra):
    cmd = [compiler]
    if as_so:
        cmd.append('-shared')
    cmd += opt_flags
    cmd += ['-o', output] + objects
    cmd += [f'-L{py_lib_path}', f'-l{py_lib_name}',
            '-lpthread', '-lm', '-lutil', '-ldl']
    cmd += other_flags
    cmd += clang_extra
    print_cmd(cmd)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print_error("Link error:")
        print(result.stderr, file=sys.stderr)
        sys.exit(1)

def extract_output_arg(args):
    for i, a in enumerate(args):
        if a in ['-o', '--output'] and i + 1 < len(args):
            return args[i + 1]
    return None

def split_directory_args(args):
    """Split raw argument list into (output, extra compiler flags)."""
    mode_flags = {'--dir', '--dir-one', '-one', '-so', '-run',
                  '--site', '-s', '-###', '-c', '-cpp'}
    output = None
    flags = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ['-o', '--output']:
            if i + 1 < len(args):
                output = args[i + 1]
                i += 2
            else:
                i += 1
            continue
        if a in mode_flags:
            i += 1
            continue
        flags.append(a)
        i += 1
    return output, [f for f in flags if f.startswith('-')]

def compile_c_source(input_file, output, opt_level, other_flags, clang_extra):
    compiler_type, compiler = find_compiler()
    if not compiler:
        print_error("No compiler found")
        sys.exit(1)

    if not output:
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        output = base_name

    cmd = [compiler]
    cmd.extend(get_optimization_flags(opt_level, compiler_type))
    cmd.append(input_file)
    cmd.extend(['-o', output])
    cmd += other_flags
    cmd += clang_extra

    print_cmd(cmd)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print_error("Compilation error:")
        print(result.stderr, file=sys.stderr)
        sys.exit(1)

    os.chmod(output, 0o755)
    add_compile_marker(output)

def compile_directory(input_dir, output, opt_level, other_flags, site_install,
                      as_so, run, script_args, clang_extra):
    """Compile every file in a directory into its own output file."""
    if as_so and run:
        print_error("-run cannot be used with -so")
        sys.exit(1)

    files = collect_directory_files(input_dir, include_c=not as_so)
    if not files:
        print_error(f"No source files found in: {input_dir}")
        sys.exit(1)

    out_dir = os.path.abspath(output) if output else os.path.abspath(input_dir)
    if os.path.exists(out_dir) and not os.path.isdir(out_dir):
        print_error(f"Output is not a directory: {out_dir}")
        sys.exit(1)
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError as e:
        print_error(f"Cannot create output directory '{out_dir}': {e}")
        sys.exit(1)

    print_info(f"Compiling {len(files)} file(s) from {input_dir} to {out_dir}")

    failed = []
    for index, path in enumerate(files, 1):
        base_name = os.path.splitext(os.path.basename(path))[0]
        ext = os.path.splitext(path)[1].lower()
        print_info(f"[{index}/{len(files)}] {os.path.basename(path)}")
        try:
            if as_so:
                compile_to_so(path, os.path.join(out_dir, base_name),
                              opt_level, other_flags, site_install, clang_extra)
            elif ext in C_SOURCE_EXTS:
                compile_c_source(path, os.path.join(out_dir, base_name),
                                 opt_level, other_flags, clang_extra)
            else:
                compile_executable(path, os.path.join(out_dir, base_name),
                                   opt_level, other_flags, run, script_args, clang_extra)
        except SystemExit:
            failed.append(path)

    if failed:
        print_error(f"{len(failed)} file(s) failed: " +
                    ', '.join(os.path.basename(f) for f in failed))
        sys.exit(1)

def install_so(so_path, py_lib_path, py_version):
    site_dir = f"{py_lib_path}/python{py_version}/site-packages"
    if not os.path.exists(site_dir):
        site_dir = os.path.join(sys.prefix, 'lib', f'python{py_version}', 'site-packages')
    os.makedirs(site_dir, exist_ok=True)
    target = os.path.join(site_dir, os.path.basename(so_path))
    shutil.copy2(so_path, target)
    os.chmod(target, 0o755)
    print_info(f"Installed to: {target}")


def resolve_bundle_output(input_dir, output, default_module, as_so):
    """Return (output_path, module_name) for a bundled build."""
    ext_suffix = get_ext_suffix()
    is_dir_output = bool(output) and (output.endswith(os.sep) or os.path.isdir(output))

    if as_so:
        if not output:
            module_name = default_module
            return (os.path.join(os.path.abspath(input_dir),
                                 module_name + ext_suffix), module_name)
        if is_dir_output:
            module_name = default_module
            return (os.path.join(output, module_name + ext_suffix), module_name)

        out_path = output
        base = os.path.basename(out_path)
        if base.endswith(ext_suffix):
            raw = base[:-len(ext_suffix)]
        elif base.endswith('.so'):
            raw = base[:-3]
        else:
            raw = os.path.splitext(base)[0]
            out_path = out_path + ext_suffix
        return out_path, sanitize_module_name(raw)

    if not output:
        return (os.path.join(os.path.abspath(input_dir),
                             default_module), default_module)
    if is_dir_output:
        return (os.path.join(output, default_module), default_module)
    return output, default_module


def compile_directory_bundle(input_dir, output, opt_level, other_flags,
                             site_install, as_so, run, script_args, clang_extra,
                             entry_name=None):
    """Bundle a directory into one executable / shared library.

    The entry file is compiled with ``cython --embed``.  Every other file is
    compiled as a normal Cython module.  All generated C files are compiled
    to object files and linked together into a single binary.
    """
    if as_so and run:
        print_error("-run cannot be used with -so")
        sys.exit(1)

    files = collect_directory_files(input_dir, include_c=False)
    if not files:
        print_error(f"No Python source files found in: {input_dir}")
        sys.exit(1)

    all_files = collect_directory_files(input_dir, include_c=True)
    ignored = [f for f in all_files if f not in files]
    if ignored:
        print_warning("Ignoring non-Python files in --dir-one: " +
                      ', '.join(os.path.basename(f) for f in ignored))

    entry_file = choose_entry_file(files, as_so, entry_name)
    if not entry_file:
        print_error("Cannot determine the entry module. Use --entry <module> "
                    "(for example --entry main).")
        sys.exit(1)

    dir_name = os.path.basename(os.path.abspath(input_dir))
    default_module = sanitize_module_name(dir_name)

    compiler_type, compiler = find_compiler()
    if not compiler:
        print_error("No compiler found")
        sys.exit(1)

    py_version = get_python_version()
    py_include = find_python_dev()
    if not py_include:
        py_include = f"/data/data/com.termux/files/usr/include/python{py_version}"
    py_lib_path, py_lib_name = get_python_lib()

    out_path, out_module = resolve_bundle_output(
        input_dir, None if run else output, default_module, as_so)
    out_dir = os.path.dirname(os.path.abspath(out_path))
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError as e:
        print_error(f"Cannot create output directory '{out_dir}': {e}")
        sys.exit(1)

    print_info(f"Bundling {len(files)} file(s), entry: "
               f"{os.path.basename(entry_file)} -> {out_path}")

    work_dir = tempfile.mkdtemp(prefix='pycc_bundle_')
    try:
        # -run always builds in work_dir (and ignores -o); it is deleted after.
        final_out = os.path.join(work_dir, default_module) if run else out_path

        modules = prepare_bundle_modules(
            files, entry_file, out_module, work_dir, as_so)
        opt_flags = get_optimization_flags(opt_level, compiler_type)

        objects = []
        sibling_names = []
        for module_name, pyx_path, is_entry in modules:
            print_info(f"  {os.path.basename(pyx_path)}"
                       f"{' (entry, --embed)' if is_entry else ''}")
            c_path = os.path.join(work_dir, f"{module_name}.c")
            cython_generate(pyx_path, c_path, embed=is_entry)

            o_path = os.path.join(work_dir, f"{module_name}.o")
            compile_object(c_path, o_path, compiler, opt_flags, py_include,
                           other_flags, clang_extra)
            objects.append(o_path)
            if not is_entry:
                sibling_names.append(module_name)

        if not as_so:
            registry_c = os.path.join(work_dir, 'pycc_registry.c')
            with open(registry_c, 'w', encoding='utf-8') as f:
                f.write(build_registry_source(sibling_names))
            registry_o = os.path.join(work_dir, 'pycc_registry.o')
            compile_object(registry_c, registry_o, compiler, opt_flags,
                           py_include, other_flags, clang_extra)
            objects.insert(0, registry_o)

        link_bundle(objects, final_out, as_so, compiler, opt_flags,
                    py_lib_path, py_lib_name, other_flags, clang_extra)

        os.chmod(final_out, 0o755)
        add_compile_marker(final_out)

        if as_so and site_install:
            install_so(final_out, py_lib_path, py_version)

        if run:
            subprocess.run([os.path.abspath(final_out)] + script_args)
        else:
            print_info(f"{'Shared library' if as_so else 'Executable'}: {final_out}")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

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
        ext_suffix = get_ext_suffix()
        
        if output:
            so_output = output if output.endswith('.so') else f"{output}{ext_suffix}"
        else:
            base_name = os.path.splitext(os.path.basename(input_file))[0]
            so_output = f"{base_name}{ext_suffix}"
        
        if file_ext in ['.py', '.pyx']:
            out_base = os.path.basename(so_output)
            if out_base.endswith(ext_suffix):
                module_name = out_base[:-len(ext_suffix)]
            else:
                module_name = os.path.splitext(out_base)[0]
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
            install_so(so_output, py_lib_path, py_version)
        else:
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
            final_output = os.path.join(work_dir, base_name)
        else:
            final_output = output if output else f"./{base_name}"
        
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
        
        if not run:
            print_info(f"Executable: {final_output}")
        else:
            subprocess.run([os.path.abspath(final_output)] + script_args)
            
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
        print("       pycc --dir [options] <directory>")
        print("       pycc --dir-one [options] <directory>")
        print("\nOptions:")
        print("  -O, --option        Pass extra args to clang (any position)")
        print("  -B, --best          Best optimization")
        print("  --python <ver>      Specify Python version (default: PYCC_PY_VERSION)")
        print("  -o, --output        Exact output name (directory with --dir)")
        print("  -run                Compile and run")
        print("  -c                  Generate C file (.c)")
        print("  -cpp                Generate C++ file (.cpp)")
        print("  -so                 Generate shared library (<name><EXT_SUFFIX>)")
        print("  --dir               Compile every file in a directory separately")
        print("  --dir-one, -one     Bundle all files in a directory into one output")
        print("                      (entry is --embed, others become objects)")
        print("  --entry <name>      Entry module for --dir-one")
        print("                      (default: __main__ / main / <directory name>)")
        print("\nExamples:")
        print("  pycc app.py                     -> ./app")
        print("  pycc --dir src/                 -> src/<file> for every file")
        print("  pycc -so --dir src/ -o build/   -> build/<file><EXT_SUFFIX>")
        print("  pycc --dir-one src/ -o myapp    -> ./myapp")
        print("  pycc -so --dir-one src/ -o lib  -> ./lib<EXT_SUFFIX>")
        print("  --site, -s          Install to site-packages (with -so)")
        print("  -v                  Verbose mode")
        print("  -q                  Quiet mode")
        print("  -###                Show commands only")
        print("  --version           Version info")
        print("  --help, -h          This help")
        print("\nEnvironment:")
        print("  PYCC_PY_VERSION     Python version")
        print("  PYCC_EXT_SUFFIX     Override C extension suffix")

        return
    
    if len(sys.argv) < 2:
        print_error("Missing input file")
        sys.exit(1)
    
    input_file = None
    other_args = []
    script_args = []
    opt_level = 'default'
    clang_option_args = []
    entry_name = None
    
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
            elif arg == '--entry':
                try:
                    entry_name = next(args_iter)
                except StopIteration:
                    print_error("--entry requires a module name")
                    sys.exit(1)
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

    dir_mode = '--dir' in other_args
    dir_one = '--dir-one' in other_args or '-one' in other_args
    if dir_mode and dir_one:
        print_error("Only one of --dir and --dir-one allowed")
        sys.exit(1)

    if os.path.isdir(input_file):
        if not (dir_mode or dir_one):
            print_error("Input is a directory; use --dir or --dir-one")
            sys.exit(1)
    elif dir_mode or dir_one:
        print_error("--dir and --dir-one require a directory")
        sys.exit(1)

    if dir_mode or dir_one:
        if '-c' in other_args or '-cpp' in other_args:
            print_error("-c/-cpp are not supported with --dir/--dir-one")
            sys.exit(1)

        as_so = '-so' in other_args
        run = '-run' in other_args
        site_install = '--site' in other_args or '-s' in other_args
        output, other_flags = split_directory_args(other_args)
        if run:
            # -run always builds in a temporary directory.
            output = None

        if dir_one:
            compile_directory_bundle(input_file, output, opt_level, other_flags,
                                     site_install, as_so, run, script_args,
                                     all_clang_extra, entry_name)
        else:
            compile_directory(input_file, output, opt_level, other_flags,
                              site_install, as_so, run, script_args,
                              all_clang_extra)
        return

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
        output = extract_output_arg(other_args)
        other_flags = [a for a in other_args
                       if a.startswith('-') and a not in ['-o', '--output']]
        compile_c_source(input_file, output, opt_level, other_flags,
                         all_clang_extra)
        return
    
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
